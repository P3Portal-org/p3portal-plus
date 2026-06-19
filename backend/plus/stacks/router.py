# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-76 Phase 1: FastAPI-Router für Stacks.

Prefix /api/stacks.
Plus-Gate: 404 für Core-/unlizenzierte Plus-Instanzen (AC-API-17).
Permission: Admin ODER Owner (einfache Spalte stacks.owner_user_id).
Approval-Wiring (PROJ-50) in PUT + DELETE.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse

from backend.core.deps import CurrentUser, get_current_user, require_admin_or
from backend.core.plus_protocol import plus_behavior
from backend.features.api_surface.deps import require_scope_for_upk

from . import cloud_init, deploy_service, service
from .permissions import can_manage_stack
from .schemas import (
    CloudInitConfigRequest,
    CloudInitConfigResponse,
    DeployJobResponse,
    DeploymentResponse,
    DeployRequest,
    DriftReport,
    LiveResource,
    OrphanStackResponse,
    PlanResponse,
    PlanSummary,
    PreviewResult,
    ReassignRequest,
    RestoreVersionRequest,
    StackCreateRequest,
    StackDetailResponse,
    StackDiffResponse,
    StackResponse,
    StackUpdateRequest,
    StackValidateRequest,
    StackVersionResponse,
    StackVersionSummary,
    ValidationResult,
)
from .service import EtagConflict

router = APIRouter(prefix="/api/stacks", tags=["stacks"])

_require_orphan_admin = require_admin_or("manage_orphan_stacks")


def _check_plus() -> None:
    if not plus_behavior.can_use_stacks():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")


async def _load_and_authorize(stack_id: int, current_user: CurrentUser, include_deleted: bool = False):
    row = await service._get_stack_row(stack_id, include_deleted=include_deleted)
    if not can_manage_stack(current_user.role, current_user.user_id, row["owner_user_id"]):
        raise HTTPException(status_code=403, detail="forbidden")
    return row


# ── Static routes (before /{stack_id}) ───────────────────────────────────────

@router.get("/orphans", response_model=list[OrphanStackResponse])
async def list_orphans(
    current_user: CurrentUser = Depends(_require_orphan_admin),
):
    _check_plus()
    return await service.list_orphans()


@router.post("/orphans/{stack_id}/reassign", response_model=StackResponse)
async def reassign_orphan(
    stack_id: int,
    body: ReassignRequest,
    current_user: CurrentUser = Depends(_require_orphan_admin),
):
    _check_plus()
    return await service.reassign_orphan(stack_id, body.owner_user_id, current_user.username)


@router.delete("/orphans/{stack_id}", status_code=204)
async def purge_orphan(
    stack_id: int,
    current_user: CurrentUser = Depends(_require_orphan_admin),
):
    _check_plus()
    await service.purge_orphan(stack_id, current_user.username)


@router.post("/validate", response_model=ValidationResult)
async def validate_stack(
    body: StackValidateRequest,
    current_user: CurrentUser = Depends(get_current_user),
    _scope: CurrentUser = Depends(require_scope_for_upk("stacks:read")),
):
    _check_plus()
    return await service.validate_definition(body)


@router.post("/preview", response_model=PreviewResult)
async def preview_new_stack(
    body: StackValidateRequest,
    current_user: CurrentUser = Depends(get_current_user),
    _scope: CurrentUser = Depends(require_scope_for_upk("stacks:read")),
):
    _check_plus()
    return await service.preview_definition(body)


# ── List + Create ─────────────────────────────────────────────────────────────

@router.get("", response_model=list[StackResponse])
async def list_stacks(
    q: Optional[str] = Query(None),
    include_deleted: bool = Query(False),
    current_user: CurrentUser = Depends(get_current_user),
    _scope: CurrentUser = Depends(require_scope_for_upk("stacks:read")),
):
    _check_plus()
    inc = include_deleted and current_user.role == "admin"
    return await service.list_stacks(
        user_id=current_user.user_id,
        role=current_user.role,
        q=q,
        include_deleted=inc,
    )


