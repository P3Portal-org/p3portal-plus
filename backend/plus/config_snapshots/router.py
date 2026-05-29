# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-74: FastAPI-Router für VM/LXC Config-Snapshots.

Prefix /api/config-snapshots.
Plus-Gate: 404 für Core-/unlizenzierte Plus-Instanzen.
Permission: Admin ODER Owner (PROJ-48 vm_owners) – AC-PERM-1a.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import Response, StreamingResponse

from backend.core.deps import CurrentUser, get_current_user, require_admin_or
from backend.core.plus_protocol import plus_behavior
from backend.features.api_surface.deps import require_scope_for_upk

from . import service
from .permissions import can_user_manage_config_snapshot, can_user_manage_orphan_snapshots
from .schemas import (
    BulkIds,
    DiffABOut,
    DiffOut,
    OrphanOut,
    RestoreIn,
    RestoreKeysIn,
    SnapshotDetail,
    SnapshotIn,
    SnapshotOut,
    UploadOut,
)

router = APIRouter(prefix="/api/config-snapshots", tags=["config-snapshots"])

_require_orphan_admin = require_admin_or("manage_config_snapshots_orphans")


def _check_plus() -> None:
    if not plus_behavior.can_use_config_snapshots():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")


def _validate_kind(kind: str) -> str:
    if kind not in ("qemu", "lxc"):
        raise HTTPException(status_code=422, detail="invalid_kind")
    return kind


async def _assert_perm(current_user: CurrentUser, snap: SnapshotDetail | SnapshotOut) -> None:
    allowed = await can_user_manage_config_snapshot(
        current_user.user_id,
        current_user.role,
        snap.portal_node_id,
        snap.vmid,
        snap.kind,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="forbidden")


# ── Static routes before path-param routes ───────────────────────────────────

# GET /api/config-snapshots/orphans
@router.get("/orphans", response_model=list[OrphanOut])
async def list_orphans(
    current_user: CurrentUser = Depends(_require_orphan_admin),
    _scope: CurrentUser = Depends(require_scope_for_upk("config_snapshots:read")),
):
    _check_plus()
    return await service.list_orphans()


# GET /api/config-snapshots/diff?a=&b=
@router.get("/diff", response_model=DiffABOut)
async def diff_snapshots_ab(
    a: str = Query(...),
    b: str = Query(...),
    current_user: CurrentUser = Depends(get_current_user),
    _scope: CurrentUser = Depends(require_scope_for_upk("config_snapshots:read")),
):
    _check_plus()
    snap_a = await service.get_snapshot(a)
    await _assert_perm(current_user, snap_a)
    # Also check access to snapshot B
    snap_b = await service.get_snapshot(b)
    await _assert_perm(current_user, snap_b)
    return await service.diff_snapshot_ab(a, b)


# POST /api/config-snapshots/bulk-download
@router.post("/bulk-download")
async def bulk_download(
    body: BulkIds,
    current_user: CurrentUser = Depends(get_current_user),
    _scope: CurrentUser = Depends(require_scope_for_upk("config_snapshots:read")),
):
    _check_plus()
    # Verify permission for each requested ID; filter to permitted set
    permitted_ids: list[str] = []
    for sid in body.ids:
        try:
            snap = await service.get_snapshot(sid)
        except HTTPException:
            continue
        allowed = await can_user_manage_config_snapshot(
            current_user.user_id, current_user.role,
            snap.portal_node_id, snap.vmid, snap.kind,
        )
        if allowed:
            permitted_ids.append(sid)

    if not permitted_ids:
        raise HTTPException(status_code=404, detail="no_accessible_snapshots")

    zip_bytes = await service.bulk_download_snapshots(permitted_ids, current_user.username)
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=config-snapshots.zip"},
    )


