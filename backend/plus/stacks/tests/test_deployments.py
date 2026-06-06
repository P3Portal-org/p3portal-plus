# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-76 Phase 2b: deployments CRUD + state-sync + get_stack_for_vm + derive."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text

from backend.db.database import get_db, get_sync_engine, init_db
from backend.plus.stacks import deployments as dep
from backend.plus.stacks import models as m

pytestmark = pytest.mark.plus_only


@pytest_asyncio.fixture
async def deploy_db():
    await init_db()
    eng = get_sync_engine()
    if eng is not None:
        m.plus_metadata.create_all(eng, checkfirst=True)
    # seed FK parents (user + jobs) + one stack to attach deployments to
    async with get_db() as db:
        await db.execute(
            text(
                "INSERT INTO local_users (id, username, password_hash, role, active, created_at) "
                "VALUES (5, 'alice', 'x', 'operator', 1, '2026-01-01T00:00:00')"
            )
        )
        await db.execute(
            text(
                "INSERT INTO nodes (id, name, url, proxmox_node, created_at) "
                "VALUES (3, 'pve', 'https://pve:8006', 'pve', '2026-01-01T00:00:00')"
            )
        )
        for jid in [f"job-{i}" for i in range(1, 10)]:
            await db.execute(
                text(
                    "INSERT INTO jobs (id, type, playbook, status, created_at, username) "
                    "VALUES (:id, 'stack_apply', 'stack:web', 'running', '2026-01-01T00:00:00', 'alice')"
                ),
                {"id": jid},
            )
        await db.execute(
            text(
                "INSERT INTO stacks (id, name, yaml_text, version, status, source_kind, "
                "current_etag, created_at, updated_at) "
                "VALUES (1, 'web', 'name: web', '1.0.0', 'active', 'structured', "
                "'etag1', '2026-01-01T00:00:00', '2026-01-01T00:00:00')"
            )
        )
        await db.commit()
    yield


async def _stack_row(stack_id=1):
    async with get_db() as db:
        r = await db.execute(text("SELECT * FROM stacks WHERE id = :id"), {"id": stack_id})
        return r.mappings().fetchone()


@pytest.mark.asyncio
async def test_create_finish_list_deployment(deploy_db):
    did = await dep.create_deployment(1, "apply", "job-1", '{"create": 2}', 5)
    assert did > 0
    rows = await dep.list_deployments(1)
    assert rows[0]["status"] == "running"
    await dep.finish_deployment(did, "success")
    rows = await dep.list_deployments(1)
    assert rows[0]["status"] == "success" and rows[0]["finished_at"]


@pytest.mark.asyncio
async def test_sync_and_get_stack_for_vm(deploy_db):
    did = await dep.create_deployment(1, "apply", "job-2", None, 5)
    await dep.sync_deployed_resources(1, did, portal_node_id=3, resources=[
        {"resource_name": "web-1", "node": "pve", "vmid": 101},
        {"resource_name": "web-2", "node": "pve", "vmid": 102},
    ])
    # lookup hits
    hit = await dep.get_stack_for_vm(3, 101)
    assert hit == {"stack_id": 1, "stack_name": "web"}
    # foreign vm / other node → None (AC-2B-MUT, isolation)
    assert await dep.get_stack_for_vm(3, 999) is None
    assert await dep.get_stack_for_vm(99, 101) is None


@pytest.mark.asyncio
async def test_clear_deployed_resources(deploy_db):
    did = await dep.create_deployment(1, "destroy", "job-3", None, 5)
    await dep.sync_deployed_resources(1, did, 3, [{"resource_name": "web-1", "node": "pve", "vmid": 101}])
    await dep.clear_deployed_resources(1)
    assert await dep.list_deployed_resources(1) == []
    assert await dep.get_stack_for_vm(3, 101) is None


@pytest.mark.asyncio
async def test_soft_deleted_stack_stops_blocking(deploy_db):
    did = await dep.create_deployment(1, "apply", "job-4", None, 5)
    await dep.sync_deployed_resources(1, did, 3, [{"resource_name": "web-1", "node": "pve", "vmid": 101}])
    async with get_db() as db:
        await db.execute(text("UPDATE stacks SET deleted_at = '2026-02-01' WHERE id = 1"))
        await db.commit()
    assert await dep.get_stack_for_vm(3, 101) is None


# ── derive_deployment_state ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_derive_not_deployed(deploy_db):
    row = await _stack_row()
    assert await dep.derive_deployment_state(row) == "not_deployed"


@pytest.mark.asyncio
async def test_derive_deploying(deploy_db):
    await dep.create_deployment(1, "apply", "job-5", None, 5)  # running
    row = await _stack_row()
    assert await dep.derive_deployment_state(row) == "deploying"


@pytest.mark.asyncio
async def test_derive_deployed_and_drift(deploy_db):
    did = await dep.create_deployment(1, "apply", "job-6", None, 5)
    await dep.finish_deployment(did, "success")
    await dep.sync_deployed_resources(1, did, 3, [{"resource_name": "web-1", "node": "pve", "vmid": 101}])
    row = await _stack_row()
    assert await dep.derive_deployment_state(row) == "deployed"
    # drift flips it
    await dep.set_drift_state(1, "out_of_sync")
    row = await _stack_row()
    assert await dep.derive_deployment_state(row) == "out_of_sync"


@pytest.mark.asyncio
async def test_derive_destroyed(deploy_db):
    did = await dep.create_deployment(1, "destroy", "job-7", None, 5)
    await dep.finish_deployment(did, "success")
    row = await _stack_row()
    assert await dep.derive_deployment_state(row) == "destroyed"


@pytest.mark.asyncio
async def test_derive_partial_and_error(deploy_db):
    did = await dep.create_deployment(1, "apply", "job-8", None, 5)
    await dep.finish_deployment(did, "partial")
    row = await _stack_row()
    assert await dep.derive_deployment_state(row) == "partial"
    did2 = await dep.create_deployment(1, "apply", "job-9", None, 5)
    await dep.finish_deployment(did2, "failed")
    row = await _stack_row()
    assert await dep.derive_deployment_state(row) == "error"
