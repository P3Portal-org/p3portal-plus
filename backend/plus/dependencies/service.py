# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-96: Service für VM-Abhängigkeiten.

CRUD + Validierung + Impact-Lookup + Topologie-Graph + Orphan-Verwaltung.

RBAC-Leitprinzip (Tech-Design L):
  - Anlegen verlangt, dass BEIDE VMs für den Ersteller sichtbar sind
    (fetch_visible_vm_resources, single-source mit Dashboard/Topologie).
  - Anzeigen liefert nur Kanten zwischen sichtbaren VMs (serverseitig gefiltert).
  - Die Impact-Warnung (get_dependents) ist beratend, nicht permission-gated.

VM-Identität immer (portal_node_id, vmid); installationsübergreifend erlaubt.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import text

from backend.core.deps import CurrentUser
from backend.db.database import get_db
from backend.models.cluster import VmInfo
from backend.services.audit_service import write_audit_log

from .schemas import (
    DepEdge,
    DepGuest,
    DependencyOut,
    DependencyTopologyResponse,
    VmDependenciesResponse,
)

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _installation_names() -> dict[int, str]:
    """Map konfigurierte portal_node_id → Installations-Name (best-effort)."""
    try:
        from backend.services.nodes_service import list_nodes
        rows = await list_nodes()
        return {row.id: row.name for row in rows}
    except Exception:
        return {}


async def _visible_index(current_user: CurrentUser) -> dict[tuple[int, int], VmInfo]:
    """Index {(portal_node_id, vmid) → VmInfo} über alle für den Nutzer sichtbaren VMs.

    Spannt alle Installationen (Multi-Node) → installationsübergreifend.
    VMs ohne konfigurierte portal_node_id (Single-Default-Node ohne Node-Eintrag)
    werden ausgelassen — eine Kante braucht eine FK-fähige Identität.
    """
    from backend.routers.cluster import fetch_visible_vm_resources
    vms = await fetch_visible_vm_resources(current_user, with_ip=False)
    return {
        (vm.portal_node_id, vm.vmid): vm
        for vm in vms
        if vm.portal_node_id is not None
    }


def _ui_type(vm_type: str) -> str:
    return "lxc" if vm_type == "lxc" else "vm"


def _guest_node_id(pnid: int, vm_type: str, vmid: int) -> str:
    return f"inst{pnid}-{_ui_type(vm_type)}-{vmid}"


def _row_to_out(row, inst_names: dict[int, str]) -> DependencyOut:
    return DependencyOut(
        id=row["id"],
        source_node_id=row["source_node_id"],
        source_vmid=row["source_vmid"],
        source_node=row["source_node"],
        source_name=row["source_name"],
        target_node_id=row["target_node_id"],
        target_vmid=row["target_vmid"],
        target_node=row["target_node"],
        target_name=row["target_name"],
        dep_label=row["dep_label"],
        created_at=row["created_at"],
        created_by=row["created_by"],
        stale=row["stale"],
        stale_at=row["stale_at"],
        source_installation=inst_names.get(row["source_node_id"]),
        target_installation=inst_names.get(row["target_node_id"]),
    )


# ── CRUD ──────────────────────────────────────────────────────────────────────

