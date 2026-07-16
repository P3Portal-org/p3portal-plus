# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-101: Ausführungs-Zustandsmaschine der Template-Replikation.

Preflight (read-only) treibt das Modal; der Start baut aus der Ziel-Auswahl einen
Ausführungs-Plan (shared-Ziele → **eine** Kopie, N→1) und dispatcht einen Job-Worker,
der pro Operation ``clone → migrate → to_template`` (lokal) bzw. ``clone → to_template``
(shared) über die PROJ-102-Core-Primitive ausführt, live protokolliert und bei Fehlern
die angelegte Zwischen-VM aufräumt (Teilerfolg pro Operation).
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import HTTPException, status
from sqlalchemy import text

from backend.db.database import get_db
from backend.models.jobs import JobResponse
from backend.services.nodes_service import NodeRow, get_node_for_proxmox_name
from backend.services.proxmox import ProxmoxAuth, ProxmoxClient
# PROJ-102-Wiederverwendung: Log-/Task-/Status-Helfer (Plus → Core erlaubt).
from backend.services.vm_lifecycle_service import (
    _humanize_proxmox_error,
    _LogFile,
    _now,
    _set_finished,
    _set_running,
    _tail_task,
)

from .schemas import (
    PreflightResponse,
    PreflightStorage,
    PreflightTargetNode,
    ReplicateRequest,
)

logger = logging.getLogger(__name__)

# Disk-Config-Keys, deren Wert mit "<storage>:..." beginnt.
_DISK_KEY_RE = ("scsi", "virtio", "ide", "sata", "efidisk", "tpmstate")


def _admin_client(node_row: NodeRow) -> tuple[ProxmoxClient, ProxmoxAuth]:
    """Per-Installation Admin-Client (Clone/Migrate/Template brauchen erhöhte Rechte)."""
    if not node_row.admin_token_id or not node_row.admin_token_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Admin service account not configured for node '{node_row.name}'",
        )
    client = ProxmoxClient(base_url=node_row.url, verify_ssl=node_row.verify_ssl)
    auth = ProxmoxAuth(kind="token", value=node_row.admin_token_id, secret=node_row.admin_token_secret)
    return client, auth


def _first_disk_storage(config: dict) -> str | None:
    """Storage-Name der ersten Daten-Disk (part vor ':'), oder None."""
    for key, val in config.items():
        if not isinstance(val, str) or ":" not in val:
            continue
        if not any(key.startswith(p) and key[len(p):].isdigit() for p in _DISK_KEY_RE):
            continue
        if "media=cdrom" in val or key.startswith("ide") and "cdrom" in val:
            continue
        return val.split(":", 1)[0].strip()
    return None


async def _image_storages(client: ProxmoxClient, auth: ProxmoxAuth, node: str) -> list[dict]:
    return await client.get_node_image_storages(auth, node)


def _storage_shared(storages: list[dict], name: str) -> bool:
    for s in storages:
        if str(s.get("storage", "")) == name:
            return bool(int(s.get("shared", 0) or 0))
    return False


def _installation_nodes(node_row: NodeRow) -> list[str]:
    """Alle PVE-Node-Namen dieser Installation (dedup, Reihenfolge stabil).

    PROJ-26-Modell: ``proxmox_node`` ist die **primäre** Node, ``cluster_nodes``
    listet nur die **zusätzlichen** Member. Die vollständige Node-Menge (und damit
    der zulässige Ziel-Kreis der Replikation) ist die Vereinigung beider — sonst
    fällt die primäre Node als Replikations-Ziel systematisch heraus.
    """
    names = [node_row.proxmox_node, *(node_row.cluster_nodes or [])]
    return [n for n in dict.fromkeys(names) if n]


# ── Preflight ─────────────────────────────────────────────────────────────────

