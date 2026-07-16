# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-42 Phase 2: Freigabe- & Orphan-Verhalten (Muster PROJ-96).

- Löschen einer VM über P3 → die zugeordnete Allocation wird FREIGEGEBEN (gelöscht).
  Der resumable Delete-Guard (``ipam_release_impact`` in vms.py) warnt vorher.
- VM außerhalb P3 verschwunden → ``confirmed`` wird ``orphaned`` markiert (nicht
  auto-freigeben; der Berechtigte räumt manuell auf). Taucht die VM wieder auf,
  wird ``orphaned`` → ``confirmed`` reaktiviert (keine Doppelvergabe).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text

from backend.db.database import get_db
from backend.services.audit_service import write_audit_log

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Delete über P3 → Freigabe ────────────────────────────────────────────────

async def release_impact(portal_node_id: int, vmid: int) -> list[dict]:
    """Allocations, die beim Löschen dieser VM freigegeben würden (für den Guard)."""
    async with get_db() as db:
        result = await db.execute(
            text(
                "SELECT id, ip, pool_id, status FROM ip_allocations "
                "WHERE portal_node_id = :pnid AND vmid = :vmid "
                "AND status IN ('confirmed', 'orphaned')"
            ),
            {"pnid": portal_node_id, "vmid": vmid},
        )
        rows = result.mappings().fetchall()
    return [dict(r) for r in rows]


async def on_vm_lxc_deleted(portal_node_id: int, vmid: int, username: str) -> int:
    """VM über P3 gelöscht → ihre Allocation(en) freigeben (löschen)."""
    async with get_db() as db:
        result = await db.execute(
            text(
                "DELETE FROM ip_allocations "
                "WHERE portal_node_id = :pnid AND vmid = :vmid "
                "AND status IN ('confirmed', 'orphaned')"
            ),
            {"pnid": portal_node_id, "vmid": vmid},
        )
        count = result.rowcount
        await db.commit()
    if count > 0:
        await write_audit_log(
            event_type="ipam_allocation_released",
            username=username,
            detail=f"vmid={vmid} node_id={portal_node_id} count={count}",
        )
    return count


# ── Vanished-Reconciliation (orphaned ↔ confirmed) ───────────────────────────

async def on_cluster_refresh_vanished_resources(
    still_visible_vmids: set[int], portal_node_id: int
) -> int:
    """Bidirektionale Reconciliation nach einem voll-erfolgreichen Refresh.

    - ``confirmed`` mit nicht mehr sichtbarer VMID → ``orphaned`` (nicht löschen).
    - ``orphaned`` mit wieder sichtbarer VMID → ``confirmed`` reaktivieren.
    Nur bei voll-erfolgreichem Refresh aufgerufen (eine offline-Installation
    verwaist nichts fälschlich, EC analog PROJ-96).
    """
    now = _now()
    async with get_db() as db:
        rows = (await db.execute(
            text(
                "SELECT id, vmid, status FROM ip_allocations "
                "WHERE portal_node_id = :pnid AND vmid IS NOT NULL "
                "AND status IN ('confirmed', 'orphaned')"
            ),
            {"pnid": portal_node_id},
        )).mappings().fetchall()

        to_orphan: list[int] = []
        to_reactivate: list[int] = []
        for r in rows:
            visible = r["vmid"] in still_visible_vmids
            if r["status"] == "confirmed" and not visible:
                to_orphan.append(r["id"])
            elif r["status"] == "orphaned" and visible:
                to_reactivate.append(r["id"])

        for ids, new_status in ((to_orphan, "orphaned"), (to_reactivate, "confirmed")):
            if not ids:
                continue
            placeholders = ",".join(f":id{i}" for i in range(len(ids)))
            params = {f"id{i}": v for i, v in enumerate(ids)}
            params["st"] = new_status
            await db.execute(
                text(f"UPDATE ip_allocations SET status = :st WHERE id IN ({placeholders})"),
                params,
            )
        if to_orphan or to_reactivate:
            await db.commit()

    changed = len(to_orphan) + len(to_reactivate)
    if changed:
        await write_audit_log(
            event_type="ipam_allocation_reconciled",
            username="system",
            detail=(f"node_id={portal_node_id} orphaned={len(to_orphan)} "
                    f"reactivated={len(to_reactivate)}"),
        )
    return changed


# ── Orphan-Verwaltung ────────────────────────────────────────────────────────

async def list_orphans() -> list[dict]:
    async with get_db() as db:
        rows = (await db.execute(
            text("SELECT * FROM ip_allocations WHERE status = 'orphaned' ORDER BY pool_id, ip")
        )).mappings().fetchall()
    return [dict(r) for r in rows]


async def release_orphans(ids: list[int] | None, username: str) -> int:
    """Verwaiste Allocations freigeben – ``ids`` leer/None = alle verwaisten."""
    async with get_db() as db:
        if ids:
            placeholders = ",".join(f":id{i}" for i in range(len(ids)))
            params = {f"id{i}": v for i, v in enumerate(ids)}
            result = await db.execute(
                text(
                    f"DELETE FROM ip_allocations "
                    f"WHERE status = 'orphaned' AND id IN ({placeholders})"
                ),
                params,
            )
        else:
            result = await db.execute(
                text("DELETE FROM ip_allocations WHERE status = 'orphaned'")
            )
        count = result.rowcount
        await db.commit()
    if count > 0:
        await write_audit_log(
            event_type="ipam_orphans_released",
            username=username,
            detail=f"count={count}",
        )
    return count


# ── Pool-Löschen-Block ───────────────────────────────────────────────────────

async def assert_pool_deletable(pool_id: int) -> None:
    """Harter Block: ein Pool mit aktiven Allocations darf nicht gelöscht werden."""
    from fastapi import HTTPException, status
    async with get_db() as db:
        row = (await db.execute(
            text(
                "SELECT COUNT(*) AS n FROM ip_allocations "
                "WHERE pool_id = :pid AND status IN ('pending', 'confirmed', 'orphaned')"
            ),
            {"pid": pool_id},
        )).mappings().fetchone()
    n = row["n"] if row else 0
    if n:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "ipam_pool_has_allocations", "pool_id": pool_id, "count": n},
        )
