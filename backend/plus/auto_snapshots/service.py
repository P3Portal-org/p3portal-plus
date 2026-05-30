# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-77 – Read-Helpers für die beiden EPs (router.py).

Die Schreib-/Run-Logik lebt in handlers.py – diese Modul nur für Lesepfade.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from sqlalchemy import text

from backend.db.database import get_db

from .schemas import (
    NativeSnapshotEntry, RunDetailEntry, RunDetailsResponse, RunSummary,
)

logger = logging.getLogger(__name__)


async def get_run_details(run_id: str) -> Optional[RunDetailsResponse]:
    """Lädt einen scheduled_job_runs-Eintrag und parsed Summary + Per-VM-Details."""
    async with get_db() as db:
        result = await db.execute(
            text(
                "SELECT id, job_id, output FROM scheduled_job_runs WHERE id = :id"
            ),
            {"id": run_id},
        )
        row = result.fetchone()
    if not row:
        return None

    run_id_db, job_id, output = row[0], row[1], row[2] or ""
    summary: RunSummary
    entries: list[RunDetailEntry] = []
    try:
        parsed = json.loads(output)
        summary = RunSummary.model_validate(parsed)
    except Exception:
        summary = RunSummary(status="failed")

    # Per-VM-Detail aus vm_native_snapshots + Config-Snapshots ableiten
    async with get_db() as db:
        nres = await db.execute(
            text(
                "SELECT portal_node_id, proxmox_node, vmid, kind, snapname, id, status "
                "FROM vm_native_snapshots WHERE scheduled_job_id = :jid "
                "ORDER BY created_at DESC LIMIT 200"
            ),
            {"jid": job_id},
        )
        for nid, pn, vid, kind, snapname, sid, status in nres.fetchall():
            status_str = "created" if status == "active" else ("rotated_only" if status == "rotated" else "failed")
            entries.append(RunDetailEntry(
                portal_node_id=nid, proxmox_node=pn, vmid=vid, kind=kind,
                status=status_str, snapname=snapname, snapshot_id=sid,
            ))

    return RunDetailsResponse(
        run_id=run_id_db, job_id=job_id, summary=summary, entries=entries,
    )


async def list_native_snapshots(
    portal_node_id: int,
    proxmox_node: str,
    vmid: int,
    kind: str,
) -> list[NativeSnapshotEntry]:
    async with get_db() as db:
        result = await db.execute(
            text(
                "SELECT id, scheduled_job_id, portal_node_id, proxmox_node, vmid, kind, "
                "       snapname, created_at, include_ram, gfs_tiers, status "
                "FROM vm_native_snapshots "
                "WHERE portal_node_id = :nid AND proxmox_node = :pn "
                "  AND vmid = :vid AND kind = :k "
                "ORDER BY created_at DESC"
            ),
            {"nid": portal_node_id, "pn": proxmox_node, "vid": vmid, "k": kind},
        )
        rows = result.fetchall()

    out: list[NativeSnapshotEntry] = []
    for r in rows:
        try:
            tiers = json.loads(r[9] or "[]")
        except Exception:
            tiers = []
        out.append(NativeSnapshotEntry(
            id=r[0], scheduled_job_id=r[1], portal_node_id=r[2], proxmox_node=r[3],
            vmid=r[4], kind=r[5], snapname=r[6], created_at=r[7],
            include_ram=bool(r[8]), gfs_tiers=tiers, status=r[10],
        ))
    return out


async def get_job_owner_username(job_id: str) -> str | None:
    """Liefert den ``created_by``-Username eines scheduled_jobs-Eintrags (für Owner-Check im EP)."""
    async with get_db() as db:
        result = await db.execute(
            text("SELECT created_by FROM scheduled_jobs WHERE id = :id"),
            {"id": job_id},
        )
        row = result.fetchone()
        return row[0] if row else None