# POST /api/config-snapshots/bulk-delete
@router.post("/bulk-delete", status_code=204)
async def bulk_delete(
    body: BulkIds,
    current_user: CurrentUser = Depends(get_current_user),
    _scope: CurrentUser = Depends(require_scope_for_upk("config_snapshots:write")),
):
    _check_plus()
    # Verify permission for each requested ID; only delete permitted ones
    permitted_ids: list[str] = []
    for sid in body.ids:
        try:
            snap = await service.get_snapshot(sid)
        except HTTPException:
            continue
        allowed = await can_user_manage_config_snapshot(
            current_user.user_id, current_user.role,
            snap.portal_node_id, snap.vmid, snap.kind,
        )
        if allowed:
            permitted_ids.append(sid)

    if not permitted_ids:
        raise HTTPException(status_code=404, detail="no_accessible_snapshots")

    await service.bulk_delete_snapshots(permitted_ids, current_user.username)


# ── By-node list (PROJ-40 Compute-Node-Detail Tab) ───────────────────────────

@router.get("/by-node/{portal_node_id}", response_model=list[SnapshotOut])
async def list_by_node(
    portal_node_id: int,
    q: Optional[str] = Query(None),
    kind: Optional[str] = Query(None),
    user_id: Optional[int] = Query(None),
    since: Optional[str] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    _scope: CurrentUser = Depends(require_scope_for_upk("config_snapshots:read")),
):
    _check_plus()
    if kind is not None:
        _validate_kind(kind)
    # Non-admin: restrict to own snapshots
    effective_user_id = user_id
    if current_user.role != "admin":
        if current_user.user_id is None:
            raise HTTPException(status_code=403, detail="forbidden")
        effective_user_id = current_user.user_id
    return await service.list_snapshots_by_node(
        portal_node_id=portal_node_id,
        q=q,
        kind=kind,
        user_id=effective_user_id,
        since=since,
    )


# ── VM-specific list (PROJ-29 VM-Detail Tab) ─────────────────────────────────

@router.get("", response_model=list[SnapshotOut])
async def list_snapshots(
    portal_node_id: int = Query(...),
    proxmox_node: str = Query(...),
    vmid: int = Query(...),
    kind: str = Query(...),
    current_user: CurrentUser = Depends(get_current_user),
    _scope: CurrentUser = Depends(require_scope_for_upk("config_snapshots:read")),
):
    _check_plus()
    _validate_kind(kind)
    allowed = await can_user_manage_config_snapshot(
        current_user.user_id, current_user.role,
        portal_node_id, vmid, kind,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="forbidden")
    return await service.list_snapshots(portal_node_id, proxmox_node, vmid, kind)


# ── Create snapshot ───────────────────────────────────────────────────────────

@router.post(
    "/{portal_node_id}/{proxmox_node}/{vmid}/create",
    response_model=SnapshotOut,
    status_code=201,
)
async def create_snapshot(
    portal_node_id: int,
    proxmox_node: str,
    vmid: int,
    body: SnapshotIn,
    kind: str = Query(...),
    current_user: CurrentUser = Depends(get_current_user),
    _scope: CurrentUser = Depends(require_scope_for_upk("config_snapshots:write")),
):
    _check_plus()
    _validate_kind(kind)
    allowed = await can_user_manage_config_snapshot(
        current_user.user_id, current_user.role,
        portal_node_id, vmid, kind,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="forbidden")
    return await service.create_snapshot(
        portal_node_id=portal_node_id,
        proxmox_node=proxmox_node,
        vmid=vmid,
        kind=kind,
        note=body.note,
        name=body.name,
        created_by_user_id=current_user.user_id,
        username=current_user.username,
    )


# ── Upload .conf ──────────────────────────────────────────────────────────────

@router.post(
    "/{portal_node_id}/{proxmox_node}/{vmid}/upload",
    response_model=UploadOut,
    status_code=201,
)
async def upload_snapshot(
    portal_node_id: int,
    proxmox_node: str,
    vmid: int,
    file: UploadFile = File(...),
    note: str = Form(...),
    kind: str = Query(...),
    current_user: CurrentUser = Depends(get_current_user),
    _scope: CurrentUser = Depends(require_scope_for_upk("config_snapshots:write")),
):
    _check_plus()
    _validate_kind(kind)
    allowed = await can_user_manage_config_snapshot(
        current_user.user_id, current_user.role,
        portal_node_id, vmid, kind,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="forbidden")
    return await service.upload_snapshot_conf(
        portal_node_id=portal_node_id,
        proxmox_node=proxmox_node,
        vmid=vmid,
        kind=kind,
        file=file,
        note=note,
        username=current_user.username,
        user_id=current_user.user_id,
    )