async def preflight(source_node: str, source_vmid: int) -> PreflightResponse:
    """Quell-Storage-Status + verfügbare Ziel-Nodes (alle anderen Nodes der Installation)."""
    node_row = await get_node_for_proxmox_name(source_node)
    if node_row is None:
        raise HTTPException(status_code=422, detail="Unknown source node")
    client, auth = _admin_client(node_row)
    try:
        config = await client.get_vm_config(auth, source_node, source_vmid, "qemu")
        src_storages = await _image_storages(client, auth, source_node)
    except httpx.HTTPStatusError as exc:
        _raise_proxmox(exc)
    except httpx.RequestError:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Could not reach Proxmox API")

    is_template = str(config.get("template", 0)) in ("1", "True")
    name = str(config.get("name") or f"template-{source_vmid}")
    disk_storage = _first_disk_storage(config)
    source_shared = bool(disk_storage) and _storage_shared(src_storages, disk_storage)

    target_names = [n for n in _installation_nodes(node_row) if n != source_node]
    targets: list[PreflightTargetNode] = []
    for tn in sorted(target_names):
        try:
            raw = await _image_storages(client, auth, tn)
        except Exception:
            raw = []
        targets.append(PreflightTargetNode(
            node=tn,
            storages=[
                PreflightStorage(
                    name=str(s.get("storage", "")),
                    type=str(s.get("type", "")),
                    shared=bool(int(s.get("shared", 0) or 0)),
                    avail=int(s.get("avail", 0) or 0),
                    total=int(s.get("total", 0) or 0),
                )
                for s in raw if s.get("storage")
            ],
        ))

    return PreflightResponse(
        source_node=source_node, source_vmid=source_vmid, source_name=name,
        is_template=is_template, source_shared=source_shared, source_storage=disk_storage,
        single_node=not target_names, targets=targets,
    )


def _raise_proxmox(exc: httpx.HTTPStatusError):
    code = exc.response.status_code
    if code in (401, 403):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Proxmox rejected the request – admin token missing privileges")
    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Proxmox API error {code}")


# ── Start / Plan-Bau ───────────────────────────────────────────────────────────

async def start_replication(current_user, req: ReplicateRequest) -> JobResponse:
    """Validiert Quelle + Ziele, baut den Plan, dispatcht den Worker."""
    node_row = await get_node_for_proxmox_name(req.source_node)
    if node_row is None:
        raise HTTPException(status_code=422, detail="Unknown source node")
    client, auth = _admin_client(node_row)

    try:
        config = await client.get_vm_config(auth, req.source_node, req.source_vmid, "qemu")
        src_storages = await _image_storages(client, auth, req.source_node)
    except httpx.HTTPStatusError as exc:
        _raise_proxmox(exc)
    except httpx.RequestError:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Could not reach Proxmox API")

    if str(config.get("template", 0)) not in ("1", "True"):
        raise HTTPException(status_code=422, detail="Source is not a template")
    source_name = str(config.get("name") or f"template-{req.source_vmid}")
    disk_storage = _first_disk_storage(config)
    if disk_storage and _storage_shared(src_storages, disk_storage):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Source already on shared storage – already cluster-wide, no replication needed",
        )

    valid_targets = {n for n in _installation_nodes(node_row) if n != req.source_node}

    # Ziel-Storages je Node cachen + shared-Flag authoritativ ermitteln (AC-STORAGE-4).
    node_storage_cache: dict[str, list[dict]] = {}
    local_ops: list[dict] = []
    shared_by_storage: dict[str, dict] = {}      # dedup shared-Ziele → 1 Op (N→1)

    for tgt in req.targets:
        if tgt.node not in valid_targets:
            raise HTTPException(
                status_code=422,
                detail=f"'{tgt.node}' is not another node of this cluster",
            )
        if tgt.node not in node_storage_cache:
            try:
                node_storage_cache[tgt.node] = await _image_storages(client, auth, tgt.node)
            except Exception:
                node_storage_cache[tgt.node] = []
        if not any(str(s.get("storage")) == tgt.storage for s in node_storage_cache[tgt.node]):
            raise HTTPException(
                status_code=422,
                detail=f"Storage '{tgt.storage}' not available on node '{tgt.node}'",
            )
        shared = _storage_shared(node_storage_cache[tgt.node], tgt.storage)
        if shared:
            # N Nodes mit demselben shared Storage → eine Kopie clusterweit.
            shared_by_storage.setdefault(tgt.storage, {
                "kind": "shared", "storage": tgt.storage, "newid": tgt.newid,
            })
        else:
            local_ops.append({
                "kind": "local", "node": tgt.node, "storage": tgt.storage, "newid": tgt.newid,
            })

    plan = list(shared_by_storage.values()) + local_ops
    if not plan:
        raise HTTPException(status_code=422, detail="No replication operations to perform")

    # Concurrency-Guard: kein zweiter Lauf auf dasselbe Quell-Template (Abschnitt K).
    label = f"replicate:{req.source_node}/{req.source_vmid}"
    async with get_db() as db:
        row = (await db.execute(
            text("SELECT COUNT(*) AS c FROM jobs WHERE type='template_replication' "
                 "AND playbook=:pb AND status IN ('pending','running')"),
            {"pb": label},
        )).mappings().fetchone()
    if row and int(row["c"]) > 0:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="A replication for this template is already running")

    # Job anlegen (neuer Typ-String, kein Schema-/Status-Delta).
    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    params = {
        "source_node": req.source_node, "source_vmid": req.source_vmid,
        "source_name": source_name, "operations": len(plan),
    }
    async with get_db() as db:
        await db.execute(
            text("INSERT INTO jobs (id, type, playbook, status, created_at, username, params) "
                 "VALUES (:id, 'template_replication', :pb, 'pending', :now, :user, :params)"),
            {"id": job_id, "pb": label, "now": now, "user": current_user.username,
             "params": json.dumps(params)},
        )
        await db.commit()

    asyncio.create_task(run_replication_job(
        job_id, node_row.id, req.source_node, req.source_vmid, source_name,
        plan, req.remove_source_after_shared, current_user.username,
    ))
    return JobResponse(
        id=job_id, type="template_replication", playbook=label, status="pending",
        created_at=now, username=current_user.username, params=params,
    )


