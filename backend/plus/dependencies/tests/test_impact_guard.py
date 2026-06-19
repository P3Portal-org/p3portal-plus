# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-96: tests for the vms.py ``_dependency_impact`` warn-then-confirm guard."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

import backend.core.plus_protocol as pp
import backend.services.nodes_service as ns
from backend.routers import vms

pytestmark = pytest.mark.plus_only


def _patch_node(monkeypatch, node_id=1):
    monkeypatch.setattr(
        ns, "get_node_for_proxmox_name",
        AsyncMock(return_value=SimpleNamespace(id=node_id)),
    )


def _patch_dependents(monkeypatch, dependents):
    monkeypatch.setattr(
        pp.plus_behavior, "get_dependents_of_vm",
        AsyncMock(return_value=dependents),
    )


@pytest.mark.asyncio
async def test_confirm_true_skips_guard(monkeypatch):
    # confirm=True must not even look up the node or call the hook.
    called = AsyncMock()
    monkeypatch.setattr(ns, "get_node_for_proxmox_name", called)
    await vms._dependency_impact("pve1", 100, True, "stop", "alice", "local")
    called.assert_not_awaited()


@pytest.mark.asyncio
async def test_node_not_configured_no_raise(monkeypatch):
    monkeypatch.setattr(ns, "get_node_for_proxmox_name", AsyncMock(return_value=None))
    # must not raise even when dependents would exist (no node → no lookup)
    await vms._dependency_impact("pve1", 100, False, "stop", "alice", "local")


@pytest.mark.asyncio
async def test_no_dependents_no_raise(monkeypatch):
    _patch_node(monkeypatch)
    _patch_dependents(monkeypatch, [])
    await vms._dependency_impact("pve1", 100, False, "reboot", "alice", "local")


@pytest.mark.asyncio
async def test_dependents_raise_409_with_body(monkeypatch):
    _patch_node(monkeypatch)
    monkeypatch.setattr(vms, "write_audit_log", AsyncMock())
    deps = [
        {"vmid": 200, "name": "svc-a", "node": "pveA", "installation": "prod",
         "dep_label": "needs db"},
        {"vmid": 201, "name": "svc-b", "node": "pveA", "installation": "prod",
         "dep_label": None},
    ]
    _patch_dependents(monkeypatch, deps)
    with pytest.raises(HTTPException) as exc:
        await vms._dependency_impact("pve1", 100, False, "delete", "alice", "local")
    assert exc.value.status_code == 409
    body = exc.value.detail
    assert body["error"] == "dependency_impact"
    assert body["action"] == "delete"
    assert body["count"] == 2
    assert body["dependents"] == deps


@pytest.mark.asyncio
async def test_hook_exception_swallowed_no_raise(monkeypatch):
    _patch_node(monkeypatch)
    monkeypatch.setattr(
        pp.plus_behavior, "get_dependents_of_vm",
        AsyncMock(side_effect=RuntimeError("boom")),
    )
    # a failing hook must never block the action (best-effort guard)
    await vms._dependency_impact("pve1", 100, False, "stop", "alice", "local")
