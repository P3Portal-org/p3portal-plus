# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-75: FastAPI router for the cluster-topology view.

Prefix /api/topology. Plus-gate: 404 in Core / unlicensed Plus (AC-CAP-4).
Every logged-in user may read; VMs/LXCs are RBAC-filtered server-side via the
single-source helper in routers/cluster.py (AC-RBAC-1/4). Nodes and networks are
visible to all (AC-RBAC-2). No audit events (read-only, AC-Audit).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from backend.core.deps import CurrentUser, get_current_user
from backend.core.plus_protocol import plus_behavior

from backend.plus.dependencies import service as dependencies_service
from backend.plus.dependencies.schemas import DependencyTopologyResponse

from . import service
from .schemas import ClusterTopologyResponse, NetworkTopologyResponse

router = APIRouter(prefix="/api/topology", tags=["topology"])


def _check_plus() -> None:
    if not plus_behavior.can_use_topology():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")


@router.get("/cluster", response_model=ClusterTopologyResponse)
async def get_cluster_topology(
    force: bool = False,
    current_user: CurrentUser = Depends(get_current_user),
) -> ClusterTopologyResponse:
    """Compute view: installations → nodes → guests + stats + stack list.

    Cheap (cluster-cache + bulk SELECTs, no per-VM call) → safe for the 60-s poll.
    """
    _check_plus()
    return await service.build_cluster_topology(current_user, force=force)


@router.get("/network", response_model=NetworkTopologyResponse)
async def get_network_topology(
    force: bool = False,
    current_user: CurrentUser = Depends(get_current_user),
) -> NetworkTopologyResponse:
    """Network view (lazy): bridges / SDN VNets / stack-bridges + connectivity.

    Expensive (per-VM ``get_vm_config`` for every visible guest) → only fetched
    when the user switches to the Network view.
    """
    _check_plus()
    return await service.build_network_topology(current_user, force=force)


@router.get("/dependencies", response_model=DependencyTopologyResponse)
async def get_dependency_topology(
    current_user: CurrentUser = Depends(get_current_user),
) -> DependencyTopologyResponse:
    """PROJ-96: Dependency view (lazy) — directed VM-dependency edges.

    Only edges between VMs the viewer may see (server-side RBAC, AC-VIEW-3); the
    same single-source ``fetch_visible_vm_resources`` as the other views. Plus-
    gated via ``can_use_topology`` (viewing needs the topology capability, not
    ``manage_dependencies``).
    """
    _check_plus()
    return await dependencies_service.build_dependency_topology(current_user)