async def create_dependency(
    current_user: CurrentUser, body, actor_username: str
) -> DependencyOut:
    """Lege eine gerichtete Kante an (source hängt von target ab).

    Validierung:
      - Selbst-Abhängigkeit (Quelle == Ziel) → 422 (EC-1).
      - Beide VMs müssen für den Ersteller sichtbar sein → 422 (EC-5).
      - Duplikat (gleiche A→B) → 409 (EC-2).
    """
    if (body.source_node_id, body.source_vmid) == (body.target_node_id, body.target_vmid):
        raise HTTPException(status_code=422, detail="self_dependency_not_allowed")

    index = await _visible_index(current_user)
    src = index.get((body.source_node_id, body.source_vmid))
    tgt = index.get((body.target_node_id, body.target_vmid))
    if src is None:
        raise HTTPException(status_code=422, detail="source_vm_not_visible")
    if tgt is None:
        raise HTTPException(status_code=422, detail="target_vm_not_visible")

    label = (body.dep_label or "").strip() or None
    now = _now()

    async with get_db() as db:
        dup = await db.execute(
            text(
                "SELECT id FROM vm_dependencies "
                "WHERE source_node_id = :sn AND source_vmid = :sv "
                "  AND target_node_id = :tn AND target_vmid = :tv"
            ),
            {"sn": body.source_node_id, "sv": body.source_vmid,
             "tn": body.target_node_id, "tv": body.target_vmid},
        )
        if dup.mappings().fetchone() is not None:
            raise HTTPException(status_code=409, detail="dependency_exists")

        await db.execute(
            text(
                "INSERT INTO vm_dependencies "
                "(source_node_id, source_vmid, source_node, source_name, "
                " target_node_id, target_vmid, target_node, target_name, "
                " dep_label, created_at, created_by, stale) "
                "VALUES (:sn, :sv, :spn, :snm, :tn, :tv, :tpn, :tnm, "
                "        :lbl, :now, :uid, 0)"
            ),
            {
                "sn": body.source_node_id, "sv": body.source_vmid,
                "spn": src.node, "snm": src.name,
                "tn": body.target_node_id, "tv": body.target_vmid,
                "tpn": tgt.node, "tnm": tgt.name,
                "lbl": label, "now": now, "uid": current_user.user_id,
            },
        )
        # id dialect-portabel über die UNIQUE-Kante auflösen.
        r = await db.execute(
            text(
                "SELECT * FROM vm_dependencies "
                "WHERE source_node_id = :sn AND source_vmid = :sv "
                "  AND target_node_id = :tn AND target_vmid = :tv"
            ),
            {"sn": body.source_node_id, "sv": body.source_vmid,
             "tn": body.target_node_id, "tv": body.target_vmid},
        )
        row = r.mappings().fetchone()
        await db.commit()

    await write_audit_log(
        event_type="vm_dependency_created",
        username=actor_username,
        auth_type=current_user.auth_type,
        detail=(
            f"source=({body.source_node_id},{body.source_vmid}) "
            f"target=({body.target_node_id},{body.target_vmid})"
        ),
    )
    inst_names = await _installation_names()
    return _row_to_out(row, inst_names)


async def get_for_vm(
    current_user: CurrentUser, portal_node_id: int, vmid: int
) -> VmDependenciesResponse:
    """Beide Richtungen für eine VM, RBAC-gefiltert auf sichtbar-beide Endpunkte."""
    index = await _visible_index(current_user)
    if (portal_node_id, vmid) not in index:
        # VM selbst nicht sichtbar → keine Offenlegung.
        return VmDependenciesResponse()

    visible_keys = set(index.keys())
    inst_names = await _installation_names()

    async with get_db() as db:
        r = await db.execute(
            text(
                "SELECT * FROM vm_dependencies "
                "WHERE (source_node_id = :nid AND source_vmid = :vmid) "
                "   OR (target_node_id = :nid AND target_vmid = :vmid) "
                "ORDER BY id"
            ),
            {"nid": portal_node_id, "vmid": vmid},
        )
        rows = r.mappings().fetchall()

    depends_on: list[DependencyOut] = []
    dependents: list[DependencyOut] = []
    for row in rows:
        other_src = (row["source_node_id"], row["source_vmid"])
        other_tgt = (row["target_node_id"], row["target_vmid"])
        out = _row_to_out(row, inst_names)
        if other_src == (portal_node_id, vmid):
            # diese VM ist die Quelle → sie hängt vom Ziel ab.
            # Ziel muss sichtbar sein (oder verwaist → trotzdem zeigen).
            if other_tgt in visible_keys or out.stale:
                depends_on.append(out)
        else:
            # diese VM ist das Ziel → Quelle hängt von ihr ab.
            if other_src in visible_keys or out.stale:
                dependents.append(out)

    return VmDependenciesResponse(depends_on=depends_on, dependents=dependents)


async def update_label(dep_id: int, dep_label: Optional[str]) -> DependencyOut:
    label = (dep_label or "").strip() or None
    async with get_db() as db:
        result = await db.execute(
            text("UPDATE vm_dependencies SET dep_label = :lbl WHERE id = :id"),
            {"lbl": label, "id": dep_id},
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="dependency_not_found")
        r = await db.execute(
            text("SELECT * FROM vm_dependencies WHERE id = :id"),
            {"id": dep_id},
        )
        row = r.mappings().fetchone()
        await db.commit()
    inst_names = await _installation_names()
    return _row_to_out(row, inst_names)


async def delete_dependency(dep_id: int, actor_username: str) -> None:
    async with get_db() as db:
        result = await db.execute(
            text("DELETE FROM vm_dependencies WHERE id = :id"),
            {"id": dep_id},
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="dependency_not_found")
        await db.commit()
    await write_audit_log(
        event_type="vm_dependency_deleted",
        username=actor_username,
        detail=f"id={dep_id}",
    )


# ── Orphans ───────────────────────────────────────────────────────────────────

