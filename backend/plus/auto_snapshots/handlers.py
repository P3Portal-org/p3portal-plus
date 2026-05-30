# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-77 – Action-Handler für `auto_config_snapshot` und `auto_vm_snapshot`.

Beide Handler werden via PROJ-70 ``get_scheduled_job_action_handlers()``
am Runner registriert und erhalten ``(job, config)`` als Argument.
Rückgabe: ``(output_json, exit_code)`` (PROJ-70-Vertrag).

Workflow (Sektion H):
  1. Targets auflösen (resolver.resolve_targets)
  2. Owner-Filter (silently skip non-owned + Audit pro Skip)
  3. asyncio.Semaphore(max_parallel)
  4. Per Target parallel:
     - Config-Handler: Hash-Check → create_snapshot(source='auto')
     - VM-Handler:    Pre-Resync, create_snapshot via Proxmox, Lock-Detect
  5. Rotation pro VM (rotation.rotate_*) NACH allen Creates
  6. Aggregat-Audit + RunSummary zurückgeben
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import text

from backend.db.database import get_db
from backend.services.audit_service import write_audit_log

from .collision_detector import is_locked_response
from .external_resync import report_prefix_collisions, sync_external_state
from .models import JOB_ID_SHORT_LEN, SNAP_NAME_PREFIX
from .permissions import is_owner_of
from .resolver import resolve_targets
from .rotation import (
    compute_gfs_tiers, delete_config_snapshots, determine_keep_set,
    insert_native_snapshot, list_active_config_snapshots,
    list_active_snapshots, mark_snapshots_rotated,
)
from .schemas import (
    AutoConfigJobConfig, AutoVmJobConfig, FailedDetail, RunSummary, TargetSpec,
)

logger = logging.getLogger(__name__)


# ─── Hilfsfunktionen ────────────────────────────────────────────────────────


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _job_id_short(job_id: str) -> str:
    """Erste ``JOB_ID_SHORT_LEN`` Zeichen der UUID-hex."""
    cleaned = job_id.replace("-", "")
    return cleaned[:JOB_ID_SHORT_LEN]


def build_snapname(job_id: str, now: datetime, suffix_seconds: bool = False) -> str:
    """``p3auto_{job_id_short}_{YYYYMMDD}_{HHMM}`` (+ optional _{SS} bei Kollision)."""
    base = f"{SNAP_NAME_PREFIX}{_job_id_short(job_id)}_{now.strftime('%Y%m%d_%H%M')}"
    if suffix_seconds:
        return f"{base}_{now.strftime('%S')}"
    return base


