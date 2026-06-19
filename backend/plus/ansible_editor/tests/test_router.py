# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-93: /api/ansible-editor router tests (AC-RBAC-1/2/3, AC-VAL-1, AC-MOD)."""
from __future__ import annotations

from unittest.mock import patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from backend.core.security import create_access_token
from backend.db.database import get_db, init_db
from backend.plus.ansible_editor.router import router

pytestmark = pytest.mark.plus_only

app = FastAPI()
app.include_router(router)

_ADMIN_TOKEN = create_access_token("admin", auth_type="local", role="admin", portal_permissions=[])
_OP_TOKEN = create_access_token("alice", auth_type="local", role="operator", portal_permissions=[])
_ADMIN_H = {"Authorization": f"Bearer {_ADMIN_TOKEN}"}
_OP_H = {"Authorization": f"Bearer {_OP_TOKEN}"}

_DEF = {
    "id": "nginx-setup",
    "name": "Nginx Setup",
    "category": "vm_lxc_config",
    "header": {"targets": "guest", "become": True},
    "tasks": [
        {"name": "apt", "module": "ansible.builtin.apt", "params": {"name": "nginx"}},
        {"name": "copy", "module": "ansible.builtin.copy",
         "params": {"dest": "/var/www/html/index.html", "src": "files/index.html"}},
    ],
    "side_files": {"index.html": "<h1>x</h1>"},
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
    return patch("backend.plus.ansible_editor.router.plus_behavior")


# ── RBAC ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_unauthenticated(client):
    r = await client.get("/api/ansible-editor/definitions")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_operator_forbidden(client):
    with _plus() as pb:
        pb.can_use_ansible_editor.return_value = True
        r = await client.get("/api/ansible-editor/definitions", headers=_OP_H)
    assert r.status_code == 403


# ── Plus-gate 404 (AC-RBAC-1) ─────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path,body", [
    ("get", "/api/ansible-editor/definitions", None),
    ("post", "/api/ansible-editor/definitions", _DEF),
    ("get", "/api/ansible-editor/modules", None),
    ("get", "/api/ansible-editor/modules/ansible.builtin.copy/schema", None),
    ("post", "/api/ansible-editor/preview", _DEF),
    ("post", "/api/ansible-editor/validate", _DEF),
])
async def test_plus_gate_404(client, method, path, body):
    with _plus() as pb:
        pb.can_use_ansible_editor.return_value = False
        fn = getattr(client, method)
        r = await (fn(path, json=body, headers=_ADMIN_H) if body else fn(path, headers=_ADMIN_H))
    assert r.status_code == 404


# ── Modules & schema (AC-MOD) ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_modules(client):
    with _plus() as pb:
        pb.can_use_ansible_editor.return_value = True
        r = await client.get("/api/ansible-editor/modules", headers=_ADMIN_H)
    assert r.status_code == 200
    names = {m["name"] for m in r.json()}
    assert "ansible.builtin.copy" in names


@pytest.mark.asyncio
async def test_module_schema(client):
    with _plus() as pb:
        pb.can_use_ansible_editor.return_value = True
        r = await client.get("/api/ansible-editor/modules/ansible.builtin.service/schema", headers=_ADMIN_H)
    assert r.status_code == 200
    by = {p["name"]: p for p in r.json()["params"]}
    assert by["state"]["widget"] == "dropdown" and by["enabled"]["widget"] == "toggle"


@pytest.mark.asyncio
async def test_module_schema_unknown_404(client):
    with _plus() as pb:
        pb.can_use_ansible_editor.return_value = True
        r = await client.get("/api/ansible-editor/modules/not_a_module/schema", headers=_ADMIN_H)
    assert r.status_code == 404


