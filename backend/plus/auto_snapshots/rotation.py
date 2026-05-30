# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-77 – GFS-Tier-Berechnung + Retention/Rotation.

Sektion I (α-Entscheidung): GFS-Tiers werden zur Insert-Zeit berechnet
und als JSON-Array in ``vm_native_snapshots.gfs_tiers`` persistiert.

Sektion J: Retention läuft NACH allen Creates pro Run, damit ein gerade
erstellter Snapshot nicht vor seiner Tier-Promotion gelöscht wird.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text

from backend.db.database import get_db

logger = logging.getLogger(__name__)


# ─── GFS-Tier-Logik ─────────────────────────────────────────────────────────


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _parse_iso(s: str) -> datetime:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return _utc_now()


def _bucket_keys(dt: datetime) -> tuple[str, str]:
    """Liefert ``(weekly_bucket, monthly_bucket)`` für ``dt`` (UTC)."""
    return dt.strftime("%G-W%V"), dt.strftime("%Y-%m")


async def compute_gfs_tiers(
    job_id: str,
    portal_node_id: int,
    vmid: int,
    kind: str,
    gfs_enabled: bool,
    now: Optional[datetime] = None,
) -> list[str]:
    """Berechnet die GFS-Tiers eines neuen Snapshots gemäß Sektion I.

    Liefert mindestens ``['daily']``. Falls ``gfs_enabled`` und noch kein lebender
    Snapshot dieses Buckets als 'weekly'/'monthly' markiert ist, werden die
    entsprechenden Tiers ergänzt.
    """
    tiers = ["daily"]
    if not gfs_enabled:
        return tiers

    now = now or _utc_now()
    bucket_weekly, bucket_monthly = _bucket_keys(now)

    async with get_db() as db:
        result = await db.execute(
            text(
                "SELECT created_at, gfs_tiers FROM vm_native_snapshots "
                "WHERE scheduled_job_id = :jid AND portal_node_id = :nid "
                "  AND vmid = :vid AND kind = :k AND status = 'active' "
                "ORDER BY created_at DESC"
            ),
            {"jid": job_id, "nid": portal_node_id, "vid": vmid, "k": kind},
        )
        rows = result.fetchall()

    week_taken = False
    month_taken = False
    for created_at, tiers_json in rows:
        try:
            existing_tiers = json.loads(tiers_json or "[]")
        except Exception:
            existing_tiers = []
        created_dt = _parse_iso(created_at)
        cw, cm = _bucket_keys(created_dt)
        if "weekly" in existing_tiers and cw == bucket_weekly:
            week_taken = True
        if "monthly" in existing_tiers and cm == bucket_monthly:
            month_taken = True
        if week_taken and month_taken:
            break

    if not week_taken:
        tiers.append("weekly")
    if not month_taken:
        tiers.append("monthly")
    return tiers


# ─── Insert-Helfer ──────────────────────────────────────────────────────────


async def insert_native_snapshot(
    snapshot_id: str,
    scheduled_job_id: str,
    portal_node_id: int,
    proxmox_node: str,
    vmid: int,
    kind: str,
    snapname: str,
    include_ram: bool,
    gfs_tiers: list[str],
) -> None:
    """Schreibt einen neuen Eintrag in vm_native_snapshots (Status active)."""
    now = _iso(_utc_now())
    async with get_db() as db:
        await db.execute(
            text(
                "INSERT INTO vm_native_snapshots "
                "(id, scheduled_job_id, portal_node_id, proxmox_node, vmid, kind, "
                " snapname, created_at, include_ram, gfs_tiers, status) "
                "VALUES (:id, :jid, :nid, :pn, :vid, :k, :sn, :ca, :ir, :gt, 'active')"
            ),
            {
                "id": snapshot_id,
                "jid": scheduled_job_id,
                "nid": portal_node_id,
                "pn": proxmox_node,
                "vid": vmid,
                "k": kind,
                "sn": snapname,
                "ca": now,
                "ir": 1 if include_ram else 0,
                "gt": json.dumps(gfs_tiers),
            },
        )
        await db.commit()


