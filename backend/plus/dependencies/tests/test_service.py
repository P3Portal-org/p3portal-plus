# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-96: service tests — CRUD validation, RBAC filter, impact lookup, topology."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from backend.core.deps import CurrentUser
from backend.plus.dependencies import service
from backend.plus.dependencies.schemas import DependencyIn
from backend.plus.dependencies.tests._helpers import FakeResult, make_get_db, vm

pytestmark = pytest.mark.plus_only


def _user(uid=1, role="admin"):
    return CurrentUser(username="alice", auth_type="local", role=role, user_id=uid)


def _patch_visible(monkeypatch, vms):
    """Patch fetch_visible_vm_resources (lazy-imported from routers.cluster)."""
    import backend.routers.cluster as cluster_mod
    monkeypatch.setattr(
        cluster_mod, "fetch_visible_vm_resources", AsyncMock(return_value=vms)
    )


def _patch_nodes(monkeypatch, names):
    """Patch list_nodes (lazy-imported from services.nodes_service)."""
    import backend.services.nodes_service as ns
    rows = [SimpleNamespace(id=nid, name=nm) for nid, nm in names.items()]
    monkeypatch.setattr(ns, "list_nodes", AsyncMock(return_value=rows))


def _silence_audit(monkeypatch):
    monkeypatch.setattr(service, "write_audit_log", AsyncMock())


# ── create validation ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_self_dependency_422(monkeypatch):
    _silence_audit(monkeypatch)
    body = DependencyIn(source_node_id=1, source_vmid=100, target_node_id=1, target_vmid=100)
    with pytest.raises(HTTPException) as exc:
        await service.create_dependency(_user(), body, "alice")
    assert exc.value.status_code == 422
    assert exc.value.detail == "self_dependency_not_allowed"


@pytest.mark.asyncio
async def test_create_source_not_visible_422(monkeypatch):
    _silence_audit(monkeypatch)
    _patch_visible(monkeypatch, [vm(200, 1)])  # only target visible
    body = DependencyIn(source_node_id=1, source_vmid=100, target_node_id=1, target_vmid=200)
    with pytest.raises(HTTPException) as exc:
        await service.create_dependency(_user(), body, "alice")
    assert exc.value.status_code == 422
    assert exc.value.detail == "source_vm_not_visible"


@pytest.mark.asyncio
async def test_create_target_not_visible_422(monkeypatch):
    _silence_audit(monkeypatch)
    _patch_visible(monkeypatch, [vm(100, 1)])  # only source visible
    body = DependencyIn(source_node_id=1, source_vmid=100, target_node_id=1, target_vmid=200)
    with pytest.raises(HTTPException) as exc:
        await service.create_dependency(_user(), body, "alice")
    assert exc.value.status_code == 422
    assert exc.value.detail == "target_vm_not_visible"


@pytest.mark.asyncio
async def test_create_duplicate_409(monkeypatch):
    _silence_audit(monkeypatch)
    _patch_visible(monkeypatch, [vm(100, 1), vm(200, 1)])
    get_db, _ = make_get_db([FakeResult(rows=[{"id": 5}])])  # dup-check returns a row
    monkeypatch.setattr(service, "get_db", get_db)
    body = DependencyIn(source_node_id=1, source_vmid=100, target_node_id=1, target_vmid=200)
    with pytest.raises(HTTPException) as exc:
        await service.create_dependency(_user(), body, "alice")
    assert exc.value.status_code == 409
    assert exc.value.detail == "dependency_exists"


@pytest.mark.asyncio
async def test_create_success_cross_installation(monkeypatch):
    _silence_audit(monkeypatch)
    # source on installation 1, target on installation 2 (cross-install, AC-MODEL-4)
    _patch_visible(monkeypatch, [
        vm(100, 1, node="pveA", name="svc", inst="prod"),
        vm(200, 2, node="pveB", name="db", inst="dr"),
    ])
    _patch_nodes(monkeypatch, {1: "prod", 2: "dr"})
    inserted = {
        "id": 7, "source_node_id": 1, "source_vmid": 100, "source_node": "pveA",
        "source_name": "svc", "target_node_id": 2, "target_vmid": 200,
        "target_node": "pveB", "target_name": "db", "dep_label": "needs postgres",
        "created_at": "2026-06-18T00:00:00+00:00", "created_by": 1,
        "stale": 0, "stale_at": None,
    }
    get_db, session = make_get_db([
        FakeResult(rows=[]),         # dup-check: no row
        FakeResult(),                # INSERT (ignored)
        FakeResult(rows=[inserted]),  # SELECT * after insert
    ])
    monkeypatch.setattr(service, "get_db", get_db)
    body = DependencyIn(
        source_node_id=1, source_vmid=100, target_node_id=2, target_vmid=200,
        dep_label="needs postgres",
    )
    out = await service.create_dependency(_user(), body, "alice")
    assert out.id == 7
    assert out.source_installation == "prod"
    assert out.target_installation == "dr"
    assert out.stale is False
    session.commit.assert_awaited()


# ── get_for_vm RBAC filter ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_for_vm_vm_not_visible_returns_empty(monkeypatch):
    _patch_visible(monkeypatch, [])  # nothing visible
    res = await service.get_for_vm(_user(role="viewer"), 1, 100)
    assert res.depends_on == []
    assert res.dependents == []


