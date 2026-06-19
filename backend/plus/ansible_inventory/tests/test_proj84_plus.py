# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-84 Plus: Discovery + Onboarding-Router.

404-in-Core-Gate (Pure-Core-Smoke-Äquivalent) + Erfolgs-Pfad (plus_behavior gepatcht, damit der
Test unabhängig vom globalen Singleton ist)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.core.deps import CurrentUser, get_current_user
from backend.core.security import create_access_token
from backend.db.database import init_db
from backend.plus.ansible_inventory import router as plus_router
from backend.plus.ansible_inventory.router import discovery_router

app = FastAPI()
app.include_router(discovery_router)

_ADMIN = create_access_token("admin", auth_type="local", role="admin")
_H_ADMIN = {"Authorization": f"Bearer {_ADMIN}"}


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    from backend.core.config import settings
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))


@pytest_asyncio.fixture
async def client():
    await init_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


# ── 404 in Pure Core (Edition-Gate, Pure-Core-Smoke) ──────────────────────────

@pytest.mark.asyncio
async def test_discovery_404_in_core(client):
    resp = await client.get("/api/ansible-inventory/discovery?node=1", headers=_H_ADMIN)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_onboard_404_in_core(client):
    resp = await client.post(
        "/api/ansible-inventory/onboard",
        json={"portal_node_id": 1, "kind": "qemu", "vmid": 100}, headers=_H_ADMIN,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_onboard_bulk_404_in_core(client):
    resp = await client.post(
        "/api/ansible-inventory/onboard/bulk",
        json={"hosts": [{"portal_node_id": 1, "kind": "qemu", "vmid": 100}]}, headers=_H_ADMIN,
    )
    assert resp.status_code == 404


# ── Erfolgs-Pfad (plus_behavior gepatcht → Singleton-unabhängig) ──────────────

def _plus_mock():
    pb = MagicMock()
    pb.can_use_ansible_inventory.return_value = True
    pb.get_injection_public_keys_extra = AsyncMock(return_value=["ssh-ed25519 AAAAGLOBAL global"])
    return pb


@pytest.mark.asyncio
async def test_onboard_success_sets_managed_and_returns_block(client):
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        username="admin", auth_type="local", role="admin", user_id=1
    )
    try:
        with patch.object(plus_router, "plus_behavior", new=_plus_mock()), \
             patch.object(plus_router.host_state, "get_host_state", new=AsyncMock(return_value=None)), \
             patch.object(plus_router.host_state, "set_managed", new=AsyncMock()) as set_mgd, \
             patch.object(plus_router, "write_audit_log", new=AsyncMock()):
            resp = await client.post(
                "/api/ansible-inventory/onboard",
                json={"portal_node_id": 1, "kind": "qemu", "vmid": 100}, headers=_H_ADMIN,
            )
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert body["detail"] == "onboarded"
    assert body["host_ref"] == "1:100:qemu"
    assert body["key_count"] == 1
    assert "p3-ansible" in body["block"]            # Onboarding-Block enthält Service-User
    assert body["skipped_already_managed"] is False
    # ssh_managed=true + global_opt_in=true gesetzt (ownership-frei)
    set_mgd.assert_awaited_once()
    assert set_mgd.await_args.kwargs.get("global_opt_in") is True


@pytest.mark.asyncio
async def test_onboard_bulk_partial_success(client):
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        username="admin", auth_type="local", role="admin", user_id=1
    )
    # 100 = neu → onboarded ; 101 = schon managed+global → skipped ; bogus kind → failed
    async def _state(node, vmid, kind):
        if vmid == 101:
            return {"ssh_managed": True, "global_opt_in": True}
        return None
    try:
        with patch.object(plus_router, "plus_behavior", new=_plus_mock()), \
             patch.object(plus_router.host_state, "get_host_state", new=AsyncMock(side_effect=_state)), \
             patch.object(plus_router.host_state, "set_managed", new=AsyncMock()), \
             patch.object(plus_router, "write_audit_log", new=AsyncMock()):
            resp = await client.post(
                "/api/ansible-inventory/onboard/bulk",
                json={"hosts": [
                    {"portal_node_id": 1, "kind": "qemu", "vmid": 100},
                    {"portal_node_id": 1, "kind": "qemu", "vmid": 101},
                    {"portal_node_id": 1, "kind": "bogus", "vmid": 102},
                ]},
                headers=_H_ADMIN,
            )
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert body["onboarded"] == 1
    assert body["skipped"] == 1
    assert len(body["failed"]) == 1 and body["failed"][0]["reason"] == "invalid_kind"


@pytest.mark.asyncio
async def test_discovery_success_maps_hosts(client):
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        username="admin", auth_type="local", role="admin", user_id=1
    )
    disc = {"portal_node_id": 1, "error": None, "hosts": [
        {"host_ref": "1:100:qemu", "portal_node_id": 1, "proxmox_node": "pve1", "vmid": 100,
         "kind": "qemu", "name": "web", "status": "running", "managed": True,
         "in_run_scope": True, "ip": "10.0.0.9"},
    ]}
    try:
        with patch.object(plus_router, "plus_behavior", new=_plus_mock()), \
             patch.object(plus_router._inv, "build_discovery", new=AsyncMock(return_value=disc)):
            resp = await client.get("/api/ansible-inventory/discovery?node=1", headers=_H_ADMIN)
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert body["portal_node_id"] == 1
    assert body["hosts"][0]["managed"] is True and body["hosts"][0]["in_run_scope"] is True
