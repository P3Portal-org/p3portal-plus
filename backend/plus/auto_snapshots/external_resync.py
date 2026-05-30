# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-77 – External-Delete-Resync + Prefix-Kollision (Sektion L).

Wird ZU BEGINN jedes Job-Runs einmal pro betroffenem Portal-Node aufgerufen:
- Snapshots die in DB ``active`` stehen aber in Proxmox fehlen → ``deleted_externally``.
- Snapshots die in Proxmox mit ``p3auto_``-Prefix existieren, aber **keinen** DB-Eintrag
  haben → einmaliger Warn-Audit (deduped 7d via audit_log-Lookback).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import text

from backend.db.database import get_db
from backend.services.audit_service import write_audit_log

from .models import SNAP_NAME_PREFIX

logger = logging.getLogger(__name__)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def sync_external_state(
    portal_node_id: int,
    proxmox_node: str,
    vmid: int,
    kind: str,
    proxmox_snap_names: set[str],
) -> tuple[int, list[str]]:
    """Synchronisiert DB ↔ Proxmox-Snapshot-Liste für eine VM.

    Args:
        proxmox_snap_names: alle in Proxmox vorhandenen Snapnames für diese VM.

    Returns:
        ``(vanished_count, external_prefixed)``
        wobei ``external_prefixed`` = Liste von ``p3auto_*``-Names ohne DB-Eintrag.
    """
    async with get_db() as db:
        result = await db.execute(
            text(
                "SELECT id, snapname FROM vm_native_snapshots "
                "WHERE portal_node_id = :nid AND proxmox_node = :pn "
                "  AND vmid = :vid AND kind = :k AND status = 'active'"
            ),
            {"nid": portal_node_id, "pn": proxmox_node, "vid": vmid, "k": kind},
        )
        db_rows = result.fetchall()

    db_snapnames = {r[1] for r in db_rows}
    vanished = db_snapnames - proxmox_snap_names

    if vanished:
        now = _iso_now()
        async with get_db() as db:
            placeholders = ",".join(f":sn{i}" for i in range(len(vanished)))
            params: dict = {"now": now}
            for i, sn in enumerate(vanished):
                params[f"sn{i}"] = sn
            await db.execute(
                text(
                    f"UPDATE vm_native_snapshots "
                    f"SET status='deleted_externally', rotated_at=:now "
                    f"WHERE portal_node_id = :nid AND proxmox_node = :pn "
                    f"  AND vmid = :vid AND kind = :k "
                    f"  AND snapname IN ({placeholders}) AND status = 'active'"
                ),
                {**params, "nid": portal_node_id, "pn": proxmox_node, "vid": vmid, "k": kind},
            )
            await db.commit()
        for snapname in vanished:
            await write_audit_log(
                "auto_vm_snapshot_external_deleted",
                username="system",
                detail=json.dumps({
                    "portal_node_id": portal_node_id,
                    "proxmox_node": proxmox_node,
                    "vmid": vmid,
                    "kind": kind,
                    "snapname": snapname,
                }),
            )

    external_prefixed = [
        sn for sn in proxmox_snap_names
        if sn.startswith(SNAP_NAME_PREFIX) and sn not in db_snapnames
    ]
    return len(vanished), external_prefixed


async def _has_recent_collision_audit(snapname: str, lookback_days: int = 7) -> bool:
    """Prüft audit_log-Lookback ob bereits eine Kollision für diesen Snapname auditiert wurde."""
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
    async with get_db() as db:
        try:
            result = await db.execute(
                text(
                    "SELECT 1 FROM audit_log "
                    "WHERE event_type = 'auto_vm_snapshot_external_prefix_collision' "
                    "  AND detail LIKE :pattern "
                    "  AND timestamp > :cutoff "
                    "LIMIT 1"
                ),
                {"pattern": f"%{snapname}%", "cutoff": cutoff},
            )
            return result.fetchone() is not None
        except Exception:
            return False


async def report_prefix_collisions(
    portal_node_id: int,
    proxmox_node: str,
    vmid: int,
    kind: str,
    external_snapnames: list[str],
) -> int:
    """Schreibt 1× Audit pro Snapname (deduped via 7d-Lookback)."""
    audited = 0
    for snapname in external_snapnames:
        if await _has_recent_collision_audit(snapname):
            continue
        await write_audit_log(
            "auto_vm_snapshot_external_prefix_collision",
            username="system",
            detail=json.dumps({
                "portal_node_id": portal_node_id,
                "proxmox_node": proxmox_node,
                "vmid": vmid,
                "kind": kind,
                "snapname": snapname,
            }),
        )
        audited += 1
    return audited
