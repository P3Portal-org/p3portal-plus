# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""QA: verify a NON-owner operator cannot access another operator's stack (AC-RBAC-2)."""
import pytest, pytest_asyncio
from unittest.mock import patch
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from backend.core.security import create_access_token
from backend.db.database import get_db, get_sync_engine, init_db
from backend.plus.stacks import models as m
from backend.plus.stacks.router import router

pytestmark = pytest.mark.plus_only
app = FastAPI(); app.include_router(router)

ALICE = {"Authorization": f"Bearer {create_access_token('alice', auth_type='local', role='operator', portal_permissions=[])}"}
BOB   = {"Authorization": f"Bearer {create_access_token('bob',   auth_type='local', role='operator', portal_permissions=[])}"}
YAML = "name: secret\nversion: '1.0.0'\nresources:\n  - {type: vm, name: x, node: pve, template: t}\n"

@pytest.fixture(autouse=True)
def _dd(tmp_path, monkeypatch):
    from backend.core.config import settings
    monkeypatch.setattr(settings, "data_dir", str(tmp_path), raising=False)

@pytest_asyncio.fixture
async def client():
    await init_db()
    eng = get_sync_engine()
    for tb in (m.stacks, m.stack_resources, m.stack_versions): tb.create(eng, checkfirst=True)
    async with get_db() as db:
        for uid, u in ((2,'alice'),(3,'bob')):
            try:
                await db.execute(text("INSERT INTO local_users (id,username,password_hash,role,active,created_at) VALUES (:i,:u,'x','operator',1,'2026-01-01T00:00:00')"), {"i":uid,"u":u})
            except Exception: pass
        await db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        yield ac

@pytest.mark.asyncio
async def test_bob_cannot_read_or_mutate_alice_stack(client):
    with patch("backend.plus.stacks.router.plus_behavior") as pb:
        pb.can_use_stacks.return_value = True
        pb.requires_approval.return_value = None
        pb.on_stack_deleted_cancel_approvals.return_value = 0
        r = await client.post("/api/stacks", json={"yaml_text": YAML}, headers=ALICE)
        sid = r.json()["id"]; etag = r.json()["current_etag"]
        # bob: GET, PUT, DELETE, versions, diff, preview → all 403
        assert (await client.get(f"/api/stacks/{sid}", headers=BOB)).status_code == 403
        assert (await client.put(f"/api/stacks/{sid}", json={"yaml_text":YAML,"expected_etag":etag}, headers=BOB)).status_code == 403
        assert (await client.delete(f"/api/stacks/{sid}", headers=BOB)).status_code == 403
        assert (await client.get(f"/api/stacks/{sid}/versions", headers=BOB)).status_code == 403
        # bob list should NOT contain alice's stack
        bl = await client.get("/api/stacks", headers=BOB)
        assert all(s["id"] != sid for s in bl.json())
