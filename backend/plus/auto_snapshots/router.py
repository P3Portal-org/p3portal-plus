# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-77 – FastAPI-Router (Plus-only, 404 in Core-Mode).

2 Endpoints (Sektion E):
- GET /api/auto-snapshots/runs/{run_id}/details
- GET /api/auto-snapshots/native-snapshots?node=…&vmid=…&kind=…
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.core.deps import CurrentUser, get_current_user
from backend.core.plus_protocol import plus_behavior
from backend.features.api_surface.deps import require_scope_for_upk

from . import service
from .schemas import NativeSnapshotEntry, RunDetailsResponse

router = APIRouter(prefix="/api/auto-snapshots", tags=["auto-snapshots"])


def _check_plus() -> None:
    if not plus_behavior.can_use_auto_snapshots():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")


# ─── GET /api/auto-snapshots/runs/{run_id}/details ────────────────────────


@router.get("/runs/{run_id}/details", response_model=RunDetailsResponse)
async def get_run_details(
    run_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    _scope: CurrentUser = Depends(require_scope_for_upk("auto_snapshots:read")),
):
    _check_plus()
    details = await service.get_run_details(run_id)
    if details is None:
        raise HTTPException(status_code=404, detail="run_not_found")

    # Permission: Admin oder Job-Owner
    if current_user.role != "admin":
        owner = await service.get_job_owner_username(details.job_id)
        if owner is None or owner != current_user.username:
            raise HTTPException(status_code=403, detail="forbidden")
    return details


# ─── GET /api/auto-snapshots/native-snapshots ────────────────────────────


@router.get("/native-snapshots", response_model=list[NativeSnapshotEntry])
async def list_native_snapshots(
    portal_node_id: int = Query(..., ge=1, description="Portal-Node-ID"),
    proxmox_node: str = Query(..., min_length=1, description="Proxmox-Node-Name"),
    vmid: int = Query(..., ge=1),
    kind: str = Query(..., pattern="^(qemu|lxc)$"),
    current_user: CurrentUser = Depends(get_current_user),
    _scope: CurrentUser = Depends(require_scope_for_upk("auto_snapshots:read")),
):
    """Bulk-Lookup für den PROJ-29-Snapshots-Tab (Badge ``auto``)."""
    _check_plus()
    return await service.list_native_snapshots(portal_node_id, proxmox_node, vmid, kind)