# ── Snapshot detail ───────────────────────────────────────────────────────────

@router.get("/{snapshot_id}", response_model=SnapshotDetail)
async def get_snapshot(
    snapshot_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    _scope: CurrentUser = Depends(require_scope_for_upk("config_snapshots:read")),
):
    _check_plus()
    snap = await service.get_snapshot(snapshot_id)
    await _assert_perm(current_user, snap)
    return snap


# ── Download .conf ────────────────────────────────────────────────────────────

@router.get("/{snapshot_id}/download")
async def download_snapshot(
    snapshot_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    _scope: CurrentUser = Depends(require_scope_for_upk("config_snapshots:read")),
):
    _check_plus()
    snap = await service.get_snapshot(snapshot_id)
    await _assert_perm(current_user, snap)
    filename, content = await service.download_snapshot_conf(snapshot_id)
    return Response(
        content=content.encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ── Restore ───────────────────────────────────────────────────────────────────

@router.post("/{snapshot_id}/restore")
async def restore_snapshot(
    snapshot_id: str,
    body: RestoreIn,
    current_user: CurrentUser = Depends(get_current_user),
    _scope: CurrentUser = Depends(require_scope_for_upk("config_snapshots:write")),
):
    _check_plus()
    snap = await service.get_snapshot(snapshot_id)
    await _assert_perm(current_user, snap)
    return await service.restore_snapshot(
        snapshot_id=snapshot_id,
        etag=body.etag,
        vm_name_confirm=body.vm_name_confirm,
        create_pre_restore_snapshot=body.create_pre_restore_snapshot,
        restart_after_restore=body.restart_after_restore,
        username=current_user.username,
        user_id=current_user.user_id,
    )


# ── Restore selected keys ─────────────────────────────────────────────────────

@router.post("/{snapshot_id}/restore-keys")
async def restore_snapshot_keys(
    snapshot_id: str,
    body: RestoreKeysIn,
    current_user: CurrentUser = Depends(get_current_user),
    _scope: CurrentUser = Depends(require_scope_for_upk("config_snapshots:write")),
):
    _check_plus()
    snap = await service.get_snapshot(snapshot_id)
    await _assert_perm(current_user, snap)
    return await service.restore_selected_keys(
        snapshot_id=snapshot_id,
        keys=body.keys,
        etag=body.etag,
        username=current_user.username,
        user_id=current_user.user_id,
    )


# ── Diff vs live ──────────────────────────────────────────────────────────────

@router.get("/{snapshot_id}/diff-live", response_model=DiffOut)
async def diff_live(
    snapshot_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    _scope: CurrentUser = Depends(require_scope_for_upk("config_snapshots:read")),
):
    _check_plus()
    snap = await service.get_snapshot(snapshot_id)
    await _assert_perm(current_user, snap)
    return await service.diff_snapshot_vs_live(snapshot_id)


# ── Delete single ─────────────────────────────────────────────────────────────

@router.delete("/{snapshot_id}", status_code=204)
async def delete_snapshot(
    snapshot_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    _scope: CurrentUser = Depends(require_scope_for_upk("config_snapshots:write")),
):
    _check_plus()
    snap = await service.get_snapshot(snapshot_id)
    await _assert_perm(current_user, snap)
    await service.delete_snapshot(snapshot_id, current_user.username)


# ── Orphan delete ─────────────────────────────────────────────────────────────

@router.delete("/orphans/{snapshot_id}", status_code=204)
async def delete_orphan(
    snapshot_id: str,
    current_user: CurrentUser = Depends(_require_orphan_admin),
    _scope: CurrentUser = Depends(require_scope_for_upk("config_snapshots:write")),
):
    _check_plus()
    await service.delete_orphan(snapshot_id, current_user.username)