# ── CRUD happy path ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_list_get_update_delete(client, isolated_env):
    with _plus() as pb:
        pb.can_use_ansible_editor.return_value = True
        r = await client.post("/api/ansible-editor/definitions", json=_DEF, headers=_ADMIN_H)
        assert r.status_code == 201, r.text
        assert r.json()["id"] == "nginx-setup" and r.json()["task_count"] == 2

        r = await client.get("/api/ansible-editor/definitions", headers=_ADMIN_H)
        assert [d["id"] for d in r.json()] == ["nginx-setup"]

        r = await client.get("/api/ansible-editor/definitions/nginx-setup", headers=_ADMIN_H)
        assert r.status_code == 200 and r.json()["header"]["targets"] == "guest"

        upd = {**_DEF, "name": "Renamed"}
        r = await client.put("/api/ansible-editor/definitions/nginx-setup", json=upd, headers=_ADMIN_H)
        assert r.status_code == 200 and r.json()["name"] == "Renamed"

        r = await client.delete("/api/ansible-editor/definitions/nginx-setup", headers=_ADMIN_H)
        assert r.status_code == 204
        r = await client.get("/api/ansible-editor/definitions/nginx-setup", headers=_ADMIN_H)
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_create_duplicate_409(client, isolated_env):
    with _plus() as pb:
        pb.can_use_ansible_editor.return_value = True
        await client.post("/api/ansible-editor/definitions", json=_DEF, headers=_ADMIN_H)
        r = await client.post("/api/ansible-editor/definitions", json=_DEF, headers=_ADMIN_H)
    assert r.status_code == 409 and r.json()["detail"] == "definition_exists"


@pytest.mark.asyncio
async def test_create_foreign_409(client, isolated_env):
    foreign = isolated_env / "nginx-setup"
    foreign.mkdir()
    (foreign / "meta.yaml").write_text("name: x\n")
    with _plus() as pb:
        pb.can_use_ansible_editor.return_value = True
        r = await client.post("/api/ansible-editor/definitions", json=_DEF, headers=_ADMIN_H)
    assert r.status_code == 409 and r.json()["detail"] == "foreign_definition_exists"


# ── hard_validate enforced on save (AC-VAL-1) ─────────────────────────────────


@pytest.mark.asyncio
async def test_create_missing_required_param_400(client, isolated_env):
    bad = {**_DEF, "tasks": [{"name": "cp", "module": "ansible.builtin.copy", "params": {"src": "x"}}]}
    with _plus() as pb:
        pb.can_use_ansible_editor.return_value = True
        r = await client.post("/api/ansible-editor/definitions", json=bad, headers=_ADMIN_H)
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "validation_failed"
    assert any("dest" in e for e in r.json()["detail"]["errors"])


@pytest.mark.asyncio
async def test_create_unknown_module_400(client, isolated_env):
    bad = {**_DEF, "tasks": [{"module": "ansible.builtin.does_not_exist", "params": {}}]}
    with _plus() as pb:
        pb.can_use_ansible_editor.return_value = True
        r = await client.post("/api/ansible-editor/definitions", json=bad, headers=_ADMIN_H)
    assert r.status_code == 400


# ── validate / preview ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_validate_returns_errors_and_warnings(client):
    bad = {**_DEF, "tasks": [{"module": "ansible.builtin.copy", "params": {"src": "x"}}]}
    with _plus() as pb:
        pb.can_use_ansible_editor.return_value = True
        r = await client.post("/api/ansible-editor/validate", json=bad, headers=_ADMIN_H)
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is False and any("dest" in e for e in j["errors"])
    assert any("ohne Namen" in w for w in j["warnings"])


@pytest.mark.asyncio
async def test_preview(client):
    with _plus() as pb:
        pb.can_use_ansible_editor.return_value = True
        r = await client.post("/api/ansible-editor/preview", json=_DEF, headers=_ADMIN_H)
    assert r.status_code == 200
    j = r.json()
    assert "hosts: managed" in j["yaml"]
    assert "playbook: nginx-setup.yml" in j["meta_yaml"]
    assert "files/index.html" in j["files"]
