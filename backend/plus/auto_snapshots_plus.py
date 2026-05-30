# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-77 – Auto-Snapshots-Plus-Mixin (`AutoSnapshotsPlusBehavior`).

Wird via ``backend/plus/__init__.py`` in ``PlusActiveBehavior`` komponiert.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class AutoSnapshotsPlusBehavior:
    """Plus-Mixin: Auto-Snapshots (PROJ-77)."""

    # ── Action-Handler-Beitrag ───────────────────────────────────────────────
    # WICHTIG: PROJ-70 ScheduledJobsPlusBehavior liefert 4 Handler (ssh / playbook /
    # power_action / git_sync). Beide Mixins definieren get_scheduled_job_action_handlers,
    # daher wird in _PlusGateBehavior das Ergebnis aller MRO-Mixins gemerged
    # (siehe backend/plus/__init__.py).

    def get_scheduled_job_action_handlers(self) -> dict:
        try:
            from backend.plus.auto_snapshots.handlers import (
                handle_auto_config_snapshot,
                handle_auto_vm_snapshot,
            )
            return {
                "auto_config_snapshot": handle_auto_config_snapshot,
                "auto_vm_snapshot": handle_auto_vm_snapshot,
            }
        except Exception as exc:
            logger.warning("PROJ-77: get_scheduled_job_action_handlers fehlgeschlagen: %s", exc)
            return {}

    # ── Cleanup-Hooks ────────────────────────────────────────────────────────

    async def on_user_deleted_auto_snapshots(self, user_id: int, actor_username: str) -> int:
        try:
            from backend.plus.auto_snapshots.cleanup import on_user_deleted
            return await on_user_deleted(user_id, actor_username)
        except Exception as exc:
            logger.warning("PROJ-77 on_user_deleted_auto_snapshots: %s", exc)
            return 0

    async def on_vm_lxc_deleted_auto_snapshots(
        self, portal_node_id: int, vmid: int, kind: str, actor_username: str
    ) -> int:
        try:
            from backend.plus.auto_snapshots.cleanup import on_vm_lxc_deleted
            return await on_vm_lxc_deleted(portal_node_id, vmid, kind, actor_username)
        except Exception as exc:
            logger.warning("PROJ-77 on_vm_lxc_deleted_auto_snapshots: %s", exc)
            return 0

    async def on_node_deleted_auto_snapshots(self, node_id, actor_username: str) -> int:
        try:
            from backend.plus.auto_snapshots.cleanup import on_node_deleted
            return await on_node_deleted(node_id, actor_username)
        except Exception as exc:
            logger.warning("PROJ-77 on_node_deleted_auto_snapshots: %s", exc)
            return 0

    def get_auto_snapshot_approval_action_types(self) -> list[str]:
        return [
            "scheduled_job_create_auto_config_snapshot",
            "scheduled_job_create_auto_vm_snapshot",
        ]