async def list_active_snapshots(
    scheduled_job_id: str,
    portal_node_id: int,
    vmid: int,
    kind: str,
) -> list[dict]:
    """Aktive Snapshots eines Jobs für ein bestimmtes Target, neueste zuerst."""
    async with get_db() as db:
        result = await db.execute(
            text(
                "SELECT id, snapname, created_at, gfs_tiers FROM vm_native_snapshots "
                "WHERE scheduled_job_id = :jid AND portal_node_id = :nid "
                "  AND vmid = :vid AND kind = :k AND status = 'active' "
                "ORDER BY created_at DESC"
            ),
            {"jid": scheduled_job_id, "nid": portal_node_id, "vid": vmid, "k": kind},
        )
        rows = result.fetchall()
    out: list[dict] = []
    for sid, sn, ca, gt in rows:
        try:
            tiers = json.loads(gt or "[]")
        except Exception:
            tiers = []
        out.append({"id": sid, "snapname": sn, "created_at": ca, "gfs_tiers": tiers})
    return out


# ─── Rotation ───────────────────────────────────────────────────────────────


def determine_keep_set(
    snapshots: list[dict],
    keep_last: int,
    keep_daily: int,
    keep_weekly: int,
    keep_monthly: int,
) -> set[str]:
    """Berechnet die zu behaltenden Snapshot-IDs.

    snapshots: neueste zuerst sortierte Liste von ``{id, gfs_tiers, …}``-Dicts.
    Logik (Sektion J):
        1) keep_last: Floor – immer mind. die jüngsten N
        2) GFS-Tiers: jeweils keep_n je Pool
        Union beider → ``keep_set``
    """
    keep: set[str] = set()
    # keep_last floor
    for s in snapshots[: max(0, keep_last)]:
        keep.add(s["id"])

    # Pools je Tier (neueste zuerst dank Sortierung)
    daily_pool = [s for s in snapshots if "daily" in (s.get("gfs_tiers") or [])]
    weekly_pool = [s for s in snapshots if "weekly" in (s.get("gfs_tiers") or [])]
    monthly_pool = [s for s in snapshots if "monthly" in (s.get("gfs_tiers") or [])]

    if keep_daily > 0:
        for s in daily_pool[:keep_daily]:
            keep.add(s["id"])
    if keep_weekly > 0:
        for s in weekly_pool[:keep_weekly]:
            keep.add(s["id"])
    if keep_monthly > 0:
        for s in monthly_pool[:keep_monthly]:
            keep.add(s["id"])

    return keep


async def mark_snapshots_rotated(
    snapshot_ids: list[str],
    reason: str,
) -> None:
    """Markiert eine Liste Snapshots als rotated mit Reason."""
    if not snapshot_ids:
        return
    now = _iso(_utc_now())
    async with get_db() as db:
        placeholders = ",".join(f":id{i}" for i in range(len(snapshot_ids)))
        params: dict = {"now": now, "reason": reason}
        for i, sid in enumerate(snapshot_ids):
            params[f"id{i}"] = sid
        await db.execute(
            text(
                f"UPDATE vm_native_snapshots "
                f"SET status='rotated', rotated_reason=:reason, rotated_at=:now "
                f"WHERE id IN ({placeholders}) AND status='active'"
            ),
            params,
        )
        await db.commit()


# ─── Config-Snapshot-Rotation (PROJ-74-Tabelle) ────────────────────────────


async def list_active_config_snapshots(
    scheduled_job_id: str,
    portal_node_id: int,
    vmid: int,
    kind: str,
) -> list[dict]:
    """Aktive Auto-Config-Snapshots eines Jobs für ein Target, neueste zuerst."""
    async with get_db() as db:
        result = await db.execute(
            text(
                "SELECT id, created_at FROM vm_config_snapshots "
                "WHERE source = 'auto' AND created_by_scheduled_job_id = :jid "
                "  AND portal_node_id = :nid AND vmid = :vid AND kind = :k "
                "  AND is_orphan = 0 "
                "ORDER BY created_at DESC"
            ),
            {"jid": scheduled_job_id, "nid": portal_node_id, "vid": vmid, "k": kind},
        )
        rows = result.fetchall()
    return [{"id": sid, "created_at": ca, "gfs_tiers": []} for sid, ca in rows]


async def delete_config_snapshots(snapshot_ids: list[str]) -> int:
    if not snapshot_ids:
        return 0
    async with get_db() as db:
        placeholders = ",".join(f":id{i}" for i in range(len(snapshot_ids)))
        params: dict = {f"id{i}": sid for i, sid in enumerate(snapshot_ids)}
        result = await db.execute(
            text(f"DELETE FROM vm_config_snapshots WHERE id IN ({placeholders})"),
            params,
        )
        await db.commit()
        return result.rowcount or 0
