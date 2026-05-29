# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-74: Lifecycle cleanup hooks for Config-Snapshots.

Hook 1 – on_vm_lxc_deleted:
  Mark all active snapshots for a (portal_node_id, proxmox_node, vmid, kind)
  as orphaned. Preserves history so Plus can restore if VM re-appears.

Hook 2 – on_user_deleted_config_snapshots:
  NULL-set created_by_user_id on snapshots belonging to a deleted user.
  Hard-delete is NOT done; the snapshot data itself belongs to the VM, not the user.

Hook 3 – on_cluster_refresh_vanished_resources_config_snapshots:
  Called by the cluster-cache service after a FULLY successful multi-node refresh.
  VMs that are no longer visible are orphaned here.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text

from backend.db.database import get_db
from backend.services.audit_service import write_audit_log


async def on_vm_lxc_deleted(
    portal_node_id: int,
    proxmox_node: str,
    vmid: int,
    kind: str,
    vm_name: Optional[str],
    username: str,
) -> int:
    """Mark snapshots for a deleted VM as orphaned. Returns number of rows updated."""
    now = datetime.now(timezone.utc).isoformat()
    async with get_db() as db:
        result = await db.execute(
            text(
                "UPDATE vm_config_snapshots "
                "SET is_orphan = 1, orphaned_at = :now, vm_name_at_delete = :vn "
                "WHERE portal_node_id = :nid "
                "  AND proxmox_node = :pn "
                "  AND vmid = :vmid "
                "  AND kind = :kind "
                "  AND is_orphan = 0"
            ),
            {
                "now": now,
                "vn": vm_name,
                "nid": portal_node_id,
                "pn": proxmox_node,
                "vmid": vmid,
                "kind": kind,
            },
        )
        count = result.rowcount
        await db.commit()

    if count > 0:
        await write_audit_log(
            "config_snapshot_orphaned",
            username=username,
            detail=f"vmid={vmid} kind={kind} node={proxmox_node} count={count}",
        )
    return count


async def on_user_deleted_config_snapshots(user_id: int) -> None:
    """NULL-set created_by_user_id for snapshots created by a deleted user."""
    async with get_db() as db:
        await db.execute(
            text(
                "UPDATE vm_config_snapshots "
                "SET created_by_user_id = NULL "
                "WHERE created_by_user_id = :uid"
            ),
            {"uid": user_id},
        )
        await db.commit()


async def on_cluster_refresh_vanished_resources_config_snapshots(
    still_visible_vmids: set[tuple[int, str, str]],  # (vmid, proxmox_node, kind)
    portal_node_id: int,
) -> None:
    """Orphan snapshots for VMs that are no longer visible after a successful refresh.

    ``still_visible_vmids`` is a set of (vmid, proxmox_node, kind) tuples for
    all VMs that were returned by the latest cluster refresh.

    Only called when the refresh was FULLY successful (not on partial failures).
    """
    now = datetime.now(timezone.utc).isoformat()

    async with get_db() as db:
        result = await db.execute(
            text(
                "SELECT DISTINCT vmid, proxmox_node, kind "
                "FROM vm_config_snapshots "
                "WHERE portal_node_id = :nid AND is_orphan = 0"
            ),
            {"nid": portal_node_id},
        )
        rows = result.fetchall()

    to_orphan = [
        r for r in rows
        if (r["vmid"], r["proxmox_node"], r["kind"]) not in still_visible_vmids
    ]

    if not to_orphan:
        return

    async with get_db() as db:
        for r in to_orphan:
            await db.execute(
                text(
                    "UPDATE vm_config_snapshots "
                    "SET is_orphan = 1, orphaned_at = :now "
                    "WHERE portal_node_id = :nid "
                    "  AND proxmox_node = :pn "
                    "  AND vmid = :vmid "
                    "  AND kind = :kind "
                    "  AND is_orphan = 0"
                ),
                {
                    "now": now,
                    "nid": portal_node_id,
                    "pn": r["proxmox_node"],
                    "vmid": r["vmid"],
                    "kind": r["kind"],
                },
            )
        await db.commit()