# ── Worker ──────────────────────────────────────────────────────────────────────

async def _has_template_named(client, auth, node: str, name: str) -> bool:
    """True wenn auf *node* bereits ein Template gleichen Namens existiert (Idempotenz)."""
    try:
        vms = await client.get_node_vms(auth, node)
    except Exception:
        return False
    for vm in vms:
        if str(vm.get("template", 0)) in ("1", "True") and str(vm.get("name", "")) == name:
            return True
    return False


async def _cleanup(log: _LogFile, client, auth, node: str, vmid: int) -> None:
    """Verwaiste Zwischen-VM aufräumen (AC-ERR-1/2)."""
    try:
        upid = await client.delete_vm(auth, node, vmid, "qemu")
        if upid:
            await _tail_task(log, client, auth, node, upid, "")  # best-effort
        log.write(f"[cleanup] Zwischen-VM {vmid} auf {node} entfernt.")
    except Exception as exc:
        log.write(f"[warn] Aufräumen der VM {vmid} auf {node} fehlgeschlagen: {exc} "
                  f"(verwaiste VM manuell prüfen).")


async def _template_vmid_range() -> tuple[int, int]:
    """Konfigurierter Template-/Packer-VMID-Bereich (gleich wie der Packer-Builder).

    Templates werden über Packer gebaut; die Auto-Vergabe der replizierten Kopie soll
    denselben Bereich nutzen (`packer_vmid_min`/`packer_vmid_max`, Default 100–999999).
    """
    from backend.services.settings_service import get_setting
    min_id = int(await get_setting("packer_vmid_min") or "100")
    max_id = int(await get_setting("packer_vmid_max") or "999999")
    return min_id, max_id


async def _next_vmid(client, auth, provided: int | None, min_id: int, max_id: int) -> int:
    if provided is not None:
        free = None
        try:
            free = await client.get_next_vmid(auth, provided, provided)
        except ValueError:
            free = None
        if free != provided:
            raise ValueError(f"VMID {provided} ist bereits belegt")
        return provided
    return await client.get_next_vmid(auth, min_id, max_id)


