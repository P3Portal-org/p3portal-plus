# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-96: router-level tests — Plus-gate 404 (Core), pass-through in Plus."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from backend.core.deps import CurrentUser
from backend.plus.dependencies import router as dep_router
from backend.plus.dependencies.schemas import (
    DependencyIn,
    DependencyLabelIn,
    DependencyOut,
    VmDependenciesResponse,
)

pytestmark = pytest.mark.plus_only


def _user():
    return CurrentUser(username="admin", auth_type="local", role="admin", user_id=1)


def _gate(value: bool):
    return SimpleNamespace(can_use_dependencies=lambda: value)


def _sample_out(dep_id=1):
    return DependencyOut(
        id=dep_id, source_node_id=1, source_vmid=100, source_node="pve1",
        source_name="svc", target_node_id=1, target_vmid=200, target_node="pve1",
        target_name="db", dep_label=None, created_at="t", created_by=1,
        stale=False, stale_at=None,
    )


# ── 404 in Core ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_vm_dependencies_404_in_core(monkeypatch):
    monkeypatch.setattr(dep_router, "plus_behavior", _gate(False))
    with pytest.raises(HTTPException) as exc:
        await dep_router.get_vm_dependencies(vmid=100, node_id=1, node=None, current_user=_user())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_create_404_in_core(monkeypatch):
    monkeypatch.setattr(dep_router, "plus_behavior", _gate(False))
    body = DependencyIn(source_node_id=1, source_vmid=100, target_node_id=1, target_vmid=200)
    with pytest.raises(HTTPException) as exc:
        await dep_router.create_dependency(body=body, current_user=_user())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_orphans_404_in_core(monkeypatch):
    monkeypatch.setattr(dep_router, "plus_behavior", _gate(False))
    with pytest.raises(HTTPException) as exc:
        await dep_router.list_orphan_dependencies(current_user=_user())
    assert exc.value.status_code == 404


# ── pass-through in Plus ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_vm_dependencies_calls_service_in_plus(monkeypatch):
    monkeypatch.setattr(dep_router, "plus_behavior", _gate(True))
    fake = VmDependenciesResponse()
    monkeypatch.setattr(dep_router.service, "get_for_vm", AsyncMock(return_value=fake))
    result = await dep_router.get_vm_dependencies(
        vmid=100, node_id=7, node=None, current_user=_user()
    )
    assert result is fake
    _, kwargs = dep_router.service.get_for_vm.await_args
    args = dep_router.service.get_for_vm.await_args.args
    assert args[1] == 7 and args[2] == 100


@pytest.mark.asyncio
async def test_get_vm_dependencies_node_required_422(monkeypatch):
    monkeypatch.setattr(dep_router, "plus_behavior", _gate(True))
    with pytest.raises(HTTPException) as exc:
        await dep_router.get_vm_dependencies(vmid=100, node_id=None, node=None, current_user=_user())
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_get_vm_dependencies_resolves_proxmox_node(monkeypatch):
    monkeypatch.setattr(dep_router, "plus_behavior", _gate(True))
    monkeypatch.setattr(dep_router.service, "get_for_vm", AsyncMock(return_value=VmDependenciesResponse()))
    import backend.services.nodes_service as ns
    monkeypatch.setattr(ns, "get_node_for_proxmox_name", AsyncMock(return_value=SimpleNamespace(id=9)))
    await dep_router.get_vm_dependencies(vmid=100, node_id=None, node="pve1", current_user=_user())
    args = dep_router.service.get_for_vm.await_args.args
    assert args[1] == 9


@pytest.mark.asyncio
async def test_create_calls_service_in_plus(monkeypatch):
    monkeypatch.setattr(dep_router, "plus_behavior", _gate(True))
    out = _sample_out()
    monkeypatch.setattr(dep_router.service, "create_dependency", AsyncMock(return_value=out))
    body = DependencyIn(source_node_id=1, source_vmid=100, target_node_id=1, target_vmid=200)
    result = await dep_router.create_dependency(body=body, current_user=_user())
    assert result is out
    dep_router.service.create_dependency.assert_awaited_once()


@pytest.mark.asyncio
async def test_patch_calls_service(monkeypatch):
    monkeypatch.setattr(dep_router, "plus_behavior", _gate(True))
    out = _sample_out()
    monkeypatch.setattr(dep_router.service, "update_label", AsyncMock(return_value=out))
    body = DependencyLabelIn(dep_label="x")
    result = await dep_router.update_dependency_label(dep_id=1, body=body, current_user=_user())
    assert result is out


@pytest.mark.asyncio
async def test_delete_calls_service(monkeypatch):
    monkeypatch.setattr(dep_router, "plus_behavior", _gate(True))
    monkeypatch.setattr(dep_router.service, "delete_dependency", AsyncMock())
    await dep_router.delete_dependency(dep_id=3, current_user=_user())
    dep_router.service.delete_dependency.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_orphans_calls_service(monkeypatch):
    monkeypatch.setattr(dep_router, "plus_behavior", _gate(True))
    monkeypatch.setattr(dep_router.service, "delete_orphans", AsyncMock(return_value=4))
    result = await dep_router.delete_orphan_dependencies(ids=[1, 2], current_user=_user())
    assert result == {"deleted": 4}
