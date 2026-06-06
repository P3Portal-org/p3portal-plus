# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-76 Phase 2b: /api/stacks deploy router (plan/deploy/destroy/drift/...)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from backend.core.plus_protocol import ApprovalDecision
from backend.core.security import create_access_token
from backend.db.database import get_db, get_sync_engine, init_db
from backend.plus.stacks import deploy_service as ds
from backend.plus.stacks import models as m
from backend.plus.stacks.router import router
from backend.plus.stacks.schemas import PlanResponse, PlanSummary

pytestmark = pytest.mark.plus_only

app = FastAPI()
app.include_router(router)

_ADMIN_H = {"Authorization": f"Bearer {create_access_token('admin', auth_type='local', role='admin', portal_permissions=[])}"}
_ALICE_H = {"Authorization": f"Bearer {create_access_token('alice', auth_type='local', role='operator', portal_permissions=[])}"}


@pytest.fixture(autouse=True)
def patch_data_dir(tmp_path, monkeypatch):
    from backend.core.config import settings
    monkeypatch.setattr(settings, "data_dir", str(tmp_path), raising=False)


@pytest_asyncio.fixture
async def client():
    await init_db()
    eng = get_sync_engine()
    if eng is not None:
        m.plus_metadata.create_all(eng, checkfirst=True)
    async with get_db() as db:
        for uid, uname, role in ((1, "admin", "admin"), (2, "alice", "operator")):
            await db.execute(
                text(
                    "INSERT INTO local_users (id, username, password_hash, role, active, created_at) "
                    "VALUES (:id, :u, 'x', :r, 1, '2026-01-01T00:00:00')"
                ),
                {"id": uid, "u": uname, "r": role},
            )
        # stack owned by alice (id=2)
        await db.execute(
            text(
                "INSERT INTO stacks (id, name, yaml_text, version, status, source_kind, "
                "owner_user_id, current_etag, created_at, updated_at) "
                "VALUES (1, 'web', 'name: web', '1.0.0', 'active', 'structured', "
                "2, 'etag1', '2026-01-01T00:00:00', '2026-01-01T00:00:00')"
            )
        )
        await db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


def _plus_on():
    return patch("backend.plus.stacks.router.plus_behavior")


# ── Core-mode 404 on all 6 new EPs ────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", [
    ("post", "/api/stacks/1/plan"),
    ("post", "/api/stacks/1/deploy"),
    ("post", "/api/stacks/1/destroy"),
    ("get", "/api/stacks/1/drift"),
    ("get", "/api/stacks/1/deployments"),
    ("get", "/api/stacks/1/resources/live"),
])
async def test_core_mode_404(client, method, path):
    with _plus_on() as pb:
        pb.can_use_stacks.return_value = False
        fn = getattr(client, method)
        kwargs = {"headers": _ADMIN_H}
        if method == "post":
            kwargs["json"] = {"plan_token": "x"}
        r = await fn(path, **kwargs)
    assert r.status_code == 404


# ── plan ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_plan_ok(client):
    fake = PlanResponse(plan_token="tok123", operation="apply",
                        summary=PlanSummary(create=2, resources=[]))
    with _plus_on() as pb, patch.object(ds, "prepare_plan", AsyncMock(return_value=fake)):
        pb.can_use_stacks.return_value = True
        r = await client.post("/api/stacks/1/plan", headers=_ADMIN_H)
    assert r.status_code == 200
    assert r.json()["plan_token"] == "tok123"
    assert r.json()["summary"]["create"] == 2


@pytest.mark.asyncio
async def test_plan_invalid_operation_422(client):
    with _plus_on() as pb:
        pb.can_use_stacks.return_value = True
        r = await client.post("/api/stacks/1/plan?operation=bogus", headers=_ADMIN_H)
    assert r.status_code == 422


# ── deploy happy + approval-202 + 403 ─────────────────────────────────────────

def _patch_deploy_chain(summary=None):
    """Patch the deploy gate chain so only the endpoint logic is exercised."""
    summary = summary or PlanSummary(create=2)
    return [
        patch.object(ds, "_spec_of", AsyncMock(return_value=object())),
        patch.object(ds, "resolve_target_node", AsyncMock(return_value=object())),
        patch.object(ds, "assert_deploy_allowed", AsyncMock()),
        patch.object(ds, "consume_plan_token", lambda *a, **k: {"summary": summary}),
        patch.object(ds, "start_stack_job", AsyncMock(return_value={"job_id": "j1", "deployment_id": 7})),
    ]