async def run_replication_job(
    job_id: str, portal_node_id: int, source_node: str, source_vmid: int,
    source_name: str, plan: list[dict], remove_source_after_shared: bool, username: str,
) -> None:
    """Arbeitet den Plan pro Operation ab, protokolliert live, räumt bei Fehlern auf."""
    from backend.services.nodes_service import get_node
    log = _LogFile(job_id)
    await _set_running(job_id, str(log.path))
    log.write(f"[info] Template-Replikation '{source_name}' (VMID {source_vmid}) von {source_node}.")

    node_row = await get_node(portal_node_id)
    if node_row is None:
        log.write("[error] Installation nicht mehr auffindbar – Abbruch.")
        await _set_finished(job_id, False)
        return
    client, auth = _admin_client(node_row)
    vmid_min, vmid_max = await _template_vmid_range()

    ok_count = 0
    fail_count = 0
    shared_ok = False

    for idx, op in enumerate(plan, 1):
        kind = op["kind"]
        try:
            if kind == "shared":
                header = f"[op {idx}/{len(plan)}] shared-Heben auf Datastore '{op['storage']}' (eine Kopie clusterweit)."
            else:
                header = f"[op {idx}/{len(plan)}] Kopie auf Node '{op['node']}' (Datastore '{op['storage']}')."
            log.write(header)

            target_node = source_node if kind == "shared" else op["node"]
            # Idempotenz: existiert das Template auf der Ziel-Node schon → überspringen.
            if kind == "local" and await _has_template_named(client, auth, target_node, source_name):
                log.write(f"[skip] Auf '{target_node}' existiert bereits ein Template '{source_name}' – übersprungen.")
                ok_count += 1
                continue

            newid = await _next_vmid(client, auth, op.get("newid"), vmid_min, vmid_max)
            log.write(f"[info] Ziel-VMID {newid}.")

            # Schritt 1: Clone auf der Quell-Node.
            clone_storage = op["storage"] if kind == "shared" else None
            upid = await client.clone_vm(
                auth, source_node, source_vmid, newid, name=source_name,
                target_storage=clone_storage, full=True, vm_type="qemu",
            )
            log.write(f"[info] Clone gestartet (VMID {newid}) …")
            if upid and not await _tail_task(log, client, auth, source_node, upid, job_id):
                log.write(f"[error] Clone fehlgeschlagen (op {idx}).")
                await _cleanup(log, client, auth, source_node, newid)
                fail_count += 1
                continue

            current_node = source_node
            if kind == "local":
                # Schritt 2: Offline-Migration auf die Ziel-Node.
                log.write(f"[info] Migration nach '{op['node']}' (Ziel-Storage '{op['storage']}') …")
                m_upid = await client.migrate_vm(
                    auth, source_node, newid, op["node"],
                    target_storage=op["storage"], vm_type="qemu",
                )
                if m_upid and not await _tail_task(log, client, auth, source_node, m_upid, job_id):
                    log.write(f"[error] Migration fehlgeschlagen (op {idx}).")
                    await _cleanup(log, client, auth, source_node, newid)
                    fail_count += 1
                    continue
                current_node = op["node"]

            # Schritt 3: Zu Template konvertieren (auf der jetzigen Node).
            log.write(f"[info] Konvertiere VMID {newid} auf '{current_node}' zu Template …")
            t_upid = await client.convert_to_template(auth, current_node, newid, "qemu")
            if t_upid and not await _tail_task(log, client, auth, current_node, t_upid, job_id):
                log.write(f"[error] Konvertierung fehlgeschlagen (op {idx}).")
                await _cleanup(log, client, auth, current_node, newid)
                fail_count += 1
                continue

            log.write(f"[ok] Template '{source_name}' auf '{current_node}' erstellt (VMID {newid}).")
            ok_count += 1
            if kind == "shared":
                shared_ok = True

        except httpx.HTTPStatusError as exc:
            log.write(_humanize_proxmox_error(exc, f"Replikation op {idx}"))
            fail_count += 1
        except ValueError as exc:
            log.write(f"[error] op {idx}: {exc}")
            fail_count += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception("PROJ-101: replication op %s crashed", idx)
            log.write(f"[error] op {idx}: unerwarteter Fehler ({exc}).")
            fail_count += 1

    # Optional: lokale Quelle nach erfolgreichem shared-Heben entfernen.
    if shared_ok and remove_source_after_shared and fail_count == 0:
        log.write(f"[info] Entferne lokale Quelle {source_vmid} auf {source_node} (auf Wunsch) …")
        await _cleanup(log, client, auth, source_node, source_vmid)

    all_ok = fail_count == 0
    log.write(f"[status] Replikation beendet: {ok_count} erfolgreich, {fail_count} fehlgeschlagen.")
    await _set_finished(job_id, all_ok)
