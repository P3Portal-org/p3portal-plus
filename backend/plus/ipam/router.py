# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-42 Phase 2: FastAPI-Router für das interne Plus-IPAM (Prefix /api/ipam).

Plus-Gate: 404 für Core-/unlizenzierte Plus-Instanzen (``_check_plus``). Der Core-
Simple-IPAM-Router (``backend/features/ipam/router.py``) bleibt separat und immer
aktiv (Pools + best-effort Vorschlag). Dieser Router ergänzt die zustandsbehaftete
Ebene: Allocations, Orphans, Netz-Freigaben, Toggles.

Scope-Zuordnung (PROJ-97, alle plus_only):
- ipam_allocations:read/write  – Allocations, Usage, Orphans
- ipam_grants:read/write       – Netz-Freigaben + Config-Toggles (Admin-Verwaltung)
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.core.deps import (
    CurrentUser,
    get_current_user,
    require_admin_or,
    require_not_restricted,
)
from backend.core.plus_protocol import plus_behavior
from backend.features.api_surface.deps import require_scope_for_upk  # PROJ-97

from . import cleanup, config_service, grants_service, service
from .schemas import (
    AllocationResponse,
    IpamConfigResponse,
    IpamConfigUpdateRequest,
    ManualAllocationRequest,
    NetworkGrantRequest,
    NetworkGrantResponse,
    PoolUsageResponse,
)
from .service import IpamReservationConflict

router = APIRouter(prefix="/api/ipam", tags=["ipam-plus"])

_ALLOC_READ = Depends(require_scope_for_upk("ipam_allocations:read"))
_ALLOC_WRITE = Depends(require_scope_for_upk("ipam_allocations:write"))
_GRANTS_READ = Depends(require_scope_for_upk("ipam_grants:read"))
_GRANTS_WRITE = Depends(require_scope_for_upk("ipam_grants:write"))

_manage = require_admin_or("manage_ipam")


def _check_plus() -> None:
    if not plus_behavior.can_use_ipam_plus():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")


async def _assert_can_view_vm(user: CurrentUser, portal_node_id: int, vmid: int) -> None:
    """BUG-42-P2-1-Härtung: nur wer die VM sehen darf, sieht ihre IPAM-Allocation.

    Spiegelt ``_check_detail_access`` (cluster.py) 1:1, damit die read-only VM-Detail-
    Karte nie mehr preisgibt als die Detailseite selbst — und **nie restriktiver** ist
    (kein neuer False-Deny): Admin/Operator/Proxmox sehen alles; ein Viewer **ohne
    jeglichen Grant** sieht alles (Dashboard-Backward-Compat); ein Viewer **mit** Grants
    braucht ``view`` auf dieser VM. Da die Allocation den VM-Typ nicht speichert, wird
    ``view`` über **beide** ``resource_type`` (vm|lxc) vereinigt — ``resolve_user_vm_access``
    überschreibt bei gleichem ``(node_id, vmid)``, daher zwei Calls statt einer Liste.
    ``require_not_restricted`` hat ``restricted`` bereits geblockt.
    """
    if user.auth_type == "proxmox" or user.role in ("admin", "operator"):
        return
    from backend.services.local_auth import get_user_by_username
    from backend.services.permissions_resolver import resolve_user_vm_access

    row = await get_user_by_username(user.username)
    if row is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not_authorized")
    combined: set[str] = set()
    saw_grant = False
    for rtype in ("vm", "lxc"):
        pm, has_any = await resolve_user_vm_access(
            row["id"],
            [{"node_id": portal_node_id, "vmid": vmid, "resource_type": rtype}],
        )
        saw_grant = saw_grant or has_any
        combined |= pm.get((portal_node_id, vmid), set())
    if not saw_grant:
        return  # Viewer ohne jeglichen Grant sieht alles (konsistent zum Dashboard)
    if "view" not in combined:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not_authorized")


# ── Konfiguration (Toggles) ───────────────────────────────────────────────────

@router.get("/config", response_model=IpamConfigResponse)
async def get_ipam_config(
    _: CurrentUser = Depends(get_current_user),
    __=_GRANTS_READ,
) -> IpamConfigResponse:
    """Aktuelle IPAM-Toggles (jeder eingeloggte Nutzer – FE-Gate braucht global_enabled)."""
    _check_plus()
    return IpamConfigResponse(**await config_service.get_config())


@router.put("/config", response_model=IpamConfigResponse)
async def update_ipam_config(
    body: IpamConfigUpdateRequest,
    current_user: CurrentUser = Depends(_manage),
    __=_GRANTS_WRITE,
) -> IpamConfigResponse:
    _check_plus()
    cfg = await config_service.update_config(
        global_enabled=body.global_enabled,
        strict_network_visibility=body.strict_network_visibility,
        updated_by=current_user.username,
    )
    return IpamConfigResponse(**cfg)


