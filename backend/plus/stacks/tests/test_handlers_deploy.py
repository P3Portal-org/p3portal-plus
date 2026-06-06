# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-76 Phase 2b: approval handler re-check (etag + plan-change) AC-2B-APPR-4."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from backend.plus.approvals import handlers
from backend.plus.stacks import deploy_service as ds
from backend.plus.stacks import service as stack_service
from backend.plus.stacks.schemas import PlanResponse, PlanSummary

pytestmark = pytest.mark.plus_only


def _approval(uid=5):
    return {"requester_user_id": uid, "action_type": "stack_deploy", "action_target": "1"}


@pytest.mark.asyncio
async def test_etag_mismatch_aborts():
    payload = {"stack_id": 1, "current_etag": "old", "plan_summary": {"create": 2}}
    with patch.object(stack_service, "_get_stack_row",
                      AsyncMock(return_value={"id": 1, "current_etag": "NEW", "name": "web"})):
        with pytest.raises(ValueError, match="stack_plan_changed_since_request"):
            await handlers._handle_stack_deploy(_approval(), payload, "admin")


@pytest.mark.asyncio
async def test_plan_change_aborts():
    payload = {"stack_id": 1, "current_etag": "e1", "plan_summary": {"create": 2, "change": 0, "destroy": 0, "replace": 0}}
    # fresh plan now has different counts → abort
    fresh = PlanResponse(plan_token="t", operation="apply", summary=PlanSummary(create=3))
    with patch.object(stack_service, "_get_stack_row",
                      AsyncMock(return_value={"id": 1, "current_etag": "e1", "name": "web"})), \
         patch.object(handlers, "_lookup_user_role", AsyncMock(return_value="operator")), \
         patch.object(ds, "_spec_of", AsyncMock(return_value=object())), \
         patch.object(ds, "resolve_target_node", AsyncMock(return_value=object())), \
         patch.object(ds, "prepare_plan", AsyncMock(return_value=fresh)):
        with pytest.raises(ValueError, match="stack_plan_changed_since_request"):
            await handlers._handle_stack_deploy(_approval(), payload, "admin")


@pytest.mark.asyncio
async def test_happy_starts_job():
    payload = {"stack_id": 1, "current_etag": "e1", "plan_summary": {"create": 2, "change": 0, "destroy": 0, "replace": 0}}
    fresh = PlanResponse(plan_token="t", operation="apply", summary=PlanSummary(create=2))
    with patch.object(stack_service, "_get_stack_row",
                      AsyncMock(return_value={"id": 1, "current_etag": "e1", "name": "web"})), \
         patch.object(handlers, "_lookup_user_role", AsyncMock(return_value="operator")), \
         patch.object(ds, "_spec_of", AsyncMock(return_value=object())), \
         patch.object(ds, "resolve_target_node", AsyncMock(return_value=object())), \
         patch.object(ds, "prepare_plan", AsyncMock(return_value=fresh)), \
         patch.object(ds, "start_stack_job", AsyncMock(return_value={"job_id": "jZ", "deployment_id": 1})):
        job_id = await handlers._handle_stack_deploy(_approval(), payload, "admin")
    assert job_id == "jZ"


@pytest.mark.asyncio
async def test_destroy_handler_uses_destroy_operation():
    payload = {"stack_id": 1, "current_etag": "e1", "plan_summary": {"create": 0, "change": 0, "destroy": 2, "replace": 0}}
    fresh = PlanResponse(plan_token="t", operation="destroy", summary=PlanSummary(destroy=2))
    captured = {}

    async def _prepare(row, role, uid, user, operation):
        captured["op"] = operation
        return fresh

    with patch.object(stack_service, "_get_stack_row",
                      AsyncMock(return_value={"id": 1, "current_etag": "e1", "name": "web"})), \
         patch.object(handlers, "_lookup_user_role", AsyncMock(return_value="operator")), \
         patch.object(ds, "_spec_of", AsyncMock(return_value=object())), \
         patch.object(ds, "resolve_target_node", AsyncMock(return_value=object())), \
         patch.object(ds, "prepare_plan", _prepare), \
         patch.object(ds, "start_stack_job", AsyncMock(return_value={"job_id": "jD", "deployment_id": 1})):
        job_id = await handlers._handle_stack_destroy(_approval(), payload, "admin")
    assert job_id == "jD"
    assert captured["op"] == "destroy"
