# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-42 Phase 2: Router-Tests – Endpoints (Plus) + 404-Gate (Core) + RBAC."""
from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import backend.core.plus_protocol as plus_protocol_module
from backend.core.security import create_access_token
from backend.db.database import init_db, get_sync_engine
from backend.features.ipam.router import router as core_router
from backend.plus.ipam import service
from backend.plus.ipam.models import plus_metadata
from backend.plus.ipam.router import router as plus_router

pytestmark = pytest.mark.plus_only

app = FastAPI()
app.include_router(core_router)
app.include_router(plus_router)

_ADMIN = {"Authorization": f"Bearer {create_access_token('admin', auth_type='local', role='admin')}"}
_OPERATOR = {"Authorization": f"Bearer {create_access_token('op', auth_type='local', role='operator')}"}
_RESTRICTED = {"Authorization": f"Bearer {create_access_token('restr', auth_type='local', role='restricted')}"}


@pytest.fixture(autouse=True)
def patch_data_dir(tmp_path, monkeypatch):
    from backend.core.config import settings
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))


@pytest.fixture(autouse=True)
def _plus_active(monkeypatch):
    """Standard: Plus aktiv (is_plus_edition True) – der 404-Test überschreibt das."""
    monkeypatch.setattr(plus_protocol_module, "is_plus_edition", lambda: True)


@pytest_asyncio.fixture
async def client():
    await init_db()
    plus_metadata.create_all(get_sync_engine(), checkfirst=True)
    # PROJ-46-Pools-Tabellen: der VM-Sicht-RBAC-Resolver (for-vm-Härtung) fragt
    # get_pool_permissions ab → in Prod via ensure_plus_db_tables vorhanden.
    try:
        from backend.plus.pools.models import plus_metadata as _pools_meta
        _pools_meta.create_all(get_sync_engine(), checkfirst=True)
    except Exception:
        pass
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def _make_pool(client):
    r = await client.post("/api/ipam/pools", json={
        "kind": "bridge", "network_name": "vmbr0", "node": "pve",
        "cidr": "192.168.2.0/24", "gateway": "192.168.2.1",
    }, headers=_ADMIN)
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ── Plus-Gate (404 in Core) ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_endpoints_404_in_core(client, monkeypatch):
    monkeypatch.setattr(plus_protocol_module, "is_plus_edition", lambda: False)
    for method, path in [
        ("get", "/api/ipam/config"), ("get", "/api/ipam/allocations"),
        ("get", "/api/ipam/orphans"), ("get", "/api/ipam/grants"),
        ("get", "/api/ipam/allocations/for-vm?portal_node_id=1&vmid=100"),
    ]:
        resp = await getattr(client, method)(path, headers=_ADMIN)
        assert resp.status_code == 404, f"{path} → {resp.status_code}"


# ── Config-Toggles ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_config_defaults_and_update(client):
    r = await client.get("/api/ipam/config", headers=_ADMIN)
    assert r.status_code == 200
    assert r.json() == {"global_enabled": False, "strict_network_visibility": False,
                        "updated_by": None, "updated_at": None}
    r2 = await client.put("/api/ipam/config", json={"global_enabled": True}, headers=_ADMIN)
    assert r2.status_code == 200 and r2.json()["global_enabled"] is True


@pytest.mark.asyncio
async def test_config_update_forbidden_for_operator(client):
    assert (await client.put("/api/ipam/config", json={"global_enabled": True},
                             headers=_OPERATOR)).status_code == 403


# ── Allocations ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_manual_allocation_and_usage(client):
    pid = await _make_pool(client)
    r = await client.post("/api/ipam/allocations",
                          json={"pool_id": pid, "ip": "192.168.2.99", "note": "Drucker"},
                          headers=_ADMIN)
    assert r.status_code == 201 and r.json()["status"] == "confirmed"
    # Duplikat → 409
    r2 = await client.post("/api/ipam/allocations",
                           json={"pool_id": pid, "ip": "192.168.2.99"}, headers=_ADMIN)
    assert r2.status_code == 409
    usage = await client.get(f"/api/ipam/pools/{pid}/usage", headers=_ADMIN)
    assert usage.status_code == 200 and usage.json()["used"] == 1
    lst = await client.get("/api/ipam/allocations", headers=_ADMIN)
    assert lst.status_code == 200 and len(lst.json()) == 1


