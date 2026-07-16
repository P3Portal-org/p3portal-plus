# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-42 Phase 2: Playbook-Deploy-Reservierung (Extraktion + Lebenszyklus)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.plus.ipam import deploy_hook, service
from backend.plus.ipam.tests.conftest import _enable_global, _make_pool

pytestmark = pytest.mark.plus_only


def _param(pid, ptype):
    return SimpleNamespace(id=pid, type=ptype)


def _detail():
    """Playbook-Detail mit den vier relevanten Param-Typen (IDs frei gewählt)."""
    return SimpleNamespace(parameters=[
        _param("vm_ipconfig", "ip_config"),
        _param("vm_bridge", "proxmox_bridge"),
        _param("proxmox_node", "proxmox_node"),
        _param("vm_id", "integer"),
    ])


def _patch_meta(monkeypatch, detail=None):
    import backend.services.playbook_service as ps
    monkeypatch.setattr(ps, "get_playbook", lambda pb: detail if detail is not None else _detail())


def _params(ip="192.168.2.50"):
    return {
        "vm_ipconfig": f"ip={ip}/24,gw=192.168.2.1",
        "vm_bridge": "vmbr0",
        "proxmox_node": "pve",
        "vm_id": 100,
    }


@pytest.mark.asyncio
async def test_reserve_on_job_start(db, monkeypatch):
    await _enable_global()
    pid = await _make_pool()
    _patch_meta(monkeypatch)
    n = await deploy_hook.on_playbook_job_started("j1", "vm-deploy", _params(), "alice")
    assert n == 1
    allocs = await service.list_allocations(pool_id=pid)
    assert len(allocs) == 1
    a = allocs[0]
    assert a.status == "pending" and a.ip == "192.168.2.50"
    assert a.vmid == 100 and a.job_id == "j1" and a.source == "proxmox"


@pytest.mark.asyncio
async def test_no_reserve_when_global_off(db, monkeypatch):
    await _make_pool()  # global bleibt AUS
    _patch_meta(monkeypatch)
    assert await deploy_hook.on_playbook_job_started("j1", "pb", _params(), "a") == 0


@pytest.mark.asyncio
async def test_no_reserve_dhcp(db, monkeypatch):
    await _enable_global()
    await _make_pool()
    _patch_meta(monkeypatch)
    p = _params()
    p["vm_ipconfig"] = "ip=dhcp"
    assert await deploy_hook.on_playbook_job_started("j1", "pb", p, "a") == 0


@pytest.mark.asyncio
async def test_no_reserve_ip_outside_pool(db, monkeypatch):
    await _enable_global()
    await _make_pool()
    _patch_meta(monkeypatch)
    assert await deploy_hook.on_playbook_job_started(
        "j1", "pb", _params(ip="172.16.0.9"), "a") == 0


@pytest.mark.asyncio
async def test_collision_raises_409(db, monkeypatch):
    await _enable_global()
    pid = await _make_pool()
    await service.reserve_specific(pid, "192.168.2.50", "bob", "proxmox", job_id="other")
    _patch_meta(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        await deploy_hook.on_playbook_job_started("j1", "pb", _params(), "alice")
    assert exc.value.status_code == 409
    assert exc.value.detail["error"] == "ipam_reservation_conflict"


@pytest.mark.asyncio
async def test_job_finished_confirms(db, monkeypatch):
    await _enable_global()
    pid = await _make_pool()
    _patch_meta(monkeypatch)
    await deploy_hook.on_playbook_job_started("j1", "pb", _params(), "alice")
    assert await deploy_hook.on_job_finished("j1", True) == 1
    confirmed = await service.list_allocations(pool_id=pid, status="confirmed")
    assert len(confirmed) == 1 and confirmed[0].vmid == 100


@pytest.mark.asyncio
async def test_job_finished_releases_on_failure(db, monkeypatch):
    await _enable_global()
    pid = await _make_pool()
    _patch_meta(monkeypatch)
    await deploy_hook.on_playbook_job_started("j1", "pb", _params(), "alice")
    assert await deploy_hook.on_job_finished("j1", False) == 1
    assert await service.list_allocations(pool_id=pid) == []