@pytest.mark.asyncio
async def test_deploy_happy(client):
    patches = _patch_deploy_chain()
    for p in patches:
        p.start()
    try:
        with _plus_on() as pb:
            pb.can_use_stacks.return_value = True
            pb.requires_approval = AsyncMock(return_value=None)
            r = await client.post("/api/stacks/1/deploy", json={"plan_token": "tok"}, headers=_ADMIN_H)
    finally:
        for p in patches:
            p.stop()
    assert r.status_code == 200
    assert r.json()["job_id"] == "j1"
    assert r.json()["operation"] == "apply"


@pytest.mark.asyncio
async def test_deploy_approval_202(client):
    from datetime import datetime, timezone
    decision = ApprovalDecision(
        approval_id="appr_1", action_type="stack_deploy", action_target="1",
        expires_at=datetime.now(timezone.utc), poll_url="/api/approvals/appr_1",
    )
    patches = _patch_deploy_chain()
    for p in patches:
        p.start()
    try:
        with _plus_on() as pb:
            pb.can_use_stacks.return_value = True
            pb.requires_approval = AsyncMock(return_value=decision)
            r = await client.post("/api/stacks/1/deploy", json={"plan_token": "tok"}, headers=_ALICE_H)
    finally:
        for p in patches:
            p.stop()
    assert r.status_code == 202
    assert r.json()["status"] == "pending_approval"
    assert r.json()["approval_id"] == "appr_1"


@pytest.mark.asyncio
async def test_deploy_rbac_403(client):
    from fastapi import HTTPException
    patches = [
        patch.object(ds, "_spec_of", AsyncMock(return_value=object())),
        patch.object(ds, "resolve_target_node", AsyncMock(return_value=object())),
        patch.object(ds, "assert_deploy_allowed",
                     AsyncMock(side_effect=HTTPException(status_code=403, detail="stack_deploy_forbidden"))),
    ]
    for p in patches:
        p.start()
    try:
        with _plus_on() as pb:
            pb.can_use_stacks.return_value = True
            r = await client.post("/api/stacks/1/deploy", json={"plan_token": "tok"}, headers=_ADMIN_H)
    finally:
        for p in patches:
            p.stop()
    assert r.status_code == 403


# ── deployments + live resources + drift (read) ───────────────────────────────

@pytest.mark.asyncio
async def test_deployments_and_live(client):
    # seed a deployment + a resource
    async with get_db() as db:
        await db.execute(text(
            "INSERT INTO jobs (id, type, playbook, status, created_at, username) "
            "VALUES ('jX', 'stack_apply', 'stack:web', 'success', '2026-01-01', 'alice')"
        ))
        await db.execute(text(
            "INSERT INTO nodes (id, name, url, proxmox_node, created_at) "
            "VALUES (1, 'pve', 'https://pve:8006', 'pve', '2026-01-01')"
        ))
        await db.execute(text(
            "INSERT INTO stack_deployments (id, stack_id, operation, status, job_id, "
            "plan_summary_json, triggered_by_user_id, started_at) "
            "VALUES (1, 1, 'apply', 'success', 'jX', '{\"create\": 2}', 2, '2026-01-02')"
        ))
        await db.execute(text(
            "INSERT INTO stack_deployed_resources (stack_id, deployment_id, resource_name, "
            "portal_node_id, node, vmid, kind, created_at) "
            "VALUES (1, 1, 'web-1', 1, 'pve', 101, 'vm', '2026-01-02')"
        ))
        await db.commit()

    with _plus_on() as pb:
        pb.can_use_stacks.return_value = True
        rd = await client.get("/api/stacks/1/deployments", headers=_ADMIN_H)
        rl = await client.get("/api/stacks/1/resources/live", headers=_ADMIN_H)
    assert rd.status_code == 200
    assert rd.json()[0]["status"] == "success"
    assert rd.json()[0]["plan_summary"]["create"] == 2
    assert rl.status_code == 200
    assert rl.json()[0]["vmid"] == 101


@pytest.mark.asyncio
async def test_drift_calls_service(client):
    from backend.plus.stacks.schemas import DriftReport
    with _plus_on() as pb, patch.object(ds, "run_drift",
                                        AsyncMock(return_value=DriftReport(drift_state="in_sync"))):
        pb.can_use_stacks.return_value = True
        r = await client.get("/api/stacks/1/drift", headers=_ADMIN_H)
    assert r.status_code == 200
    assert r.json()["drift_state"] == "in_sync"