@router.post("", response_model=StackResponse, status_code=201)
async def create_stack(
    body: StackCreateRequest,
    current_user: CurrentUser = Depends(get_current_user),
    _scope: CurrentUser = Depends(require_scope_for_upk("stacks:write")),
):
    _check_plus()
    return await service.create_stack(body, current_user.user_id, current_user.username)


# ── Detail / Update / Delete ──────────────────────────────────────────────────

@router.get("/{stack_id}", response_model=StackDetailResponse)
async def get_stack(
    stack_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    _scope: CurrentUser = Depends(require_scope_for_upk("stacks:read")),
):
    _check_plus()
    await _load_and_authorize(stack_id, current_user, include_deleted=(current_user.role == "admin"))
    return await service.get_stack_detail(stack_id)


@router.put("/{stack_id}", response_model=StackResponse)
async def update_stack(
    stack_id: int,
    body: StackUpdateRequest,
    change_summary: Optional[str] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    _scope: CurrentUser = Depends(require_scope_for_upk("stacks:write")),
):
    _check_plus()
    row = await _load_and_authorize(stack_id, current_user)

    if change_summary and not body.change_summary:
        body.change_summary = change_summary

    # PROJ-50: Approval-Check (payload trägt new_yaml für Re-Check beim Approve)
    if current_user.user_id is not None:
        try:
            from .validation import parse_input
            _raw, canonical = parse_input(body)
        except Exception:
            canonical = body.yaml_text or ""
        try:
            decision = await plus_behavior.requires_approval(
                action_type="stack_edit",
                payload={
                    "stack_id": stack_id,
                    "stack_name": row["name"],
                    "new_yaml": canonical,
                    "expected_etag": body.expected_etag,
                    "change_summary": body.change_summary,
                },
                user_id=current_user.user_id,
                username=current_user.username,
            )
            if decision is not None:
                return JSONResponse(
                    status_code=202,
                    content={
                        "status": "pending_approval",
                        "approval_id": decision.approval_id,
                        "poll_url": decision.poll_url,
                    },
                )
        except HTTPException:
            raise
        except Exception:
            pass

    try:
        return await service.update_with_etag(stack_id, body, current_user.user_id, current_user.username)
    except EtagConflict as conflict:
        return JSONResponse(status_code=409, content=conflict.body.model_dump())


@router.delete("/{stack_id}", status_code=204)
async def delete_stack(
    stack_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    _scope: CurrentUser = Depends(require_scope_for_upk("stacks:delete")),
):
    _check_plus()
    row = await _load_and_authorize(stack_id, current_user)

    # PROJ-50: Approval-Check
    if current_user.user_id is not None:
        try:
            decision = await plus_behavior.requires_approval(
                action_type="stack_delete",
                payload={"stack_id": stack_id, "stack_name": row["name"]},
                user_id=current_user.user_id,
                username=current_user.username,
            )
            if decision is not None:
                return JSONResponse(
                    status_code=202,
                    content={
                        "status": "pending_approval",
                        "approval_id": decision.approval_id,
                        "poll_url": decision.poll_url,
                    },
                )
        except Exception:
            pass

    await service.soft_delete(stack_id, current_user.username)
    # Cancel any pending approvals for this stack (best-effort)
    try:
        await plus_behavior.on_stack_deleted_cancel_approvals(stack_id)
    except Exception:
        pass
    return Response(status_code=204)


# ── Preview saved stack ───────────────────────────────────────────────────────

@router.post("/{stack_id}/preview", response_model=PreviewResult)
async def preview_saved(
    stack_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    _scope: CurrentUser = Depends(require_scope_for_upk("stacks:read")),
):
    _check_plus()
    await _load_and_authorize(stack_id, current_user)
    return await service.preview_saved_stack(stack_id)


# ── Versions ───────────────────────────────────────────────────────────────────

@router.get("/{stack_id}/versions", response_model=list[StackVersionSummary])
async def list_versions(
    stack_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    _scope: CurrentUser = Depends(require_scope_for_upk("stacks:read")),
):
    _check_plus()
    await _load_and_authorize(stack_id, current_user, include_deleted=(current_user.role == "admin"))
    return await service.list_versions(stack_id)


