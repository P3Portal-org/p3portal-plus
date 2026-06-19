# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-96: Plus-Mixin für VM-Abhängigkeiten.

Stellt can_use_dependencies() + den Impact-Lookup + die Lifecycle-Hooks bereit.
"""
from __future__ import annotations


class DependenciesPlusBehavior:
    """Plus-Mixin: aktiviert das VM-Abhängigkeits-Feature."""

    def can_use_dependencies(self) -> bool:
        return True

    async def get_dependents_of_vm(
        self, portal_node_id: int, vmid: int
    ) -> list[dict]:
        from backend.plus.dependencies.service import get_dependents
        return await get_dependents(portal_node_id, vmid)

    async def on_vm_lxc_deleted_dependencies(
        self, portal_node_id: int, vmid: int, username: str
    ) -> int:
        from backend.plus.dependencies.cleanup import on_vm_lxc_deleted
        return await on_vm_lxc_deleted(portal_node_id, vmid, username)

    async def on_cluster_refresh_vanished_resources_dependencies(
        self, still_visible_vmids: set, portal_node_id: int
    ) -> int:
        from backend.plus.dependencies.cleanup import (
            on_cluster_refresh_vanished_resources,
        )
        return await on_cluster_refresh_vanished_resources(
            still_visible_vmids, portal_node_id
        )
