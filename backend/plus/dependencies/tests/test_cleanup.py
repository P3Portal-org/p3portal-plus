# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-96: cleanup tests — orphan-mark on delete + on vanished refresh."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from backend.plus.dependencies import cleanup
from backend.plus.dependencies.tests._helpers import FakeResult, make_get_db

pytestmark = pytest.mark.plus_only


def _silence_audit(monkeypatch):
    monkeypatch.setattr(cleanup, "write_audit_log", AsyncMock())


@pytest.mark.asyncio
async def test_on_vm_lxc_deleted_marks_stale(monkeypatch):
    _silence_audit(monkeypatch)
    get_db, session = make_get_db([FakeResult(rowcount=2)])
    monkeypatch.setattr(cleanup, "get_db", get_db)
    count = await cleanup.on_vm_lxc_deleted(1, 100, "alice")
    assert count == 2
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_on_vm_lxc_deleted_no_edges(monkeypatch):
    audit = AsyncMock()
    monkeypatch.setattr(cleanup, "write_audit_log", audit)
    get_db, _ = make_get_db([FakeResult(rowcount=0)])
    monkeypatch.setattr(cleanup, "get_db", get_db)
    count = await cleanup.on_vm_lxc_deleted(1, 100, "alice")
    assert count == 0
    audit.assert_not_awaited()  # no audit noise when nothing changed


@pytest.mark.asyncio
async def test_vanished_marks_only_missing_endpoints(monkeypatch):
    _silence_audit(monkeypatch)
    # Edges on installation 1: vmid 100 still visible, vmid 300 vanished.
    edges = [
        {"id": 1, "source_node_id": 1, "source_vmid": 100,
         "target_node_id": 2, "target_vmid": 500},   # 100 visible → keep
        {"id": 2, "source_node_id": 1, "source_vmid": 300,
         "target_node_id": 2, "target_vmid": 500},   # 300 gone → stale
    ]
    get_db, session = make_get_db([
        FakeResult(rows=edges),   # SELECT active edges on node 1
        FakeResult(rowcount=1),   # UPDATE
    ])
    monkeypatch.setattr(cleanup, "get_db", get_db)
    still_visible = {100, 200}  # 300 not present
    count = await cleanup.on_cluster_refresh_vanished_resources(still_visible, 1)
    assert count == 1
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_vanished_nothing_to_orphan(monkeypatch):
    audit = AsyncMock()
    monkeypatch.setattr(cleanup, "write_audit_log", audit)
    edges = [
        {"id": 1, "source_node_id": 1, "source_vmid": 100,
         "target_node_id": 2, "target_vmid": 500},
    ]
    get_db, _ = make_get_db([FakeResult(rows=edges)])
    monkeypatch.setattr(cleanup, "get_db", get_db)
    count = await cleanup.on_cluster_refresh_vanished_resources({100}, 1)
    assert count == 0
    audit.assert_not_awaited()


@pytest.mark.asyncio
async def test_vanished_target_endpoint_on_this_node(monkeypatch):
    _silence_audit(monkeypatch)
    # The vanished VM is the TARGET on node 1.
    edges = [
        {"id": 5, "source_node_id": 2, "source_vmid": 900,
         "target_node_id": 1, "target_vmid": 777},
    ]
    get_db, _ = make_get_db([
        FakeResult(rows=edges),
        FakeResult(rowcount=1),
    ])
    monkeypatch.setattr(cleanup, "get_db", get_db)
    count = await cleanup.on_cluster_refresh_vanished_resources({100, 200}, 1)
    assert count == 1
