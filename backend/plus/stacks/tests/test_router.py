# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-76: Tests für den /api/stacks Router (Plus-Modul)."""
from __future__ import annotations

from unittest.mock import patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from backend.core.security import create_access_token
from backend.db.database import get_db, get_sync_engine, init_db
from backend.plus.stacks import models as m
from backend.plus.stacks.router import router

pytestmark = pytest.mark.plus_only

app = FastAPI()
app.include_router(router)

_ADMIN_TOKEN = create_access_token("admin", auth_type="local", role="admin", portal_permissions=[])
_OP_TOKEN = create_access_token("alice", auth_type="local", role="operator", portal_permissions=[])

_ADMIN_H = {"Authorization": f"Bearer {_ADMIN_TOKEN}"}
_OP_H = {"Authorization": f"Bearer {_OP_TOKEN}"}

_YAML = (
    "name: webcluster\n"
    "version: '1.0.0'\n"
    "resources:\n"
    "  - type: vm\n"
    "    name: web\n"
    "    node: pve-01\n"
    "    template: deb12\n"
    "    count: 2\n"
)


@pytest.fixture(autouse=True)
def patch_data_dir(tmp_path, monkeypatch):
    from backend.core.config import settings
    monkeypatch.setattr(settings, "data_dir", str(tmp_path), raising=False)


@pytest_asyncio.fixture
async def client():
    await init_db()
    eng = get_sync_engine()
    if eng is not None:
        m.stacks.create(eng, checkfirst=True)
        m.stack_resources.create(eng, checkfirst=True)
        m.stack_versions.create(eng, checkfirst=True)
    # Seed users so get_current_user resolves user_id
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


def _plus_on():
    return patch("backend.plus.stacks.router.plus_behavior")


# ── Unauthenticated ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_unauthenticated(client):
    r = await client.get("/api/stacks")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_create_unauthenticated(client):
    r = await client.post("/api/stacks", json={"yaml_text": _YAML})
    assert r.status_code == 401


# ── Plus-gate: 404 when feature not licensed ──────────────────────────────────

@pytest.mark.asyncio
async def test_plus_gate_list(client):
    with _plus_on() as pb:
        pb.can_use_stacks.return_value = False
        r = await client.get("/api/stacks", headers=_ADMIN_H)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_plus_gate_create(client):
    with _plus_on() as pb:
        pb.can_use_stacks.return_value = False
        r = await client.post("/api/stacks", json={"yaml_text": _YAML}, headers=_ADMIN_H)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_plus_gate_validate(client):
    with _plus_on() as pb:
        pb.can_use_stacks.return_value = False
        r = await client.post("/api/stacks/validate", json={"yaml_text": _YAML}, headers=_ADMIN_H)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_plus_gate_orphans(client):
    with _plus_on() as pb:
        pb.can_use_stacks.return_value = False
        r = await client.get("/api/stacks/orphans", headers=_ADMIN_H)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_plus_gate_detail(client):
    with _plus_on() as pb:
        pb.can_use_stacks.return_value = False
        r = await client.get("/api/stacks/1", headers=_ADMIN_H)
    assert r.status_code == 404


# ── Validate / Preview ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_validate_ok(client):
    with _plus_on() as pb:
        pb.can_use_stacks.return_value = True
        r = await client.post("/api/stacks/validate", json={"yaml_text": _YAML}, headers=_ADMIN_H)
    assert r.status_code == 200
    assert r.json()["valid"] is True


@pytest.mark.asyncio
async def test_validate_invalid(client):
    with _plus_on() as pb:
        pb.can_use_stacks.return_value = True
        r = await client.post(
            "/api/stacks/validate", json={"yaml_text": "name: ab\nresources: []\n"}, headers=_ADMIN_H
        )
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is False and body["errors"]


@pytest.mark.asyncio
async def test_preview_resolves_count(client):
    with _plus_on() as pb:
        pb.can_use_stacks.return_value = True
        r = await client.post("/api/stacks/preview", json={"yaml_text": _YAML}, headers=_ADMIN_H)
    assert r.status_code == 200
    body = r.json()
    assert body["resource_count"] == 2
    assert {res["name"] for res in body["resources"]} == {"web-1", "web-2"}