@router.get("/{stack_id}/versions/{version_number}", response_model=StackVersionResponse)
async def get_version(
    stack_id: int,
    version_number: int,
    current_user: CurrentUser = Depends(get_current_user),
    _scope: CurrentUser = Depends(require_scope_for_upk("stacks:read")),
):
    _check_plus()
    await _load_and_authorize(stack_id, current_user, include_deleted=(current_user.role == "admin"))
    return await service.get_version(stack_id, version_number)


@router.get("/{stack_id}/diff", response_model=StackDiffResponse)
async def diff_stack(
    stack_id: int,
    from_: str = Query("current", alias="from"),
    to: str = Query("current"),
    current_user: CurrentUser = Depends(get_current_user),
    _scope: CurrentUser = Depends(require_scope_for_upk("stacks:read")),
):
    _check_plus()
    await _load_and_authorize(stack_id, current_user, include_deleted=(current_user.role == "admin"))
    return await service.diff_stack(stack_id, from_, to)


# ── Restore ────────────────────────────────────────────────────────────────────

@router.post("/{stack_id}/restore-version", response_model=StackResponse)
async def restore_version(
    stack_id: int,
    body: RestoreVersionRequest,
    current_user: CurrentUser = Depends(get_current_user),
    _scope: CurrentUser = Depends(require_scope_for_upk("stacks:write")),
):
    _check_plus()
    await _load_and_authorize(stack_id, current_user)
    try:
        return await service.restore_version(
            stack_id=stack_id,
            version_number=body.version_number,
            user_id=current_user.user_id,
            username=current_user.username,
            change_summary=body.change_summary,
            expected_etag=body.expected_etag,
        )
    except EtagConflict as conflict:
        return JSONResponse(status_code=409, content=conflict.body.model_dump())


# ── PROJ-85: Cloud-Init login/IP (separate encrypted store, not in YAML) ──────

@router.get("/{stack_id}/cloud-init", response_model=CloudInitConfigResponse)
async def get_stack_cloud_init(
    stack_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    _scope: CurrentUser = Depends(require_scope_for_upk("stacks:read")),
):
    _check_plus()
    await _load_and_authorize(stack_id, current_user, include_deleted=(current_user.role == "admin"))
    return await cloud_init.get_cloud_init(stack_id)


@router.put("/{stack_id}/cloud-init", response_model=CloudInitConfigResponse)
async def put_stack_cloud_init(
    stack_id: int,
    body: CloudInitConfigRequest,
    current_user: CurrentUser = Depends(get_current_user),
    _scope: CurrentUser = Depends(require_scope_for_upk("stacks:write")),
):
    _check_plus()
    await _load_and_authorize(stack_id, current_user)
    # No approval-202: cloud-init is not versioned/approved (AC-STORE-3).
    return await cloud_init.put_cloud_init(stack_id, body, current_user.username)


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 2b: Plan / Deploy / Destroy / Drift / Deployments / Live-Resources
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/{stack_id}/plan", response_model=PlanResponse)
async def plan_stack(
    stack_id: int,
    operation: str = Query("apply"),
    current_user: CurrentUser = Depends(get_current_user),
    _scope: CurrentUser = Depends(require_scope_for_upk("stacks:write")),
):
    _check_plus()
    row = await _load_and_authorize(stack_id, current_user)
    if operation not in ("apply", "destroy"):
        raise HTTPException(status_code=422, detail="invalid_operation")
    return await deploy_service.prepare_plan(
        row, current_user.role, current_user.user_id, current_user.username, operation,
    )


