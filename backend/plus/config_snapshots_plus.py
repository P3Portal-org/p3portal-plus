# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-74: Plus-Mixin für Config-Snapshots.

Stellt can_use_config_snapshots() + alle Lifecycle-Hooks bereit.
"""
from __future__ import annotations

from typing import Optional


class ConfigSnapshotsPlusBehavior:
    """Plus-Mixin: aktiviert das Config-Snapshot-Feature."""

    def can_use_config_snapshots(self) -> bool:
        return True

    async def on_vm_lxc_deleted_config_snapshots(
        self,
        portal_node_id: int,
        proxmox_node: str,
        vmid: int,
        kind: str,
        vm_name: Optional[str],
        username: str,
    ) -> int:
        from backend.plus.config_snapshots.cleanup import on_vm_lxc_deleted
        return await on_vm_lxc_deleted(
            portal_node_id, proxmox_node, vmid, kind, vm_name, username
        )

    async def on_user_deleted_config_snapshots(self, user_id: int) -> None:
        from backend.plus.config_snapshots.cleanup import on_user_deleted_config_snapshots
        await on_user_deleted_config_snapshots(user_id)

    async def on_cluster_refresh_vanished_resources_config_snapshots(
        self,
        still_visible_vmids: set,
        portal_node_id: int,
    ) -> None:
        from backend.plus.config_snapshots.cleanup import (
            on_cluster_refresh_vanished_resources_config_snapshots,
        )
        await on_cluster_refresh_vanished_resources_config_snapshots(
            still_visible_vmids, portal_node_id
        )

    async def on_config_snapshot_deleted_cancel_approvals(
        self, snapshot_id: str
    ) -> int:
        """Cancel pending config_snapshot_restore approvals for this snapshot."""
        try:
            from backend.plus.approvals.service import cancel_approvals_by_target
            return await cancel_approvals_by_target(
                action_type="config_snapshot_restore",
                action_target=f"config_snapshot:{snapshot_id}",
            )
        except Exception:
            return 0
