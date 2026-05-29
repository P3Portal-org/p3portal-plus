# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-74: Tests für den /api/config-snapshots Router (Plus-Modul)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.core.security import create_access_token
from backend.db.database import init_db
from backend.plus.config_snapshots.router import router

pytestmark = pytest.mark.plus_only

app = FastAPI()
app.include_router(router)

_ADMIN_TOKEN = create_access_token("admin", auth_type="local", role="admin", portal_permissions=[])
_OP_TOKEN = create_access_token(
    "operator", auth_type="local", role="operator", portal_permissions=[]
)
_VIEWER_TOKEN = create_access_token(
    "viewer", auth_type="local", role="viewer", portal_permissions=[]
)

_ADMIN_H = {"Authorization": f"Bearer {_ADMIN_TOKEN}"}
_OP_H = {"Authorization": f"Bearer {_OP_TOKEN}"}
_VIEWER_H = {"Authorization": f"Bearer {_VIEWER_TOKEN}"}


@pytest.fixture(autouse=True)
def patch_data_dir(tmp_path, monkeypatch):
    from backend.core.config import settings
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))


@pytest_asyncio.fixture
async def client():
    await init_db()
    from backend.db.database import get_sync_engine
    from backend.plus.config_snapshots.models import plus_metadata as _cs_meta
    eng = get_sync_engine()
    if eng:
        _cs_meta.create_all(eng)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


# ── Unauthenticated ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_unauthenticated(client):
    r = await client.get("/api/config-snapshots")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_create_unauthenticated(client):
    r = await client.post(
        "/api/config-snapshots/1/pve/100/create",
        json={"note": "x"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_restore_unauthenticated(client):
    r = await client.post(
        "/api/config-snapshots/snap-1/restore",
        json={"vm_name_confirm": "vm", "etag": "abc"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_delete_unauthenticated(client):
    r = await client.delete("/api/config-snapshots/snap-1")
    assert r.status_code == 401


# ── Plus-gate: 404 when feature not licensed ──────────────────────────────────

@pytest.mark.asyncio
async def test_plus_gate_list_by_node(client):
    with patch(
        "backend.plus.config_snapshots.router.plus_behavior"
    ) as mock_pb:
        mock_pb.can_use_config_snapshots.return_value = False
        r = await client.get("/api/config-snapshots/by-node/1", headers=_ADMIN_H)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_plus_gate_orphans(client):
    with patch(
        "backend.plus.config_snapshots.router.plus_behavior"
    ) as mock_pb:
        mock_pb.can_use_config_snapshots.return_value = False
        r = await client.get("/api/config-snapshots/orphans", headers=_ADMIN_H)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_plus_gate_diff(client):
    with patch(
        "backend.plus.config_snapshots.router.plus_behavior"
    ) as mock_pb:
        mock_pb.can_use_config_snapshots.return_value = False
        r = await client.get(
            "/api/config-snapshots/diff?a=x&b=y", headers=_ADMIN_H
        )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_plus_gate_bulk_download(client):
    with patch(
        "backend.plus.config_snapshots.router.plus_behavior"
    ) as mock_pb:
        mock_pb.can_use_config_snapshots.return_value = False
        r = await client.post(
            "/api/config-snapshots/bulk-download",
            json={"ids": ["x"]},
            headers=_ADMIN_H,
        )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_plus_gate_create(client):
    with patch(
        "backend.plus.config_snapshots.router.plus_behavior"
    ) as mock_pb:
        mock_pb.can_use_config_snapshots.return_value = False
        r = await client.post(
            "/api/config-snapshots/1/pve/100/create?kind=qemu",
            json={"note": "test"},
            headers=_ADMIN_H,
        )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_plus_gate_restore(client):
    with patch(
        "backend.plus.config_snapshots.router.plus_behavior"
    ) as mock_pb:
        mock_pb.can_use_config_snapshots.return_value = False
        r = await client.post(
            "/api/config-snapshots/snap-1/restore",
            json={"vm_name_confirm": "vm", "etag": "abc"},
            headers=_ADMIN_H,
        )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_plus_gate_delete(client):
    with patch(
        "backend.plus.config_snapshots.router.plus_behavior"
    ) as mock_pb:
        mock_pb.can_use_config_snapshots.return_value = False
        r = await client.delete("/api/config-snapshots/snap-1", headers=_ADMIN_H)
    assert r.status_code == 404


# ── With Plus active: 404 on nonexistent snapshot ────────────────────────────

@pytest.mark.asyncio
async def test_get_snapshot_not_found(client):
    with patch(
        "backend.plus.config_snapshots.router.plus_behavior"
    ) as mock_pb:
        mock_pb.can_use_config_snapshots.return_value = True
        r = await client.get("/api/config-snapshots/nonexistent", headers=_ADMIN_H)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_diff_live_snapshot_not_found(client):
    with patch(
        "backend.plus.config_snapshots.router.plus_behavior"
    ) as mock_pb:
        mock_pb.can_use_config_snapshots.return_value = True
        r = await client.get(
            "/api/config-snapshots/snap-xyz/diff-live?portal_node_id=1&proxmox_node=pve&vmid=100&kind=qemu",
            headers=_ADMIN_H,
        )
    assert r.status_code == 404


# ── By-node list: admin gets empty list when Plus active ─────────────────────

@pytest.mark.asyncio
async def test_list_by_node_empty(client):
    with patch(
        "backend.plus.config_snapshots.router.plus_behavior"
    ) as mock_pb:
        mock_pb.can_use_config_snapshots.return_value = True
        r = await client.get("/api/config-snapshots/by-node/1", headers=_ADMIN_H)
    assert r.status_code == 200
    assert r.json() == []


# ── Orphan endpoint: operator gets 403 ───────────────────────────────────────

@pytest.mark.asyncio
async def test_orphans_forbidden_for_operator(client):
    with patch(
        "backend.plus.config_snapshots.router.plus_behavior"
    ) as mock_pb:
        mock_pb.can_use_config_snapshots.return_value = True
        r = await client.get("/api/config-snapshots/orphans", headers=_OP_H)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_orphans_accessible_for_admin(client):
    with patch(
        "backend.plus.config_snapshots.router.plus_behavior"
    ) as mock_pb:
        mock_pb.can_use_config_snapshots.return_value = True
        r = await client.get("/api/config-snapshots/orphans", headers=_ADMIN_H)
    assert r.status_code == 200
    assert r.json() == []
