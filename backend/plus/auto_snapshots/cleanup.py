# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-77 – Lifecycle-Cleanup-Hooks (Sektion N).

Werden via PROJ-60-Mediator-Pattern an Bestandsstellen verdrahtet.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import text

from backend.db.database import get_db
from backend.services.audit_service import write_audit_log

logger = logging.getLogger(__name__)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── User-Delete ────────────────────────────────────────────────────────────


async def on_user_deleted(user_id: int, actor_username: str) -> int:
    """Pausiert alle Auto-Snapshot-Jobs eines gelöschten Users (paused_ownerless).

    KEIN sofortiges Löschen – Admin kann Job adoptieren oder löschen.
    Returns Anzahl pausierter Jobs.
    """
    try:
        async with get_db() as db:
            result = await db.execute(
                text("SELECT username FROM local_users WHERE id = :uid"),
                {"uid": user_id},
            )
            row = result.fetchone()
            username = row[0] if row else None

        if not username:
            return 0

        async with get_db() as db:
            result = await db.execute(
                text(
                    "UPDATE scheduled_jobs SET active = 0, "
                    "last_run_status = 'paused_ownerless', "
                    "next_run_at = NULL, updated_at = :now "
                    "WHERE created_by = :u "
                    "  AND job_type IN ('auto_config_snapshot','auto_vm_snapshot')"
                ),
                {"u": username, "now": _iso_now()},
            )
            await db.commit()
            count = result.rowcount or 0

        if count:
            await write_audit_log(
                "auto_snapshot_job_paused_ownerless",
                username=actor_username,
                detail=json.dumps({
                    "reason": "user_deleted",
                    "deleted_username": username,
                    "count": count,
                }),
            )
            logger.info("PROJ-77: %d Auto-Snapshot-Jobs pausiert (User %s gelöscht)", count, username)
        return count
    except Exception as exc:
        logger.warning("PROJ-77 on_user_deleted: %s", exc)
        return 0


# ─── VM/LXC-Delete ──────────────────────────────────────────────────────────


async def on_vm_lxc_deleted(
    portal_node_id: int,
    vmid: int,
    kind: str,
    actor_username: str,
) -> int:
    """Markiert native Snapshots als rotated/vm_deleted (Proxmox hat sie ohnehin gelöscht).

    Config-Snapshots werden bereits durch PROJ-74-Hook orphan-markiert.
    Returns Anzahl betroffener Native-Snap-Reihen.
    """
    try:
        async with get_db() as db:
            result = await db.execute(
                text(
                    "UPDATE vm_native_snapshots "
                    "SET status='rotated', rotated_reason='vm_deleted', rotated_at=:now "
                    "WHERE portal_node_id = :nid AND vmid = :vid AND kind = :k "
                    "  AND status = 'active'"
                ),
                {"now": _iso_now(), "nid": portal_node_id, "vid": vmid, "k": kind},
            )
            await db.commit()
            count = result.rowcount or 0
        if count:
            await write_audit_log(
                "auto_vm_snapshot_rotated",
                username=actor_username,
                detail=json.dumps({
                    "reason": "vm_deleted",
                    "portal_node_id": portal_node_id, "vmid": vmid, "kind": kind,
                    "count": count,
                }),
            )
        return count
    except Exception as exc:
        logger.warning("PROJ-77 on_vm_lxc_deleted: %s", exc)
        return 0


# ─── Node-Delete ────────────────────────────────────────────────────────────


async def on_node_deleted(node_id, actor_username: str) -> int:
    """Deaktiviert alle Auto-Snapshot-Jobs, die einen gelöschten Portal-Node referenzieren.

    Sucht über config-LIKE nach ``portal_node_id`` in target_spec (auch in singles/portal_node_ids).
    Returns Anzahl deaktivierter Jobs.
    """
    try:
        async with get_db() as db:
            result = await db.execute(
                text(
                    "SELECT id, config FROM scheduled_jobs "
                    "WHERE parent_job_id IS NULL "
                    "  AND job_type IN ('auto_config_snapshot','auto_vm_snapshot')"
                )
            )
            candidates = [(r[0], r[1]) for r in result.all()]

        to_deactivate: list[str] = []
        node_id_str = str(node_id)
        for jid, cfg_str in candidates:
            try:
                cfg = json.loads(cfg_str or "{}")
            except Exception:
                continue
            target = cfg.get("target_spec", {}) or {}
            singles = target.get("singles") or []
            node_ids = target.get("portal_node_ids") or []
            hit = False
            if str(node_id_str) in (str(n) for n in node_ids):
                hit = True
            elif any(str(s.get("portal_node_id")) == node_id_str for s in singles if isinstance(s, dict)):
                hit = True
            if hit:
                to_deactivate.append(jid)

        if not to_deactivate:
            return 0

        async with get_db() as db:
            for jid in to_deactivate:
                await db.execute(
                    text(
                        "UPDATE scheduled_jobs SET active = 0, next_run_at = NULL, "
                        "updated_at = :now WHERE id = :id"
                    ),
                    {"now": _iso_now(), "id": jid},
                )
            await db.commit()

        await write_audit_log(
            "auto_snapshot_job_paused_ownerless",
            username=actor_username,
            detail=json.dumps({
                "reason": "node_deleted",
                "node_id": node_id_str,
                "count": len(to_deactivate),
            }),
        )
        logger.info("PROJ-77: %d Auto-Snapshot-Jobs deaktiviert (Node %s gelöscht)", len(to_deactivate), node_id_str)
        return len(to_deactivate)
    except Exception as exc:
        logger.warning("PROJ-77 on_node_deleted: %s", exc)
        return 0