@pytest.mark.asyncio
async def test_release_allocation(client):
    pid = await _make_pool(client)
    r = await client.post("/api/ipam/allocations", json={"pool_id": pid, "ip": "192.168.2.50"},
                          headers=_ADMIN)
    aid = r.json()["id"]
    assert (await client.delete(f"/api/ipam/allocations/{aid}", headers=_ADMIN)).status_code == 204
    assert (await client.delete(f"/api/ipam/allocations/{aid}", headers=_ADMIN)).status_code == 404


@pytest.mark.asyncio
async def test_pool_delete_blocked_with_allocations(client):
    pid = await _make_pool(client)
    await client.post("/api/ipam/allocations", json={"pool_id": pid, "ip": "192.168.2.50"},
                      headers=_ADMIN)
    # Core-Delete-Endpoint ruft den Plus-Block-Hook → 409
    r = await client.delete(f"/api/ipam/pools/{pid}", headers=_ADMIN)
    assert r.status_code == 409


# ── Allocation für VM (read-only VM-Detail-Karte, PROJ-42 Ph2 /frontend) ──────

@pytest.mark.asyncio
async def test_allocation_for_vm_operator_can_read(client):
    """US-7: nicht manage-gated → ein Operator (VM-Owner) sieht die Zuordnung."""
    pid = await _make_pool(client)
    await service.reserve_specific(pid, "192.168.2.50", "op", "proxmox",
                                   job_id="j1", vmid=100, portal_node_id=1)
    await service.confirm_by_job("j1")
    r = await client.get("/api/ipam/allocations/for-vm?portal_node_id=1&vmid=100",
                         headers=_OPERATOR)
    assert r.status_code == 200 and r.json()["ip"] == "192.168.2.50"
    # Keine Allocation → null (kein 404).
    r2 = await client.get("/api/ipam/allocations/for-vm?portal_node_id=1&vmid=999",
                          headers=_OPERATOR)
    assert r2.status_code == 200 and r2.json() is None


@pytest.mark.asyncio
async def test_allocation_for_vm_restricted_forbidden(client):
    r = await client.get("/api/ipam/allocations/for-vm?portal_node_id=1&vmid=100",
                         headers=_RESTRICTED)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_allocation_for_vm_viewer_without_grants_sees_all(client):
    """BUG-42-P2-1-Härtung darf einen Viewer OHNE Grant nicht über-restringieren
    (Dashboard-Backward-Compat: kein Grant → sieht alles, 1:1 _check_detail_access)."""
    from backend.services.local_auth import create_user
    await create_user("viewer1", "pw12345678", "viewer")
    token = create_access_token("viewer1", auth_type="local", role="viewer")
    hdr = {"Authorization": f"Bearer {token}"}
    pid = await _make_pool(client)
    await service.reserve_specific(pid, "192.168.2.50", "alice", "proxmox",
                                   job_id="j1", vmid=100, portal_node_id=1)
    await service.confirm_by_job("j1")
    r = await client.get("/api/ipam/allocations/for-vm?portal_node_id=1&vmid=100",
                         headers=hdr)
    assert r.status_code == 200 and r.json()["ip"] == "192.168.2.50"


# ── Netz-Freigaben ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_grants_crud(client):
    r = await client.post("/api/ipam/grants", json={
        "kind": "bridge", "network_name": "vmbr0", "node": "pve",
        "grantee_kind": "user", "grantee_id": 2,
    }, headers=_ADMIN)
    assert r.status_code == 201, r.text
    gid = r.json()["id"]
    lst = await client.get("/api/ipam/grants", headers=_ADMIN)
    assert lst.status_code == 200 and len(lst.json()) == 1
    assert (await client.delete(f"/api/ipam/grants/{gid}", headers=_ADMIN)).status_code == 204
    assert (await client.get("/api/ipam/grants", headers=_ADMIN)).json() == []


@pytest.mark.asyncio
async def test_grants_forbidden_for_operator(client):
    assert (await client.get("/api/ipam/grants", headers=_OPERATOR)).status_code == 403
