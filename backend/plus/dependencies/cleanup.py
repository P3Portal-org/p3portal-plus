# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-96: Lifecycle-Hooks für VM-Abhängigkeiten – „verwaist" markieren, nie löschen.

Hook 1 – on_vm_lxc_deleted:
  Wird eine VM über P3 gelöscht, werden ihre Kanten (als Quelle UND Ziel) als
  stale markiert (AC-ORPHAN-2). Kein Hard-Delete – der Berechtigte räumt manuell auf.

Hook 2 – on_cluster_refresh_vanished_resources:
  Wird vom Cluster-Cache NACH einem voll-erfolgreichen Multi-Node-Refresh gerufen.
  Kanten, deren Endpunkt auf diese Installation zeigt aber dessen VMID nicht mehr
  sichtbar ist, werden stale markiert (AC-ORPHAN-1, EC-6 – nur bei Erfolg).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import text

from backend.db.database import get_db
from backend.services.audit_service import write_audit_log


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def on_vm_lxc_deleted(portal_node_id: int, vmid: int, username: str) -> int:
    """Markiere alle Kanten der gelöschten VM (Quelle ODER Ziel) als stale."""
    now = _now()
    async with get_db() as db:
        result = await db.execute(
            text(
                "UPDATE vm_dependencies SET stale = 1, stale_at = :now "
                "WHERE stale = 0 AND ("
                "  (source_node_id = :nid AND source_vmid = :vmid) "
                "  OR (target_node_id = :nid AND target_vmid = :vmid))"
            ),
            {"now": now, "nid": portal_node_id, "vmid": vmid},
        )
        count = result.rowcount
        await db.commit()
    if count > 0:
        await write_audit_log(
            event_type="vm_dependency_orphaned",
            username=username,
            detail=f"vmid={vmid} node_id={portal_node_id} count={count}",
        )
    return count


async def on_cluster_refresh_vanished_resources(
    still_visible_vmids: set[int],
    portal_node_id: int,
) -> int:
    """Markiere Kanten verschwundener VMs auf dieser Installation als stale.

    ``still_visible_vmids`` = Menge aller VMIDs, die der letzte (erfolgreiche)
    Refresh dieser Installation lieferte. Endpunkte auf dieser Installation mit
    einer nicht mehr enthaltenen VMID werden verwaist.

    Nur bei voll-erfolgreichem Refresh aufgerufen (EC-6) – eine offline-/teilweise
    fehlgeschlagene Installation verwaist nichts fälschlich.
    """
    now = _now()
    async with get_db() as db:
        # Aktive Kanten, deren Quelle ODER Ziel auf dieser Installation liegt.
        r = await db.execute(
            text(
                "SELECT id, source_node_id, source_vmid, target_node_id, target_vmid "
                "FROM vm_dependencies "
                "WHERE stale = 0 AND (source_node_id = :nid OR target_node_id = :nid)"
            ),
            {"nid": portal_node_id},
        )
        rows = r.mappings().fetchall()

        to_orphan: list[int] = []
        for row in rows:
            src_gone = (
                row["source_node_id"] == portal_node_id
                and row["source_vmid"] not in still_visible_vmids
            )
            tgt_gone = (
                row["target_node_id"] == portal_node_id
                and row["target_vmid"] not in still_visible_vmids
            )
            if src_gone or tgt_gone:
                to_orphan.append(row["id"])

        if not to_orphan:
            return 0

        placeholders = ",".join(f":id{i}" for i in range(len(to_orphan)))
        params = {f"id{i}": v for i, v in enumerate(to_orphan)}
        params["now"] = now
        await db.execute(
            text(
                f"UPDATE vm_dependencies SET stale = 1, stale_at = :now "
                f"WHERE id IN ({placeholders})"
            ),
            params,
        )
        await db.commit()

    await write_audit_log(
        event_type="vm_dependency_orphaned",
        username="system",
        detail=f"node_id={portal_node_id} vanished count={len(to_orphan)}",
    )
    return len(to_orphan)