def _hash_payload(payload: dict) -> str:
    """SHA-256 über kanonische JSON-Darstellung (gleicher Algorithmus wie PROJ-74._etag_of)."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


async def _get_node_name_to_id(name: str) -> int | None:
    """Lookup portal_node_id für einen Proxmox-Node-Namen."""
    async with get_db() as db:
        result = await db.execute(
            text("SELECT id FROM nodes WHERE proxmox_node = :n OR name = :n LIMIT 1"),
            {"n": name},
        )
        row = result.fetchone()
        return int(row[0]) if row else None


async def _parse_target_spec(config: dict, job_id: str) -> TargetSpec | None:
    """Parsed das ``target_spec``-Dict aus der Job-Config in ein TargetSpec-Modell."""
    raw = config.get("target_spec")
    if not isinstance(raw, dict):
        return None
    try:
        return TargetSpec.model_validate(raw)
    except Exception as exc:
        logger.warning("PROJ-77 job=%s ungültiges target_spec: %s", job_id, exc)
        return None


async def _get_user_id_for_username(username: str | None) -> int | None:
    if not username:
        return None
    async with get_db() as db:
        result = await db.execute(
            text("SELECT id FROM local_users WHERE username = :u LIMIT 1"),
            {"u": username},
        )
        row = result.fetchone()
        return int(row[0]) if row else None


async def _proxmox_node_for_portal_node_id(portal_node_id: int) -> tuple[str, object] | None:
    """Lookup Proxmox-Node-Name + NodeRow für einen portal_node_id.

    Liefert ``(proxmox_node_name, node_row)`` oder None bei Fehler.
    """
    from backend.services.nodes_service import get_node
    try:
        node = await get_node(portal_node_id)
        if not node:
            return None
        return node.proxmox_node, node
    except Exception as exc:  # pragma: no cover
        logger.warning("PROJ-77 _proxmox_node_for_portal_node_id %s: %s", portal_node_id, exc)
        return None


# ─── Pre-Run: Owner-Re-Check ────────────────────────────────────────────────


async def _check_owner_alive(username: str | None) -> bool:
    if not username:
        return True  # Admin oder system
    async with get_db() as db:
        result = await db.execute(
            text("SELECT 1 FROM local_users WHERE username = :u AND active = 1 LIMIT 1"),
            {"u": username},
        )
        return result.fetchone() is not None


async def _pause_job_ownerless(job_id: str, username: str | None) -> None:
    """Setzt Job auf last_run_status='paused_ownerless', deaktiviert ihn."""
    async with get_db() as db:
        await db.execute(
            text(
                "UPDATE scheduled_jobs SET active = 0, last_run_status = 'paused_ownerless', "
                "updated_at = :now, next_run_at = NULL WHERE id = :id"
            ),
            {"now": _iso(_utc_now()), "id": job_id},
        )
        await db.commit()
    await write_audit_log(
        "auto_snapshot_job_paused_ownerless",
        username="system",
        detail=json.dumps({"job_id": job_id, "username": username}),
    )


async def _owner_user_id_or_none(username: str | None) -> int | None:
    """Liefert user_id wenn user_role != 'admin', sonst None (Admin überspringt Owner-Filter)."""
    if not username:
        return None
    async with get_db() as db:
        result = await db.execute(
            text("SELECT id, role FROM local_users WHERE username = :u LIMIT 1"),
            {"u": username},
        )
        row = result.fetchone()
        if not row:
            return None
        uid, role = int(row[0]), row[1]
        if role == "admin":
            return None  # Admin filtert nicht
        return uid


# ─── Handler-Einstieg: auto_config_snapshot ─────────────────────────────────


async def handle_auto_config_snapshot(job: dict, config: dict) -> tuple[str, int]:
    """Run-Logik für Action-Type ``auto_config_snapshot``."""
    job_id = job["id"]
    created_by = job.get("created_by") or ""

    if not await _check_owner_alive(created_by):
        await _pause_job_ownerless(job_id, created_by)
        return _summary_to_output(RunSummary(status="failed")), 1

    try:
        cfg = AutoConfigJobConfig.model_validate(config)
    except Exception as exc:
        logger.warning("PROJ-77 job=%s ungültige Auto-Config-Config: %s", job_id, exc)
        return f"[config_error] {exc}", 1

    targets = await resolve_targets(cfg.target_spec)
    await write_audit_log(
        "auto_snapshot_targets_resolved",
        username=created_by or "system",
        detail=json.dumps({"job_id": job_id, "count": len(targets)}),
    )

    if not targets:
        return _summary_to_output(RunSummary(status="skipped", targets_total=0)), 0

    summary = RunSummary(status="success", targets_total=len(targets))

    # Owner-Filter (nicht-Admin-Jobs)
    owner_uid = await _owner_user_id_or_none(created_by)
    work_targets: list[tuple[int, int, str]] = []
    if owner_uid is None:
        work_targets = list(targets)
    else:
        for nid, vmid, kind in targets:
            if await is_owner_of(owner_uid, nid, vmid, kind):
                work_targets.append((nid, vmid, kind))
            else:
                summary.skipped_not_owner_count += 1
                await write_audit_log(
                    "auto_snapshot_target_skipped_not_owner",
                    username=created_by or "system",
                    detail=json.dumps({
                        "job_id": job_id, "portal_node_id": nid, "vmid": vmid, "kind": kind,
                    }),
                )

    if not work_targets:
        summary.status = "skipped"
        return _summary_to_output(summary), 0

    sema = asyncio.Semaphore(max(1, min(10, cfg.max_parallel)))
    user_id = await _get_user_id_for_username(created_by) if created_by else None

    async def _one(triple: tuple[int, int, str]) -> None:
        nid, vmid, kind = triple
        async with sema:
            await _process_config_target(
                summary, cfg, job_id, created_by, user_id, nid, vmid, kind,
            )

    await asyncio.gather(*(_one(t) for t in work_targets), return_exceptions=False)

    # Rotation pro VM (auto-Config-Snapshots)
    for nid, vmid, kind in work_targets:
        await _rotate_config_for_target(summary, cfg, job_id, nid, vmid, kind, created_by)

    summary.status = _determine_overall_status(summary)
    await write_audit_log(
        "auto_config_snapshot_rotated",
        username=created_by or "system",
        detail=json.dumps({"job_id": job_id, "rotated": summary.rotated_count}),
    )
    await write_audit_log(
        "auto_snapshot_run_completed",
        username=created_by or "system",
        detail=json.dumps({
            "job_id": job_id, "action_type": "auto_config_snapshot",
            "status": summary.status, "targets_total": summary.targets_total,
            "created_count": summary.created_count,
            "skipped_no_change_count": summary.skipped_no_change_count,
            "skipped_not_owner_count": summary.skipped_not_owner_count,
            "failed_count": summary.failed_count,
            "rotated_count": summary.rotated_count,
        }),
    )

    exit_code = 0 if summary.status in ("success", "skipped") else (
        2 if summary.status == "partial_success" else 1
    )
    return _summary_to_output(summary), exit_code


async def _process_config_target(
    summary: RunSummary,
    cfg: AutoConfigJobConfig,
    job_id: str,
    actor_username: str,
    actor_user_id: int | None,
    portal_node_id: int,
    vmid: int,
    kind: str,
) -> None:
    node_info = await _proxmox_node_for_portal_node_id(portal_node_id)
    if not node_info:
        summary.failed_count += 1
        summary.failed_details.append(FailedDetail(
            node="?", vmid=vmid, error_class="node_lookup", error_msg="portal_node not found",
        ))
        return
    proxmox_node, _node_row = node_info

    # Live-Config holen + Hash vergleichen
    try:
        from backend.plus.config_snapshots.service import _admin_auth, _get_node_or_404
        node = await _get_node_or_404(portal_node_id)
        client, auth = _admin_auth(node)
        vm_type = "qemu" if kind == "qemu" else "lxc"
        live_raw = await client.get_vm_config(auth, proxmox_node, vmid, vm_type=vm_type)
    except Exception as exc:
        summary.failed_count += 1
        summary.failed_details.append(FailedDetail(
            node=proxmox_node, vmid=vmid, error_class="proxmox_unreachable", error_msg=str(exc),
        ))
        return

    # description + digest filtern (analog PROJ-74._create_snapshot_impl)
    live_payload = dict(live_raw)
    live_payload.pop("description", None)
    live_payload.pop("digest", None)
    live_hash = _hash_payload(live_payload)

    if cfg.skip_if_no_changes:
        last_hash = await _get_last_auto_config_hash(job_id, portal_node_id, vmid, kind)
        if last_hash and last_hash == live_hash:
            summary.skipped_no_change_count += 1
            await write_audit_log(
                "auto_config_snapshot_skipped_no_change",
                username=actor_username or "system",
                detail=json.dumps({
                    "job_id": job_id, "portal_node_id": portal_node_id,
                    "vmid": vmid, "kind": kind, "etag": live_hash,
                }),
            )
            return

    # Snapshot anlegen via PROJ-74-Service (mit source='auto' + FK)
    try:
        from backend.plus.config_snapshots.service import create_snapshot as _create
        note = cfg.note or f"Auto-Config-Snapshot (Job {_job_id_short(job_id)})"
        out = await _create(
            portal_node_id=portal_node_id,
            proxmox_node=proxmox_node,
            vmid=vmid,
            kind=kind,
            note=note,
            name=None,
            created_by_user_id=actor_user_id,
            username=actor_username or "system",
            source="auto",
            payload_override=live_raw,
            created_by_scheduled_job_id=job_id,
        )
    except Exception as exc:
        summary.failed_count += 1
        summary.failed_details.append(FailedDetail(
            node=proxmox_node, vmid=vmid, error_class="snapshot_create_failed",
            error_msg=str(exc),
        ))
        return

    summary.created_count += 1
    await write_audit_log(
        "auto_config_snapshot_created",
        username=actor_username or "system",
        detail=json.dumps({
            "job_id": job_id, "snapshot_id": out.id,
            "portal_node_id": portal_node_id, "vmid": vmid, "kind": kind,
        }),
    )


async def _get_last_auto_config_hash(
    job_id: str, portal_node_id: int, vmid: int, kind: str,
) -> str | None:
    """Liefert SHA-256 des letzten auto-Snapshots derselben VM von diesem Job."""
    async with get_db() as db:
        result = await db.execute(
            text(
                "SELECT payload_json FROM vm_config_snapshots "
                "WHERE source='auto' AND created_by_scheduled_job_id=:jid "
                "  AND portal_node_id=:nid AND vmid=:vid AND kind=:k AND is_orphan=0 "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"jid": job_id, "nid": portal_node_id, "vid": vmid, "k": kind},
        )
        row = result.fetchone()
    if not row:
        return None
    try:
        return _hash_payload(json.loads(row[0]))
    except Exception:
        return None


async def _rotate_config_for_target(
    summary: RunSummary,
    cfg: AutoConfigJobConfig,
    job_id: str,
    portal_node_id: int,
    vmid: int,
    kind: str,
    actor_username: str,
) -> None:
    snapshots = await list_active_config_snapshots(job_id, portal_node_id, vmid, kind)
    if not snapshots:
        return
    keep_ids = set([s["id"] for s in snapshots[: max(0, cfg.keep_last)]])
    # GFS gilt für Config-Snapshots NICHT (Tiers nicht persistiert); nur keep_last greift.
    to_delete = [s["id"] for s in snapshots if s["id"] not in keep_ids]
    deleted = await delete_config_snapshots(to_delete)
    summary.rotated_count += deleted


# ─── Handler-Einstieg: auto_vm_snapshot ─────────────────────────────────────


async def handle_auto_vm_snapshot(job: dict, config: dict) -> tuple[str, int]:
    """Run-Logik für Action-Type ``auto_vm_snapshot`` (Proxmox-nativ)."""
    job_id = job["id"]
    created_by = job.get("created_by") or ""

    if not await _check_owner_alive(created_by):
        await _pause_job_ownerless(job_id, created_by)
        return _summary_to_output(RunSummary(status="failed")), 1

    try:
        cfg = AutoVmJobConfig.model_validate(config)
    except Exception as exc:
        logger.warning("PROJ-77 job=%s ungültige Auto-VM-Config: %s", job_id, exc)
        return f"[config_error] {exc}", 1

    targets = await resolve_targets(cfg.target_spec)
    await write_audit_log(
        "auto_snapshot_targets_resolved",
        username=created_by or "system",
        detail=json.dumps({"job_id": job_id, "count": len(targets)}),
    )

    if not targets:
        return _summary_to_output(RunSummary(status="skipped", targets_total=0)), 0

    summary = RunSummary(status="success", targets_total=len(targets))

    owner_uid = await _owner_user_id_or_none(created_by)
    work_targets: list[tuple[int, int, str]] = []
    if owner_uid is None:
        work_targets = list(targets)
    else:
        for nid, vmid, kind in targets:
            if await is_owner_of(owner_uid, nid, vmid, kind):
                work_targets.append((nid, vmid, kind))
            else:
                summary.skipped_not_owner_count += 1
                await write_audit_log(
                    "auto_snapshot_target_skipped_not_owner",
                    username=created_by or "system",
                    detail=json.dumps({
                        "job_id": job_id, "portal_node_id": nid, "vmid": vmid, "kind": kind,
                    }),
                )

    if not work_targets:
        summary.status = "skipped"
        return _summary_to_output(summary), 0

    # External-Resync 1× pro VM
    await _resync_external_state_for_targets(work_targets, created_by, job_id)

    sema = asyncio.Semaphore(max(1, min(10, cfg.max_parallel)))

    async def _one(triple: tuple[int, int, str]) -> None:
        nid, vmid, kind = triple
        async with sema:
            await _process_vm_target(summary, cfg, job_id, created_by, nid, vmid, kind)

    await asyncio.gather(*(_one(t) for t in work_targets), return_exceptions=False)

    # Rotation NACH allen Creates
    for nid, vmid, kind in work_targets:
        await _rotate_native_for_target(summary, cfg, job_id, nid, vmid, kind, created_by)

    summary.status = _determine_overall_status(summary)

    # Audit (Aggregat für Creates, Per-VM bereits für Skips/Errors)
    if summary.created_count > 0:
        sample = [f"{nid}/{vmid}" for nid, vmid, _ in work_targets[:10]]
        await write_audit_log(
            "auto_vm_snapshot_created_summary",
            username=created_by or "system",
            detail=json.dumps({
                "job_id": job_id, "created_count": summary.created_count,
                "first_10_vmids": sample,
            }),
        )
    await write_audit_log(
        "auto_vm_snapshot_rotated",
        username=created_by or "system",
        detail=json.dumps({"job_id": job_id, "rotated": summary.rotated_count}),
    )
    await write_audit_log(
        "auto_snapshot_run_completed",
        username=created_by or "system",
        detail=json.dumps({
            "job_id": job_id, "action_type": "auto_vm_snapshot",
            "status": summary.status, "targets_total": summary.targets_total,
            "created_count": summary.created_count,
            "skipped_locked_count": summary.skipped_locked_count,
            "skipped_not_owner_count": summary.skipped_not_owner_count,
            "failed_count": summary.failed_count,
            "rotated_count": summary.rotated_count,
        }),
    )

    exit_code = 0 if summary.status in ("success", "skipped") else (
        2 if summary.status == "partial_success" else 1
    )
    return _summary_to_output(summary), exit_code


async def _resync_external_state_for_targets(
    targets: list[tuple[int, int, str]],
    actor_username: str,
    job_id: str,
) -> None:
    """1× pro VM Proxmox-Snapshots laden, deleted_externally markieren, Prefix-Kollision auditieren."""
    for nid, vmid, kind in targets:
        node_info = await _proxmox_node_for_portal_node_id(nid)
        if not node_info:
            continue
        proxmox_node, _node_row = node_info
        try:
            from backend.plus.config_snapshots.service import _admin_auth, _get_node_or_404
            node = await _get_node_or_404(nid)
            client, auth = _admin_auth(node)
            vm_type = "qemu" if kind == "qemu" else "lxc"
            snaps = await client.get_snapshots(auth, proxmox_node, vmid, vm_type=vm_type)
        except Exception as exc:  # node offline o. ä. – ignorieren, Create-Phase wird scheitern
            logger.debug("PROJ-77 resync: konnte Proxmox-Snaps nicht laden: %s", exc)
            continue
        snap_names = {s.get("name") for s in snaps if isinstance(s, dict) and s.get("name")}
        _, external_prefixed = await sync_external_state(nid, proxmox_node, vmid, kind, snap_names)
        if external_prefixed:
            await report_prefix_collisions(nid, proxmox_node, vmid, kind, external_prefixed)


async def _process_vm_target(
    summary: RunSummary,
    cfg: AutoVmJobConfig,
    job_id: str,
    actor_username: str,
    portal_node_id: int,
    vmid: int,
    kind: str,
) -> None:
    node_info = await _proxmox_node_for_portal_node_id(portal_node_id)
    if not node_info:
        summary.failed_count += 1
        summary.failed_details.append(FailedDetail(
            node="?", vmid=vmid, error_class="node_lookup", error_msg="portal_node not found",
        ))
        return
    proxmox_node, _node_row = node_info

    vm_type = "qemu" if kind == "qemu" else "lxc"
    use_ram = False

    # include_ram: nur qemu+running, sonst silently skip mit Info-Audit
    if cfg.include_ram:
        if kind == "lxc":
            await write_audit_log(
                "auto_vm_snapshot_ram_skipped_lxc",
                username=actor_username or "system",
                detail=json.dumps({"job_id": job_id, "vmid": vmid, "node": proxmox_node}),
            )
        else:
            try:
                from backend.plus.config_snapshots.service import _admin_auth, _get_node_or_404
                node = await _get_node_or_404(portal_node_id)
                client, auth = _admin_auth(node)
                status = await client.get_vm_status_current(auth, proxmox_node, vmid, vm_type="qemu")
                if (status.get("status") or "").lower() == "running":
                    use_ram = True
                else:
                    await write_audit_log(
                        "auto_vm_snapshot_ram_skipped_vm_not_running",
                        username=actor_username or "system",
                        detail=json.dumps({"job_id": job_id, "vmid": vmid, "node": proxmox_node}),
                    )
            except Exception:
                pass  # bei Status-Fehler weiter ohne RAM

    # Snapshot anlegen (mit Retry bei Snapname-Kollision)
    now = _utc_now()
    snapname = build_snapname(job_id, now)
    description = cfg.note or "P3 auto-snapshot"

    upid: str | None = None
    last_exc: Exception | None = None
    locked = False
    for attempt in range(2):
        try:
            from backend.plus.config_snapshots.service import _admin_auth, _get_node_or_404
            node = await _get_node_or_404(portal_node_id)
            client, auth = _admin_auth(node)
            upid = await client.create_snapshot(
                auth, proxmox_node, vmid, snapname,
                description=description, vm_type=vm_type, vmstate=use_ram,
            )
            break  # OK
        except Exception as exc:
            last_exc = exc
            body = getattr(getattr(exc, "response", None), "text", str(exc))
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            if is_locked_response(status_code, body):
                locked = True
                break
            # Snapname-Kollision (Proxmox: "snapshot 'name' already exists" / 409)
            if attempt == 0 and (
                "already exists" in str(exc).lower()
                or (status_code is not None and status_code == 409)
            ):
                snapname = build_snapname(job_id, _utc_now(), suffix_seconds=True)
                continue
            break

    if locked:
        summary.skipped_locked_count += 1
        await write_audit_log(
            "auto_vm_snapshot_skipped_locked",
            username=actor_username or "system",
            detail=json.dumps({
                "job_id": job_id, "portal_node_id": portal_node_id,
                "vmid": vmid, "kind": kind, "snapname": snapname,
            }),
        )
        return

    if upid is None:
        summary.failed_count += 1
        msg = str(last_exc) if last_exc else "create_snapshot returned no UPID"
        summary.failed_details.append(FailedDetail(
            node=proxmox_node, vmid=vmid, error_class="snapshot_create_failed", error_msg=msg,
        ))
        await write_audit_log(
            "auto_vm_snapshot_failed",
            username=actor_username or "system",
            detail=json.dumps({
                "job_id": job_id, "vmid": vmid, "node": proxmox_node, "error": msg,
            }),
        )
        return

    # GFS-Tiers berechnen + DB-Insert
    tiers = await compute_gfs_tiers(
        job_id, portal_node_id, vmid, kind, gfs_enabled=cfg.gfs_enabled,
    )
    snapshot_id = uuid.uuid4().hex
    await insert_native_snapshot(
        snapshot_id, job_id, portal_node_id, proxmox_node, vmid, kind,
        snapname, include_ram=use_ram, gfs_tiers=tiers,
    )
    summary.created_count += 1


async def _rotate_native_for_target(
    summary: RunSummary,
    cfg: AutoVmJobConfig,
    job_id: str,
    portal_node_id: int,
    vmid: int,
    kind: str,
    actor_username: str,
) -> None:
    snapshots = await list_active_snapshots(job_id, portal_node_id, vmid, kind)
    if not snapshots:
        return
    keep = determine_keep_set(
        snapshots,
        keep_last=cfg.keep_last,
        keep_daily=cfg.keep_daily,
        keep_weekly=cfg.keep_weekly,
        keep_monthly=cfg.keep_monthly,
    )
    to_delete = [s for s in snapshots if s["id"] not in keep]
    if not to_delete:
        return

    node_info = await _proxmox_node_for_portal_node_id(portal_node_id)
    if not node_info:
        return
    proxmox_node, _node_row = node_info

    try:
        from backend.plus.config_snapshots.service import _admin_auth, _get_node_or_404
        node = await _get_node_or_404(portal_node_id)
        client, auth = _admin_auth(node)
    except Exception as exc:
        logger.warning("PROJ-77 rotate native: admin_auth failed: %s", exc)
        return

    vm_type = "qemu" if kind == "qemu" else "lxc"
    rotated_ids: list[str] = []
    for s in to_delete:
        try:
            await client.delete_snapshot(auth, proxmox_node, vmid, s["snapname"], vm_type=vm_type)
            rotated_ids.append(s["id"])
        except Exception as exc:
            logger.warning(
                "PROJ-77 rotate: Proxmox delete_snapshot %s/%d/%s fehlgeschlagen: %s",
                proxmox_node, vmid, s["snapname"], exc,
            )

    if rotated_ids:
        await mark_snapshots_rotated(rotated_ids, reason="keep_last_exceeded")
        summary.rotated_count += len(rotated_ids)


# ─── Output-Format ──────────────────────────────────────────────────────────


def _summary_to_output(summary: RunSummary) -> str:
    """Serialisiert RunSummary in scheduled_job_runs.output (max 50 KB)."""
    raw = summary.model_dump_json()
    return raw[:51200]


def _determine_overall_status(summary: RunSummary) -> str:
    """AC-RUN-1: success / partial_success / failed / skipped."""
    if summary.targets_total == 0:
        return "skipped"
    if summary.failed_count == 0 and summary.skipped_locked_count == 0:
        if summary.created_count == 0 and summary.skipped_no_change_count == 0:
            # nichts erstellt, nichts übersprungen, kein Fehler → wahrscheinlich alle Owner-skipped
            if summary.skipped_not_owner_count == summary.targets_total:
                return "skipped"
        return "success"
    if summary.created_count + summary.skipped_no_change_count > 0:
        return "partial_success"
    return "failed"