# ── Create → detail → list → delete (happy path) ──────────────────────────────

@pytest.mark.asyncio
async def test_create_and_get(client):
    with _plus_on() as pb:
        pb.can_use_stacks.return_value = True
        pb.requires_approval.return_value = None
        r = await client.post("/api/stacks", json={"yaml_text": _YAML}, headers=_OP_H)
        assert r.status_code == 201
        sid = r.json()["id"]
        assert r.json()["resource_count"] == 2

        r2 = await client.get(f"/api/stacks/{sid}", headers=_OP_H)
        assert r2.status_code == 200
        assert r2.json()["yaml_text"]


@pytest.mark.asyncio
async def test_owner_isolation(client):
    """A stack created by alice is not visible (403) to another operator."""
    with _plus_on() as pb:
        pb.can_use_stacks.return_value = True
        pb.requires_approval.return_value = None
        r = await client.post("/api/stacks", json={"yaml_text": _YAML}, headers=_OP_H)
        sid = r.json()["id"]
        # admin can see it
        r_admin = await client.get(f"/api/stacks/{sid}", headers=_ADMIN_H)
        assert r_admin.status_code == 200


@pytest.mark.asyncio
async def test_update_etag_conflict_409(client):
    with _plus_on() as pb:
        pb.can_use_stacks.return_value = True
        pb.requires_approval.return_value = None
        r = await client.post("/api/stacks", json={"yaml_text": _YAML}, headers=_OP_H)
        sid = r.json()["id"]
        r2 = await client.put(
            f"/api/stacks/{sid}",
            json={"yaml_text": _YAML, "expected_etag": "0" * 64},
            headers=_OP_H,
        )
    assert r2.status_code == 409
    body = r2.json()
    assert "current_etag" in body and "current_yaml" in body


@pytest.mark.asyncio
async def test_update_missing_etag_422(client):
    with _plus_on() as pb:
        pb.can_use_stacks.return_value = True
        pb.requires_approval.return_value = None
        r = await client.post("/api/stacks", json={"yaml_text": _YAML}, headers=_OP_H)
        sid = r.json()["id"]
        r2 = await client.put(f"/api/stacks/{sid}", json={"yaml_text": _YAML}, headers=_OP_H)
    assert r2.status_code == 422


@pytest.mark.asyncio
async def test_update_approval_202(client):
    """When requires_approval returns a decision, PUT returns 202 pending."""
    from backend.core.plus_protocol import ApprovalDecision
    from datetime import datetime, timezone

    decision = ApprovalDecision(
        approval_id="appr_test", action_type="stack_edit", action_target="1",
        expires_at=datetime.now(timezone.utc), poll_url="/api/approvals/appr_test",
    )
    with _plus_on() as pb:
        pb.can_use_stacks.return_value = True
        pb.requires_approval.return_value = None
        r = await client.post("/api/stacks", json={"yaml_text": _YAML}, headers=_OP_H)
        sid = r.json()["id"]
        etag = r.json()["current_etag"]

        async def _decide(*a, **k):
            return decision
        pb.requires_approval.side_effect = _decide
        r2 = await client.put(
            f"/api/stacks/{sid}",
            json={"yaml_text": _YAML, "expected_etag": etag},
            headers=_OP_H,
        )
    assert r2.status_code == 202
    assert r2.json()["status"] == "pending_approval"


@pytest.mark.asyncio
async def test_delete_soft(client):
    with _plus_on() as pb:
        pb.can_use_stacks.return_value = True
        pb.requires_approval.return_value = None
        pb.on_stack_deleted_cancel_approvals.return_value = 0
        r = await client.post("/api/stacks", json={"yaml_text": _YAML}, headers=_OP_H)
        sid = r.json()["id"]
        r2 = await client.delete(f"/api/stacks/{sid}", headers=_OP_H)
        assert r2.status_code == 204
        r3 = await client.get("/api/stacks", headers=_OP_H)
        assert all(s["id"] != sid for s in r3.json())