@pytest.mark.asyncio
async def test_get_for_vm_filters_invisible_other_endpoint(monkeypatch):
    # The VM (1,100) is visible, dependent (1,200) is visible, but a third
    # endpoint (1,300) is NOT visible → that edge must be hidden (AC-VIEW-3).
    _patch_visible(monkeypatch, [vm(100, 1), vm(200, 1)])
    _patch_nodes(monkeypatch, {1: "prod"})
    rows = [
        # (1,200) depends on (1,100) → dependent, visible source → shown
        {"id": 1, "source_node_id": 1, "source_vmid": 200, "source_node": "pve1",
         "source_name": "dep-ok", "target_node_id": 1, "target_vmid": 100,
         "target_node": "pve1", "target_name": "db", "dep_label": None,
         "created_at": "t", "created_by": 1, "stale": 0, "stale_at": None},
        # (1,300) depends on (1,100) → dependent, source NOT visible → hidden
        {"id": 2, "source_node_id": 1, "source_vmid": 300, "source_node": "pve1",
         "source_name": "secret", "target_node_id": 1, "target_vmid": 100,
         "target_node": "pve1", "target_name": "db", "dep_label": None,
         "created_at": "t", "created_by": 1, "stale": 0, "stale_at": None},
    ]
    get_db, _ = make_get_db([FakeResult(rows=rows)])
    monkeypatch.setattr(service, "get_db", get_db)
    res = await service.get_for_vm(_user(), 1, 100)
    dependent_vmids = {d.source_vmid for d in res.dependents}
    assert dependent_vmids == {200}  # 300 hidden (not visible)
    assert res.depends_on == []


# ── impact lookup (the vms.py hook) ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_dependents_shape(monkeypatch):
    rows = [
        {"vmid": 200, "name": "svc-a", "node": "pveA", "dep_label": "db",
         "installation": "prod"},
        {"vmid": 201, "name": "svc-b", "node": "pveA", "dep_label": None,
         "installation": "prod"},
    ]
    get_db, _ = make_get_db([FakeResult(rows=rows)])
    monkeypatch.setattr(service, "get_db", get_db)
    deps = await service.get_dependents(1, 100)
    assert len(deps) == 2
    assert deps[0] == {
        "vmid": 200, "name": "svc-a", "node": "pveA",
        "installation": "prod", "dep_label": "db",
    }


# ── topology graph ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_build_topology_only_visible_edges(monkeypatch):
    _patch_visible(monkeypatch, [vm(100, 1, vm_type="qemu"), vm(200, 1, vm_type="lxc")])
    _patch_nodes(monkeypatch, {1: "prod"})
    rows = [
        # both endpoints visible → emitted
        {"id": 1, "source_node_id": 1, "source_vmid": 200, "source_node": "pve1",
         "source_name": "x", "target_node_id": 1, "target_vmid": 100,
         "target_node": "pve1", "target_name": "y", "dep_label": "needs",
         "created_at": "t", "created_by": 1, "stale": 0, "stale_at": None},
        # target (1,999) not visible → skipped
        {"id": 2, "source_node_id": 1, "source_vmid": 200, "source_node": "pve1",
         "source_name": "x", "target_node_id": 1, "target_vmid": 999,
         "target_node": "pve1", "target_name": "z", "dep_label": None,
         "created_at": "t", "created_by": 1, "stale": 0, "stale_at": None},
    ]
    get_db, _ = make_get_db([FakeResult(rows=rows)])
    monkeypatch.setattr(service, "get_db", get_db)
    res = await service.build_dependency_topology(_user())
    assert len(res.guests) == 2
    assert len(res.edges) == 1
    edge = res.edges[0]
    assert edge.source_id == "inst1-lxc-200"   # source is lxc
    assert edge.target_id == "inst1-vm-100"    # target is qemu
    assert edge.dep_label == "needs"


# ── update / delete / orphans ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_label_404(monkeypatch):
    get_db, _ = make_get_db([FakeResult(rowcount=0)])
    monkeypatch.setattr(service, "get_db", get_db)
    with pytest.raises(HTTPException) as exc:
        await service.update_label(42, "x")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_404(monkeypatch):
    _silence_audit(monkeypatch)
    get_db, _ = make_get_db([FakeResult(rowcount=0)])
    monkeypatch.setattr(service, "get_db", get_db)
    with pytest.raises(HTTPException) as exc:
        await service.delete_dependency(42, "alice")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_orphans_all(monkeypatch):
    _silence_audit(monkeypatch)
    get_db, _ = make_get_db([FakeResult(rowcount=3)])
    monkeypatch.setattr(service, "get_db", get_db)
    count = await service.delete_orphans(None, "alice")
    assert count == 3


@pytest.mark.asyncio
async def test_delete_orphans_by_ids(monkeypatch):
    _silence_audit(monkeypatch)
    get_db, session = make_get_db([FakeResult(rowcount=2)])
    monkeypatch.setattr(service, "get_db", get_db)
    count = await service.delete_orphans([1, 2], "alice")
    assert count == 2
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_list_orphans(monkeypatch):
    _patch_nodes(monkeypatch, {1: "prod"})
    rows = [
        {"id": 9, "source_node_id": 1, "source_vmid": 100, "source_node": "pve1",
         "source_name": "gone", "target_node_id": 1, "target_vmid": 200,
         "target_node": "pve1", "target_name": "db", "dep_label": None,
         "created_at": "t", "created_by": 1, "stale": 1, "stale_at": "t2"},
    ]
    get_db, _ = make_get_db([FakeResult(rows=rows)])
    monkeypatch.setattr(service, "get_db", get_db)
    out = await service.list_orphans()
    assert len(out) == 1
    assert out[0].stale is True
    assert out[0].source_installation == "prod"
