# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-75: router-level tests — Plus-gate 404 (Core), pass-through in Plus."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from backend.core.deps import CurrentUser
from backend.plus.topology import router as topo_router
from backend.plus.topology.schemas import ClusterTopologyResponse, NetworkTopologyResponse


def _user():
    return CurrentUser(username="admin", auth_type="local", role="admin", user_id=1)


def _gate(value: bool):
    return SimpleNamespace(can_use_topology=lambda: value)


@pytest.mark.asyncio
async def test_cluster_endpoint_404_in_core(monkeypatch):
    monkeypatch.setattr(topo_router, "plus_behavior", _gate(False))
    with pytest.raises(HTTPException) as exc:
        await topo_router.get_cluster_topology(force=False, current_user=_user())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_network_endpoint_404_in_core(monkeypatch):
    monkeypatch.setattr(topo_router, "plus_behavior", _gate(False))
    with pytest.raises(HTTPException) as exc:
        await topo_router.get_network_topology(force=False, current_user=_user())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_cluster_endpoint_calls_service_in_plus(monkeypatch):
    monkeypatch.setattr(topo_router, "plus_behavior", _gate(True))
    fake = ClusterTopologyResponse()
    monkeypatch.setattr(
        topo_router.service, "build_cluster_topology", AsyncMock(return_value=fake)
    )
    result = await topo_router.get_cluster_topology(force=True, current_user=_user())
    assert result is fake
    topo_router.service.build_cluster_topology.assert_awaited_once()
    _, kwargs = topo_router.service.build_cluster_topology.await_args
    assert kwargs.get("force") is True


@pytest.mark.asyncio
async def test_network_endpoint_calls_service_in_plus(monkeypatch):
    monkeypatch.setattr(topo_router, "plus_behavior", _gate(True))
    fake = NetworkTopologyResponse()
    monkeypatch.setattr(
        topo_router.service, "build_network_topology", AsyncMock(return_value=fake)
    )
    result = await topo_router.get_network_topology(force=False, current_user=_user())
    assert result is fake
    topo_router.service.build_network_topology.assert_awaited_once()
