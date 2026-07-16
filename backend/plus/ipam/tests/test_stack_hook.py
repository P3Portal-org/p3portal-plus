# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-42 Phase 2: Stacks-IPAM-Integration (reserve/confirm/destroy-release)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.plus.ipam import service, stack_hook
from backend.plus.ipam.tests.conftest import _enable_global, _make_pool

pytestmark = pytest.mark.plus_only


def _resolved(ip_cidr, mode="static"):
    return SimpleNamespace(ip_mode=mode, ip_address_cidr=ip_cidr, ip_gateway=None)


def _resource(name="web", node=None, bridge="vmbr0"):
    return SimpleNamespace(name=name, node=node,
                           network=SimpleNamespace(bridge=bridge, tag=None))


def _patch_ci(monkeypatch, resolved: dict, resources: dict):
    import backend.plus.stacks.cloud_init as ci
    from unittest.mock import AsyncMock
    monkeypatch.setattr(ci, "resolve_for_transpile", AsyncMock(return_value=resolved))
    monkeypatch.setattr(ci, "_resource_by_name", lambda spec: resources)


def _ip_of():
    assert stack_hook._ip_of("192.168.2.50/24") == "192.168.2.50"
    assert stack_hook._ip_of("dhcp") is None
    assert stack_hook._ip_of(None) is None


@pytest.mark.asyncio
async def test_reserve_stack_ips_static(db, monkeypatch):
    await _enable_global()
    pid = await _make_pool()
    _patch_ci(monkeypatch, {"web": _resolved("192.168.2.50/24")}, {"web": _resource()})
    n = await stack_hook.reserve_stack_ips(1, 555, spec=object(), username="alice")
    assert n == 1
    allocs = await service.list_allocations(pool_id=pid)
    assert len(allocs) == 1
    a = allocs[0]
    assert a.status == "pending" and a.source == "stack"
    assert a.stack_deployment_id == 555 and a.ip == "192.168.2.50"
    assert a.note == "web"  # resource_name für die confirm-Zuordnung


@pytest.mark.asyncio
async def test_reserve_skips_dhcp_and_no_pool(db, monkeypatch):
    await _enable_global()
    await _make_pool()
    _patch_ci(monkeypatch,
              {"web": _resolved("192.168.2.50/24", mode="dhcp"),
               "db": _resolved("172.16.0.9/24")},   # 172.x → kein Pool
              {"web": _resource(), "db": _resource("db")})
    n = await stack_hook.reserve_stack_ips(1, 555, spec=object(), username="alice")
    assert n == 0


@pytest.mark.asyncio
async def test_reserve_disabled_when_global_off(db, monkeypatch):
    await _make_pool()  # global bleibt AUS
    _patch_ci(monkeypatch, {"web": _resolved("192.168.2.50/24")}, {"web": _resource()})
    assert await stack_hook.reserve_stack_ips(1, 555, spec=object(), username="a") == 0


@pytest.mark.asyncio
async def test_reserve_conflict_rolls_back(db, monkeypatch):
    await _enable_global()
    pid = await _make_pool()
    # .50 bereits belegt → Kollision für den Stack-Deploy
    await service.reserve_specific(pid, "192.168.2.50", "bob", "proxmox", job_id="x")
    _patch_ci(monkeypatch,
              {"a": _resolved("192.168.2.51/24"), "web": _resolved("192.168.2.50/24")},
              {"a": _resource("a"), "web": _resource("web")})
    with pytest.raises(HTTPException) as exc:
        await stack_hook.reserve_stack_ips(1, 777, spec=object(), username="alice")
    assert exc.value.status_code == 409
    # Teil-Reservierung (.51) wurde zurückgerollt → nur die Fremd-Allocation bleibt
    stack_allocs = await service.list_allocations()
    assert all(a.stack_deployment_id != 777 for a in stack_allocs)


async def _add_deployed(stack_id, deployment_id, resource_name, vmid, pnid=1):
    from sqlalchemy import text
    from backend.db.database import get_db
    async with get_db() as d:
        # minimale Parent-Rows (FK stack_deployed_resources → nodes/stacks/stack_deployments)
        await d.execute(text(
            "INSERT INTO nodes (id, name, url, proxmox_node, created_at) "
            "VALUES (:id, 'pve', 'https://x:8006', 'pve', '2026-01-01') ON CONFLICT DO NOTHING"),
            {"id": pnid})
        await d.execute(text(
            "INSERT INTO stacks (id, name, yaml_text, current_etag, created_at, updated_at) "
            "VALUES (:id, 'st', 'x', 'e', '2026-01-01', '2026-01-01') ON CONFLICT DO NOTHING"),
            {"id": stack_id})
        await d.execute(text(
            "INSERT INTO stack_deployments (id, stack_id, operation, started_at) "
            "VALUES (:did, :sid, 'apply', '2026-01-01') ON CONFLICT DO NOTHING"),
            {"did": deployment_id, "sid": stack_id})
        await d.execute(text(
            "INSERT INTO stack_deployed_resources "
            "(stack_id, deployment_id, resource_name, portal_node_id, node, vmid, kind, created_at) "
            "VALUES (:sid, :did, :rn, :pnid, 'pve', :vmid, 'vm', '2026-01-01')"),
            {"sid": stack_id, "did": deployment_id, "rn": resource_name, "pnid": pnid, "vmid": vmid})
        await d.commit()


@pytest.mark.asyncio
async def test_confirm_stack_ips(db, monkeypatch):
    await _enable_global()
    pid = await _make_pool()
    _patch_ci(monkeypatch, {"web": _resolved("192.168.2.50/24")}, {"web": _resource()})
    await stack_hook.reserve_stack_ips(1, 555, spec=object(), username="alice")
    await _add_deployed(1, 555, "web", vmid=100)
    n = await stack_hook.confirm_stack_ips(555)
    assert n == 1
    confirmed = await service.list_allocations(pool_id=pid, status="confirmed")
    assert len(confirmed) == 1 and confirmed[0].vmid == 100


@pytest.mark.asyncio
async def test_confirm_releases_undeployed(db, monkeypatch):
    await _enable_global()
    pid = await _make_pool()
    _patch_ci(monkeypatch,
              {"web": _resolved("192.168.2.50/24"), "db": _resolved("192.168.2.51/24")},
              {"web": _resource("web"), "db": _resource("db")})
    await stack_hook.reserve_stack_ips(1, 555, spec=object(), username="alice")
    # nur "web" wurde real deployt → "db"-Reservierung wird freigegeben
    await _add_deployed(1, 555, "web", vmid=100)
    n = await stack_hook.confirm_stack_ips(555)
    assert n == 1
    all_allocs = await service.list_allocations(pool_id=pid)
    assert len(all_allocs) == 1 and all_allocs[0].note == "web"


@pytest.mark.asyncio
async def test_release_on_destroy(db, monkeypatch):
    await _enable_global()
    pid = await _make_pool()
    _patch_ci(monkeypatch, {"web": _resolved("192.168.2.50/24")}, {"web": _resource()})
    await stack_hook.reserve_stack_ips(1, 555, spec=object(), username="alice")
    await _add_deployed(1, 555, "web", vmid=100)
    await stack_hook.confirm_stack_ips(555)
    # Destroy gibt die confirmed-IP der Stack-VM aktiv frei
    n = await stack_hook.release_stack_on_destroy(1, "alice")
    assert n == 1
    assert await service.list_allocations(pool_id=pid) == []
