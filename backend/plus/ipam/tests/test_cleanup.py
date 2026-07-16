# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-42 Phase 2: Freigabe-/Orphan-Verhalten + Pool-Löschen-Block."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.plus.ipam import cleanup, service
from backend.plus.ipam.tests.conftest import _make_pool

pytestmark = pytest.mark.plus_only


async def _confirmed(pid, ip, vmid, node_id=1, job="j"):
    await service.reserve_specific(pid, ip, "alice", "proxmox",
                                   job_id=job, vmid=vmid, portal_node_id=node_id)
    await service.confirm_by_job(job)


@pytest.mark.asyncio
async def test_release_impact_lists_allocations(db):
    pid = await _make_pool()
    await _confirmed(pid, "192.168.2.50", 100)
    impact = await cleanup.release_impact(1, 100)
    assert len(impact) == 1 and impact[0]["ip"] == "192.168.2.50"
    assert await cleanup.release_impact(1, 999) == []


@pytest.mark.asyncio
async def test_on_vm_deleted_releases(db):
    pid = await _make_pool()
    await _confirmed(pid, "192.168.2.50", 100)
    n = await cleanup.on_vm_lxc_deleted(1, 100, "alice")
    assert n == 1
    assert await service.list_allocations(pool_id=pid) == []


@pytest.mark.asyncio
async def test_vanished_marks_orphaned_and_reactivates(db):
    pid = await _make_pool()
    await _confirmed(pid, "192.168.2.50", 100)
    # VMID 100 nicht mehr sichtbar → orphaned
    changed = await cleanup.on_cluster_refresh_vanished_resources(set(), 1)
    assert changed == 1
    orphans = await service.list_allocations(status="orphaned")
    assert len(orphans) == 1
    # VMID 100 taucht wieder auf → confirmed
    changed2 = await cleanup.on_cluster_refresh_vanished_resources({100}, 1)
    assert changed2 == 1
    assert await service.list_allocations(status="orphaned") == []
    assert len(await service.list_allocations(status="confirmed")) == 1


@pytest.mark.asyncio
async def test_vanished_ignores_other_node(db):
    pid = await _make_pool()
    await _confirmed(pid, "192.168.2.50", 100, node_id=1)
    # Refresh einer ANDEREN Installation (node_id=2) verwaist nichts auf node 1
    assert await cleanup.on_cluster_refresh_vanished_resources(set(), 2) == 0
    assert len(await service.list_allocations(status="confirmed")) == 1


@pytest.mark.asyncio
async def test_list_and_release_orphans(db):
    pid = await _make_pool()
    await _confirmed(pid, "192.168.2.50", 100, job="j1")
    await _confirmed(pid, "192.168.2.51", 101, job="j2")
    await cleanup.on_cluster_refresh_vanished_resources(set(), 1)
    orphans = await cleanup.list_orphans()
    assert len(orphans) == 2
    # gezielt einen freigeben
    n = await cleanup.release_orphans([orphans[0]["id"]], "admin")
    assert n == 1 and len(await cleanup.list_orphans()) == 1
    # Rest (alle) freigeben
    assert await cleanup.release_orphans(None, "admin") == 1
    assert await cleanup.list_orphans() == []


@pytest.mark.asyncio
async def test_assert_pool_deletable_blocks(db):
    pid = await _make_pool()
    await service.reserve_specific(pid, "192.168.2.50", "alice", "proxmox", job_id="j1")
    with pytest.raises(HTTPException) as exc:
        await cleanup.assert_pool_deletable(pid)
    assert exc.value.status_code == 409
    # nach Freigabe wieder löschbar
    await service.release_pending_by_job("j1")
    await cleanup.assert_pool_deletable(pid)  # kein Wurf
