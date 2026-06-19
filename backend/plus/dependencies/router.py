# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-96: FastAPI-Router für VM-Abhängigkeiten.

Prefix /api/dependencies.
Plus-Gate: 404 für Core-/unlizenzierte Plus-Instanzen (AC-RBAC-2).
Anzeigen (GET) erfordert nur Login + RBAC-Sichtbarkeit; Verwalten (POST/PATCH/
DELETE) erfordert die delegierbare Plus-Permission ``manage_dependencies``.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.core.deps import CurrentUser, get_current_user, require_admin_or
from backend.core.plus_protocol import plus_behavior

from . import service
from .schemas import (
    DependencyIn,
    DependencyLabelIn,
    DependencyOut,
    VmDependenciesResponse,
)

router = APIRouter(prefix="/api/dependencies", tags=["dependencies"])

_require_manage = require_admin_or("manage_dependencies")


def _check_plus() -> None:
    if not plus_behavior.can_use_dependencies():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")


# ── Static routes before path-param routes ───────────────────────────────────

@router.get("/orphans", response_model=list[DependencyOut])
async def list_orphan_dependencies(
    current_user: CurrentUser = Depends(_require_manage),
) -> list[DependencyOut]:
    _check_plus()
    return await service.list_orphans()


@router.delete("/orphans")
async def delete_orphan_dependencies(
    ids: list[int] = Query(default_factory=list, description="Leere Liste = alle verwaisten löschen"),
    current_user: CurrentUser = Depends(_require_manage),
) -> dict:
    _check_plus()
    count = await service.delete_orphans(ids or None, current_user.username)
    return {"deleted": count}


# ── VM-Detail: beide Richtungen ───────────────────────────────────────────────

@router.get("", response_model=VmDependenciesResponse)
async def get_vm_dependencies(
    vmid: int = Query(...),
    node_id: int | None = Query(default=None, description="Portal-DB-Node-ID der VM"),
    node: str | None = Query(default=None, description="Proxmox-Node-Name (Fallback)"),
    current_user: CurrentUser = Depends(get_current_user),
) -> VmDependenciesResponse:
    _check_plus()
    pnid = node_id
    if pnid is None and node:
        from backend.services.nodes_service import get_node_for_proxmox_name
        node_row = await get_node_for_proxmox_name(node)
        if node_row is not None:
            pnid = node_row.id
    if pnid is None:
        raise HTTPException(status_code=422, detail="node_required")
    return await service.get_for_vm(current_user, pnid, vmid)


# ── Verwalten ─────────────────────────────────────────────────────────────────

@router.post("", response_model=DependencyOut, status_code=status.HTTP_201_CREATED)
async def create_dependency(
    body: DependencyIn,
    current_user: CurrentUser = Depends(_require_manage),
) -> DependencyOut:
    _check_plus()
    return await service.create_dependency(current_user, body, current_user.username)


@router.patch("/{dep_id}", response_model=DependencyOut)
async def update_dependency_label(
    dep_id: int,
    body: DependencyLabelIn,
    current_user: CurrentUser = Depends(_require_manage),
) -> DependencyOut:
    _check_plus()
    return await service.update_label(dep_id, body.dep_label)


@router.delete("/{dep_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dependency(
    dep_id: int,
    current_user: CurrentUser = Depends(_require_manage),
):
    _check_plus()
    await service.delete_dependency(dep_id, current_user.username)