async def list_orphans() -> list[DependencyOut]:
    inst_names = await _installation_names()
    async with get_db() as db:
        r = await db.execute(
            text("SELECT * FROM vm_dependencies WHERE stale = 1 ORDER BY stale_at DESC, id DESC")
        )
        rows = r.mappings().fetchall()
    return [_row_to_out(row, inst_names) for row in rows]


async def delete_orphans(ids: Optional[list[int]], actor_username: str) -> int:
    """Lösche verwaiste Kanten (alle stale, optional auf ids beschränkt)."""
    async with get_db() as db:
        if ids:
            placeholders = ",".join(f":id{i}" for i in range(len(ids)))
            params = {f"id{i}": v for i, v in enumerate(ids)}
            result = await db.execute(
                text(f"DELETE FROM vm_dependencies WHERE stale = 1 AND id IN ({placeholders})"),
                params,
            )
        else:
            result = await db.execute(
                text("DELETE FROM vm_dependencies WHERE stale = 1")
            )
        count = result.rowcount
        await db.commit()
    if count > 0:
        await write_audit_log(
            event_type="vm_dependency_orphans_purged",
            username=actor_username,
            detail=f"count={count}",
        )
    return count


# ── Impact-Lookup (für den vms.py-Hook; beratend, nicht permission-gated) ──────

async def get_dependents(portal_node_id: int, vmid: int) -> list[dict]:
    """Direkte Abhängige einer VM (Quellen der Kanten, die auf sie zeigen).

    Verwaiste Kanten werden ausgelassen (deren Quelle existiert nicht mehr →
    sonst Warn-Rauschen). Ein JOIN auf nodes liefert den Installations-Namen.
    """
    async with get_db() as db:
        r = await db.execute(
            text(
                "SELECT d.source_vmid AS vmid, d.source_name AS name, "
                "       d.source_node AS node, d.dep_label AS dep_label, "
                "       n.name AS installation "
                "FROM vm_dependencies d "
                "LEFT JOIN nodes n ON n.id = d.source_node_id "
                "WHERE d.target_node_id = :nid AND d.target_vmid = :vmid "
                "  AND d.stale = 0 "
                "ORDER BY d.source_vmid"
            ),
            {"nid": portal_node_id, "vmid": vmid},
        )
        rows = r.mappings().fetchall()
    return [
        {
            "vmid": row["vmid"],
            "name": row["name"],
            "node": row["node"],
            "installation": row["installation"],
            "dep_label": row["dep_label"],
        }
        for row in rows
    ]


# ── Topologie-Graph (lazy, RBAC-gefiltert) ────────────────────────────────────

async def build_dependency_topology(
    current_user: CurrentUser,
) -> DependencyTopologyResponse:
    """Gerichteter Abhängigkeits-Graph, nur zwischen für den Nutzer sichtbaren VMs.

    Eine Kante wird nur emittiert, wenn BEIDE Endpunkte im sichtbaren Set liegen
    (serverseitig, AC-VIEW-3). Verwaiste Kanten zwischen sichtbaren VMs bleiben
    sichtbar (als stale markiert).
    """
    index = await _visible_index(current_user)
    inst_names = await _installation_names()

    guests = [
        DepGuest(
            id=_guest_node_id(pnid, vm.type, vmid),
            vmid=vm.vmid,
            node=vm.node,
            type=_ui_type(vm.type),
            label=vm.name or str(vm.vmid),
            status=vm.status,
            installation=inst_names.get(pnid) or vm.portal_node_name,
            portal_node_id=pnid,
        )
        for (pnid, vmid), vm in index.items()
    ]

    async with get_db() as db:
        r = await db.execute(text("SELECT * FROM vm_dependencies ORDER BY id"))
        rows = r.mappings().fetchall()

    edges: list[DepEdge] = []
    for row in rows:
        src_key = (row["source_node_id"], row["source_vmid"])
        tgt_key = (row["target_node_id"], row["target_vmid"])
        src = index.get(src_key)
        tgt = index.get(tgt_key)
        if src is None or tgt is None:
            continue  # mind. ein Endpunkt nicht sichtbar/verschwunden → nicht emittieren
        edges.append(
            DepEdge(
                id=row["id"],
                source_id=_guest_node_id(src_key[0], src.type, src.vmid),
                target_id=_guest_node_id(tgt_key[0], tgt.type, tgt.vmid),
                dep_label=row["dep_label"],
                stale=bool(row["stale"]),
            )
        )

    return DependencyTopologyResponse(guests=guests, edges=edges)