async def _deploy_or_destroy(
    stack_id: int, body: DeployRequest, operation: str, current_user: CurrentUser,
):
    """Shared apply/destroy flow: re-gate → consume plan-token → approval-202 → job."""
    row = await _load_and_authorize(stack_id, current_user)

    spec = await deploy_service._spec_of(row)
    node = await deploy_service.resolve_target_node(spec)
    # Re-check RBAC/Quota (definition/rights could have changed since /plan).
    await deploy_service.assert_deploy_allowed(
        row, spec, node, current_user.role, current_user.user_id, current_user.username,
    )

    entry = deploy_service.consume_plan_token(
        body.plan_token, stack_id, row["current_etag"], operation,
    )
    summary: PlanSummary = entry["summary"]

    # PROJ-50: Approval-Check (payload carries plan-summary + etag for the re-check).
    action_type = "stack_deploy" if operation == "apply" else "stack_destroy"
    if current_user.user_id is not None:
        try:
            decision = await plus_behavior.requires_approval(
                action_type=action_type,
                payload={
                    "stack_id": stack_id,
                    "stack_name": row["name"],
                    "operation": operation,
                    "current_etag": row["current_etag"],
                    "plan_summary": summary.model_dump(),
                },
                user_id=current_user.user_id,
                username=current_user.username,
            )
            if decision is not None:
                return JSONResponse(
                    status_code=202,
                    content={
                        "status": "pending_approval",
                        "approval_id": decision.approval_id,
                        "poll_url": decision.poll_url,
                    },
                )
        except HTTPException:
            raise
        except Exception:
            pass

    job = await deploy_service.start_stack_job(
        row, operation, summary, node, current_user.user_id, current_user.username,
    )
    from .deployments import derive_deployment_state
    fresh = await service._get_stack_row(stack_id)
    return DeployJobResponse(
        job_id=job["job_id"],
        deployment_id=job["deployment_id"],
        operation=operation,
        deployment_state=await derive_deployment_state(fresh),
    )


@router.post("/{stack_id}/deploy")
async def deploy_stack(
    stack_id: int,
    body: DeployRequest,
    current_user: CurrentUser = Depends(get_current_user),
    _scope: CurrentUser = Depends(require_scope_for_upk("stacks:write")),
):
    _check_plus()
    return await _deploy_or_destroy(stack_id, body, "apply", current_user)


@router.post("/{stack_id}/destroy")
async def destroy_stack(
    stack_id: int,
    body: DeployRequest,
    current_user: CurrentUser = Depends(get_current_user),
    _scope: CurrentUser = Depends(require_scope_for_upk("stacks:write")),
):
    _check_plus()
    return await _deploy_or_destroy(stack_id, body, "destroy", current_user)


@router.api_route("/{stack_id}/drift", methods=["GET", "POST"], response_model=DriftReport)
async def stack_drift(
    stack_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    _scope: CurrentUser = Depends(require_scope_for_upk("stacks:read")),
):
    _check_plus()
    row = await _load_and_authorize(stack_id, current_user)
    return await deploy_service.run_drift(row, current_user.username)


@router.get("/{stack_id}/deployments", response_model=list[DeploymentResponse])
async def list_deployments(
    stack_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    _scope: CurrentUser = Depends(require_scope_for_upk("stacks:read")),
):
    _check_plus()
    await _load_and_authorize(stack_id, current_user, include_deleted=(current_user.role == "admin"))
    from .deployments import list_deployments as _list
    import json as _json
    rows = await _list(stack_id)
    out: list[DeploymentResponse] = []
    for r in rows:
        summary = None
        if r.get("plan_summary_json"):
            try:
                summary = PlanSummary(**_json.loads(r["plan_summary_json"]))
            except Exception:
                summary = None
        out.append(DeploymentResponse(
            id=r["id"], operation=r["operation"], status=r["status"],
            job_id=r["job_id"], plan_summary=summary,
            triggered_by_user_id=r["triggered_by_user_id"],
            started_at=r["started_at"], finished_at=r["finished_at"],
            error_text=r["error_text"],
        ))
    return out


@router.get("/{stack_id}/resources/live", response_model=list[LiveResource])
async def list_live_resources(
    stack_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    _scope: CurrentUser = Depends(require_scope_for_upk("stacks:read")),
):
    _check_plus()
    await _load_and_authorize(stack_id, current_user, include_deleted=(current_user.role == "admin"))
    from .deployments import list_deployed_resources
    rows = await list_deployed_resources(stack_id)
    return [
        LiveResource(
            resource_name=r["resource_name"], node=r["node"], vmid=r["vmid"],
            kind=r["kind"], portal_node_id=r["portal_node_id"],
        )
        for r in rows
    ]
