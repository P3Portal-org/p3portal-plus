# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-42 Phase 2: Mediator-Mixin für das interne Plus-IPAM.

Aktiviert die Plus-Capability und überschreibt die Core-No-op-Defaults aus
``CorePlusBehavior`` (plus_protocol.py). Jede Impl lazy-importiert den eigentlichen
Service erst im Methodenkörper (kein Top-Level-Plus-Import → Core-Build bricht nie).

Alle zustandsbehafteten Hooks respektieren den ``global_enabled``-Toggle intern:
ist IPAM global AUS, verhalten sie sich wie der Core-Default (Phase-1-best-effort
bleibt, aber keine Reservierung/Historie) – kein Upgrade-Bruch (Tech-Design P2.B).
"""
from __future__ import annotations


class IpamPlusBehavior:
    """Plus-Mixin: aktiviert das interne IPAM (Allocations, Lebenszyklus, Grants)."""

    def can_use_ipam_plus(self) -> bool:
        return True

    # ── Etappe B: Reservierung / belegte IPs ─────────────────────────────────

    async def ipam_reserved_ips(self, pool_id: int) -> set:
        from backend.plus.ipam.service import reserved_ips
        return await reserved_ips(pool_id)

    async def on_playbook_job_started_ipam(
        self, job_id: str, playbook: str, params: dict, username: str
    ) -> int:
        from backend.plus.ipam.deploy_hook import on_playbook_job_started
        return await on_playbook_job_started(job_id, playbook, params, username)

    async def on_job_finished_ipam(self, job_id: str, success: bool) -> int:
        from backend.plus.ipam.deploy_hook import on_job_finished
        return await on_job_finished(job_id, success)

    async def get_ipam_allocation_for_vm(
        self, portal_node_id: int, vmid: int
    ) -> dict | None:
        from backend.plus.ipam.service import get_allocation_for_vm
        return await get_allocation_for_vm(portal_node_id, vmid)

    # ── Etappe C: Freigabe / Orphan / Pool-Löschen-Block ─────────────────────

    async def ipam_release_impact(
        self, portal_node_id: int, vmid: int
    ) -> list[dict]:
        from backend.plus.ipam import config_service
        if not await config_service.is_global_enabled():
            return []
        from backend.plus.ipam.cleanup import release_impact
        return await release_impact(portal_node_id, vmid)

    async def on_vm_lxc_deleted_ipam(
        self, portal_node_id: int, vmid: int, username: str
    ) -> int:
        from backend.plus.ipam.cleanup import on_vm_lxc_deleted
        return await on_vm_lxc_deleted(portal_node_id, vmid, username)

    async def on_cluster_refresh_vanished_resources_ipam(
        self, still_visible_vmids: set, portal_node_id: int
    ) -> int:
        from backend.plus.ipam import config_service
        if not await config_service.is_global_enabled():
            return 0
        from backend.plus.ipam.cleanup import on_cluster_refresh_vanished_resources
        return await on_cluster_refresh_vanished_resources(
            still_visible_vmids, portal_node_id
        )

    async def ipam_assert_pool_deletable(self, pool_id: int) -> None:
        from backend.plus.ipam.cleanup import assert_pool_deletable
        await assert_pool_deletable(pool_id)

    # ── Etappe D: Netz-Freigaben / Sichtbarkeits-Filter ──────────────────────

    async def filter_visible_networks(
        self, user, bridges: list, vnets: list, node: str
    ) -> tuple:
        from backend.plus.ipam import config_service
        if not await config_service.is_global_enabled():
            return bridges, vnets
        from backend.plus.ipam.grants_service import filter_networks
        return await filter_networks(user, bridges, vnets, node)

    async def ipam_filter_pools(self, user, pools: list) -> list:
        from backend.plus.ipam import config_service
        if not await config_service.is_global_enabled():
            return pools
        from backend.plus.ipam.grants_service import filter_pools
        return await filter_pools(user, pools)
