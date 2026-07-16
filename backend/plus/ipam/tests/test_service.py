# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-42 Phase 2: Allocation-Lebenszyklus – Reservierung/Race/confirm/release/sweep."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.plus.ipam import config_service, service
from backend.plus.ipam.service import IpamReservationConflict
from backend.plus.ipam.tests.conftest import _enable_global, _make_pool

pytestmark = pytest.mark.plus_only


@pytest.mark.asyncio
async def test_reserve_specific_creates_pending(db):
    pid = await _make_pool()
    alloc = await service.reserve_specific(pid, "192.168.2.50", "alice", "proxmox", job_id="j1")
    assert alloc.status == "pending"
    assert alloc.ip == "192.168.2.50"
    assert alloc.owner_username == "alice"
    assert alloc.pending_expires_at is not None


@pytest.mark.asyncio
async def test_reserve_collision_raises(db):
    pid = await _make_pool()
    await service.reserve_specific(pid, "192.168.2.50", "alice", "proxmox", job_id="j1")
    with pytest.raises(IpamReservationConflict):
        await service.reserve_specific(pid, "192.168.2.50", "bob", "proxmox", job_id="j2")


@pytest.mark.asyncio
async def test_confirm_by_job(db):
    pid = await _make_pool()
    await service.reserve_specific(pid, "192.168.2.50", "alice", "proxmox",
                                   job_id="j1", vmid=100, portal_node_id=1)
    n = await service.confirm_by_job("j1")
    assert n == 1
    allocs = await service.list_allocations(pool_id=pid, status="confirmed")
    assert len(allocs) == 1
    assert allocs[0].vmid == 100 and allocs[0].confirmed_at is not None
    assert allocs[0].pending_expires_at is None


@pytest.mark.asyncio
async def test_release_pending_on_failure(db):
    pid = await _make_pool()
    await service.reserve_specific(pid, "192.168.2.50", "alice", "proxmox", job_id="j1")
    n = await service.release_pending_by_job("j1")
    assert n == 1
    assert await service.list_allocations(pool_id=pid) == []


@pytest.mark.asyncio
async def test_confirmed_not_released_by_failure(db):
    pid = await _make_pool()
    await service.reserve_specific(pid, "192.168.2.50", "alice", "proxmox", job_id="j1")
    await service.confirm_by_job("j1")
    # ein späterer (fremder) Fehlschlag darf die confirmed-Allocation nicht löschen
    assert await service.release_pending_by_job("j1") == 0
    assert len(await service.list_allocations(pool_id=pid)) == 1


@pytest.mark.asyncio
async def test_sweep_expired_pending(db):
    pid = await _make_pool()
    await service.reserve_specific(pid, "192.168.2.50", "alice", "proxmox", job_id="j1")
    # Ablaufzeit manuell in die Vergangenheit setzen
    from sqlalchemy import text
    from backend.db.database import get_db
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    async with get_db() as d:
        await d.execute(text("UPDATE ip_allocations SET pending_expires_at = :p"), {"p": past})
        await d.commit()
    swept = await service.sweep_expired_pending()
    assert swept == 1
    assert await service.list_allocations(pool_id=pid) == []


@pytest.mark.asyncio
async def test_reserved_ips_respects_global_toggle(db):
    pid = await _make_pool()
    await service.reserve_specific(pid, "192.168.2.50", "alice", "proxmox", job_id="j1")
    # global AUS (Default) → keine Reservierungssicht (Phase-1-best-effort)
    assert await service.reserved_ips(pid) == set()
    await _enable_global()
    assert await service.reserved_ips(pid) == {"192.168.2.50"}


@pytest.mark.asyncio
async def test_manual_allocation_confirmed(db):
    pid = await _make_pool()
    alloc = await service.add_manual(pid, "192.168.2.99", "Drucker", "admin")
    assert alloc.status == "confirmed" and alloc.source == "manual"
    with pytest.raises(IpamReservationConflict):
        await service.add_manual(pid, "192.168.2.99", "dup", "admin")


@pytest.mark.asyncio
async def test_pool_usage(db):
    pid = await _make_pool(cidr="192.168.2.0/29", gateway="192.168.2.1")
    # /29 → 6 Host-IPs; .1 = Gateway → 5 nutzbar
    await service.reserve_specific(pid, "192.168.2.2", "alice", "proxmox", job_id="j1")
    await service.add_manual(pid, "192.168.2.3", None, "admin")
    usage = await service.pool_usage(pid)
    assert usage.total == 5
    assert usage.used == 2
    assert usage.free == 3


@pytest.mark.asyncio
async def test_find_pool_for_ip(db):
    pid = await _make_pool()  # 192.168.2.0/24 on vmbr0/pve
    other = await _make_pool(network_name="vmbr1", cidr="10.0.0.0/24", gateway=None)
    # CIDR-Match + Bridge-Eingrenzung
    p = await service.find_pool_for_ip("192.168.2.50", bridge="vmbr0", node="pve")
    assert p is not None and p.id == pid
    p2 = await service.find_pool_for_ip("10.0.0.5")
    assert p2 is not None and p2.id == other
    # IP außerhalb aller Pools
    assert await service.find_pool_for_ip("172.16.0.1") is None


@pytest.mark.asyncio
async def test_get_allocation_for_vm(db):
    pid = await _make_pool()
    await service.reserve_specific(pid, "192.168.2.50", "alice", "proxmox",
                                   job_id="j1", vmid=100, portal_node_id=1)
    await service.confirm_by_job("j1")
    got = await service.get_allocation_for_vm(1, 100)
    assert got is not None and got["ip"] == "192.168.2.50"
    assert await service.get_allocation_for_vm(1, 999) is None