# ── Allocations (Lebenszyklus / Usage) ────────────────────────────────────────

@router.get("/allocations", response_model=list[AllocationResponse])
async def list_allocations(
    pool_id: Optional[int] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    _: CurrentUser = Depends(_manage),
    __=_ALLOC_READ,
) -> list[AllocationResponse]:
    _check_plus()
    return await service.list_allocations(pool_id=pool_id, status=status_filter)


@router.get("/allocations/for-vm", response_model=Optional[AllocationResponse])
async def allocation_for_vm(
    portal_node_id: int = Query(...),
    vmid: int = Query(...),
    current_user: CurrentUser = Depends(require_not_restricted),
    __=_ALLOC_READ,
) -> Optional[AllocationResponse]:
    """IPAM-Allocation einer konkreten VM/LXC (read-only, VM/LXC-Detailseite).

    Nicht ``manage_ipam``-gated, damit ein VM-Owner die eigene Zuordnung sieht
    (US-7); ``require_not_restricted`` wie ``/suggest``/``by-network``. Liefert die
    Allocation oder ``null`` (kein Fund). Literal-Route **vor** ``/allocations``-CRUD
    ist unkritisch (eigener Pfad), aber der ``for-vm``-Pfad muss vor einer etwaigen
    ``/allocations/{id}`` stehen — hier ist nur DELETE per ``{alloc_id}`` definiert.
    """
    _check_plus()
    await _assert_can_view_vm(current_user, portal_node_id, vmid)
    alloc = await service.get_allocation_for_vm(portal_node_id, vmid)
    return AllocationResponse(**alloc) if alloc else None


@router.get("/pools/{pool_id}/usage", response_model=PoolUsageResponse)
async def pool_usage(
    pool_id: int,
    _: CurrentUser = Depends(_manage),
    __=_ALLOC_READ,
) -> PoolUsageResponse:
    _check_plus()
    usage = await service.pool_usage(pool_id)
    if usage is None:
        raise HTTPException(status_code=404, detail="pool_not_found")
    return usage


@router.post("/allocations", response_model=AllocationResponse,
             status_code=status.HTTP_201_CREATED)
async def add_manual_allocation(
    body: ManualAllocationRequest,
    current_user: CurrentUser = Depends(_manage),
    __=_ALLOC_WRITE,
) -> AllocationResponse:
    """Fremd-IP (Nicht-Proxmox) manuell als belegt eintragen."""
    _check_plus()
    try:
        return await service.add_manual(
            body.pool_id, body.ip, body.note, current_user.username
        )
    except IpamReservationConflict as conflict:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "ip_already_allocated", "ip": conflict.ip},
        )


@router.delete("/allocations/{alloc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def release_allocation(
    alloc_id: int,
    _: CurrentUser = Depends(_manage),
    __=_ALLOC_WRITE,
) -> None:
    _check_plus()
    ok = await service.release_by_id(alloc_id)
    if not ok:
        raise HTTPException(status_code=404, detail="allocation_not_found")


# ── Orphans (verwaiste Allocations) ───────────────────────────────────────────

@router.get("/orphans", response_model=list[AllocationResponse])
async def list_orphans(
    _: CurrentUser = Depends(_manage),
    __=_ALLOC_READ,
) -> list[AllocationResponse]:
    _check_plus()
    return await service.list_allocations(status="orphaned")


@router.delete("/orphans")
async def release_orphans(
    ids: list[int] = Query(default_factory=list,
                           description="Leere Liste = alle verwaisten freigeben"),
    current_user: CurrentUser = Depends(_manage),
    __=_ALLOC_WRITE,
) -> dict:
    _check_plus()
    count = await cleanup.release_orphans(ids or None, current_user.username)
    return {"released": count}


# ── Netz-Freigaben ────────────────────────────────────────────────────────────

@router.get("/grants", response_model=list[NetworkGrantResponse])
async def list_grants(
    _: CurrentUser = Depends(_manage),
    __=_GRANTS_READ,
) -> list[NetworkGrantResponse]:
    _check_plus()
    return await grants_service.list_grants()


@router.post("/grants", response_model=NetworkGrantResponse,
             status_code=status.HTTP_201_CREATED)
async def create_grant(
    body: NetworkGrantRequest,
    current_user: CurrentUser = Depends(_manage),
    __=_GRANTS_WRITE,
) -> NetworkGrantResponse:
    _check_plus()
    return await grants_service.create_grant(body, current_user.username)


@router.delete("/grants/{grant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_grant(
    grant_id: int,
    _: CurrentUser = Depends(_manage),
    __=_GRANTS_WRITE,
) -> None:
    _check_plus()
    ok = await grants_service.delete_grant(grant_id)
    if not ok:
        raise HTTPException(status_code=404, detail="grant_not_found")
