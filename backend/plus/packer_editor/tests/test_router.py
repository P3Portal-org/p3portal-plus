# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-92: /api/packer-editor router tests. AC-RBAC-1/2/3 / EC-1/11 / 422."""
from __future__ import annotations

from unittest.mock import patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from backend.core.security import create_access_token
from backend.db.database import get_db, init_db
from backend.plus.packer_editor.router import router

pytestmark = pytest.mark.plus_only

app = FastAPI()
app.include_router(router)

_ADMIN_TOKEN = create_access_token("admin", auth_type="local", role="admin", portal_permissions=[])
_OP_TOKEN = create_access_token("alice", auth_type="local", role="operator", portal_permissions=[])
_ADMIN_H = {"Authorization": f"Bearer {_ADMIN_TOKEN}"}
_OP_H = {"Authorization": f"Bearer {_OP_TOKEN}"}

_ISO_DEF = {
    "id": "deb13",
    "name": "Debian 13",
    "description": "test",
    "required_role": "operator",
    "source": {"type": "proxmox-iso", "ssh_private_key_name": "sysadm"},
    "installer": {
        "os_profile": "debian-preseed",
        "root_password_plain": "changeme123",
        "ssh_public_key": "ssh-ed25519 AAAA svc",
    },
    "provisioners": [
        {"type": "file", "source_name": "cloud.cfg", "source_content": "# cfg", "destination": "/tmp/c"},
    ],
    "side_files": {"sysadm": "PRIVKEY"},
}


@pytest_asyncio.fixture
async def client():
    await init_db()
    async with get_db() as db:
        for uid, uname, role in ((1, "admin", "admin"), (2, "alice", "operator")):
            try:
                await db.execute(
                    text(
                        "INSERT INTO local_users (id, username, password_hash, role, active, created_at) "
                        "VALUES (:id, :u, 'x', :r, 1, '2026-01-01T00:00:00')"
                    ),
                    {"id": uid, "u": uname, "r": role},
                )
            except Exception:
                pass
        await db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


def _plus():
    return patch("backend.plus.packer_editor.router.plus_behavior")


# ── Unauthenticated / RBAC ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_unauthenticated(client):
    r = await client.get("/api/packer-editor/definitions")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_operator_forbidden(client):
    with _plus() as pb:
        pb.can_use_packer_editor.return_value = True
        r = await client.get("/api/packer-editor/definitions", headers=_OP_H)
    assert r.status_code == 403  # require_admin (AC-RBAC-3)


# ── Plus-gate 404 (AC-RBAC-2) ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_plus_gate_list(client):
    with _plus() as pb:
        pb.can_use_packer_editor.return_value = False
        r = await client.get("/api/packer-editor/definitions", headers=_ADMIN_H)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_plus_gate_create(client):
    with _plus() as pb:
        pb.can_use_packer_editor.return_value = False
        r = await client.post("/api/packer-editor/definitions", json=_ISO_DEF, headers=_ADMIN_H)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_plus_gate_preview(client):
    with _plus() as pb:
        pb.can_use_packer_editor.return_value = False
        r = await client.post("/api/packer-editor/preview", json=_ISO_DEF, headers=_ADMIN_H)
    assert r.status_code == 404


# ── Happy path CRUD ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_list_get_delete(client, patch_packer_dir):
    with _plus() as pb:
        pb.can_use_packer_editor.return_value = True
        # create
        r = await client.post("/api/packer-editor/definitions", json=_ISO_DEF, headers=_ADMIN_H)
        assert r.status_code == 201, r.text
        assert r.json()["id"] == "deb13"
        # list
        r = await client.get("/api/packer-editor/definitions", headers=_ADMIN_H)
        assert r.status_code == 200
        assert [d["id"] for d in r.json()] == ["deb13"]
        # get (roundtrip model)
        r = await client.get("/api/packer-editor/definitions/deb13", headers=_ADMIN_H)
        assert r.status_code == 200
        body = r.json()
        assert body["source"]["type"] == "proxmox-iso"
        # plain password never returned
        assert body["installer"]["root_password_plain"] is None
        # delete
        r = await client.delete("/api/packer-editor/definitions/deb13", headers=_ADMIN_H)
        assert r.status_code == 204
        r = await client.get("/api/packer-editor/definitions/deb13", headers=_ADMIN_H)
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_create_collision_409(client, patch_packer_dir):
    with _plus() as pb:
        pb.can_use_packer_editor.return_value = True
        await client.post("/api/packer-editor/definitions", json=_ISO_DEF, headers=_ADMIN_H)
        r = await client.post("/api/packer-editor/definitions", json=_ISO_DEF, headers=_ADMIN_H)
    assert r.status_code == 409
    assert r.json()["detail"] == "definition_exists"


@pytest.mark.asyncio
async def test_create_foreign_collision_409(client, patch_packer_dir):
    foreign = patch_packer_dir / "deb13"
    foreign.mkdir()
    (foreign / "deb13.pkr.hcl").write_text("# foreign")
    with _plus() as pb:
        pb.can_use_packer_editor.return_value = True
        r = await client.post("/api/packer-editor/definitions", json=_ISO_DEF, headers=_ADMIN_H)
    assert r.status_code == 409
    assert r.json()["detail"] == "foreign_definition_exists"


@pytest.mark.asyncio
async def test_update_id_mismatch_400(client, patch_packer_dir):
    with _plus() as pb:
        pb.can_use_packer_editor.return_value = True
        r = await client.put("/api/packer-editor/definitions/other", json=_ISO_DEF, headers=_ADMIN_H)
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_update_not_found_404(client, patch_packer_dir):
    with _plus() as pb:
        pb.can_use_packer_editor.return_value = True
        r = await client.put("/api/packer-editor/definitions/deb13", json=_ISO_DEF, headers=_ADMIN_H)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_invalid_id_422(client, patch_packer_dir):
    bad = dict(_ISO_DEF, id="../escape")
    with _plus() as pb:
        pb.can_use_packer_editor.return_value = True
        r = await client.post("/api/packer-editor/definitions", json=bad, headers=_ADMIN_H)
    assert r.status_code == 422


# ── validate / preview ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_validate_returns_warnings(client, patch_packer_dir):
    # iso without installer → semantic warning, but still ok (non-blocking)
    no_inst = dict(_ISO_DEF)
    no_inst = {k: v for k, v in no_inst.items() if k != "installer"}
    with _plus() as pb:
        pb.can_use_packer_editor.return_value = True
        r = await client.post("/api/packer-editor/validate", json=no_inst, headers=_ADMIN_H)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert any("ohne Installer" in w for w in body["warnings"])


@pytest.mark.asyncio
async def test_preview_projection(client, patch_packer_dir):
    with _plus() as pb:
        pb.can_use_packer_editor.return_value = True
        r = await client.post("/api/packer-editor/preview", json=_ISO_DEF, headers=_ADMIN_H)
    assert r.status_code == 200
    body = r.json()
    assert 'source "proxmox-iso" "builder" {' in body["hcl"]
    assert "http/preseed.cfg" in body["files"]
    # preview shows the hash, never the plain password
    assert "changeme123" not in body["files"]["http/preseed.cfg"]
    assert "$6$" in body["files"]["http/preseed.cfg"]
    assert "iso_file" in body["meta_yaml"]