@pytest.mark.asyncio
async def test_versions_and_diff(client):
    with _plus_on() as pb:
        pb.can_use_stacks.return_value = True
        pb.requires_approval.return_value = None
        r = await client.post("/api/stacks", json={"yaml_text": _YAML}, headers=_OP_H)
        sid = r.json()["id"]
        etag = r.json()["current_etag"]
        new_yaml = _YAML.replace("count: 2", "count: 1")
        await client.put(
            f"/api/stacks/{sid}", json={"yaml_text": new_yaml, "expected_etag": etag}, headers=_OP_H
        )
        rv = await client.get(f"/api/stacks/{sid}/versions", headers=_OP_H)
        assert rv.status_code == 200 and len(rv.json()) == 1
        rd = await client.get(f"/api/stacks/{sid}/diff?from=v1&to=current", headers=_OP_H)
        assert rd.status_code == 200
        assert any(e["change"] != "unchanged" for e in rd.json()["diff"])


@pytest.mark.asyncio
async def test_restore_version_endpoint(client):
    with _plus_on() as pb:
        pb.can_use_stacks.return_value = True
        pb.requires_approval.return_value = None
        r = await client.post("/api/stacks", json={"yaml_text": _YAML}, headers=_OP_H)
        sid = r.json()["id"]
        etag = r.json()["current_etag"]
        new_yaml = _YAML.replace("count: 2", "count: 1")
        await client.put(
            f"/api/stacks/{sid}", json={"yaml_text": new_yaml, "expected_etag": etag}, headers=_OP_H
        )
        rr = await client.post(
            f"/api/stacks/{sid}/restore-version", json={"version_number": 1}, headers=_OP_H
        )
    assert rr.status_code == 200
    assert rr.json()["resource_count"] == 2     # v1 had count:2


@pytest.mark.asyncio
async def test_restore_version_etag_conflict_409(client):
    """BUG-76-2: Restore mit veraltetem expected_etag → 409 (Edge 9)."""
    with _plus_on() as pb:
        pb.can_use_stacks.return_value = True
        pb.requires_approval.return_value = None
        r = await client.post("/api/stacks", json={"yaml_text": _YAML}, headers=_OP_H)
        sid = r.json()["id"]
        etag = r.json()["current_etag"]
        new_yaml = _YAML.replace("count: 2", "count: 1")
        # Edit verschiebt den ETag weiter
        await client.put(
            f"/api/stacks/{sid}", json={"yaml_text": new_yaml, "expected_etag": etag}, headers=_OP_H
        )
        # Restore mit dem alten (jetzt veralteten) ETag → 409
        rr = await client.post(
            f"/api/stacks/{sid}/restore-version",
            json={"version_number": 1, "expected_etag": etag},
            headers=_OP_H,
        )
    assert rr.status_code == 409
    assert "current_etag" in rr.json()


@pytest.mark.asyncio
async def test_restore_version_etag_ok(client):
    """BUG-76-2: Restore mit korrektem aktuellem expected_etag → 200."""
    with _plus_on() as pb:
        pb.can_use_stacks.return_value = True
        pb.requires_approval.return_value = None
        r = await client.post("/api/stacks", json={"yaml_text": _YAML}, headers=_OP_H)
        sid = r.json()["id"]
        etag = r.json()["current_etag"]
        new_yaml = _YAML.replace("count: 2", "count: 1")
        ru = await client.put(
            f"/api/stacks/{sid}", json={"yaml_text": new_yaml, "expected_etag": etag}, headers=_OP_H
        )
        current_etag = ru.json()["current_etag"]
        rr = await client.post(
            f"/api/stacks/{sid}/restore-version",
            json={"version_number": 1, "expected_etag": current_etag},
            headers=_OP_H,
        )
    assert rr.status_code == 200
    assert rr.json()["resource_count"] == 2


@pytest.mark.asyncio
async def test_orphans_requires_admin(client):
    with _plus_on() as pb:
        pb.can_use_stacks.return_value = True
        r = await client.get("/api/stacks/orphans", headers=_OP_H)
    assert r.status_code == 403
