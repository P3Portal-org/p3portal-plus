# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-76: Tests für Capability + Permission + Scope-Registrierung + ETag."""
from __future__ import annotations

import hashlib

import pytest

from backend.core.plus_protocol import CAPABILITIES, CorePlusBehavior
from backend.plus.stacks.service import etag_of

pytestmark = pytest.mark.plus_only


def test_stacks_capability_registered():
    assert "stacks" in CAPABILITIES
    assert CAPABILITIES["stacks"] == "can_use_stacks"


def test_core_default_stacks_disabled():
    assert CorePlusBehavior().can_use_stacks() is False


def test_core_stack_hooks_noop():
    core = CorePlusBehavior()
    assert core.get_stack_approval_action_types() == []


@pytest.mark.asyncio
async def test_core_on_user_deleted_stacks_noop():
    assert await CorePlusBehavior().on_user_deleted_stacks(1) == 0


@pytest.mark.asyncio
async def test_core_on_stack_deleted_cancel_approvals_noop():
    assert await CorePlusBehavior().on_stack_deleted_cancel_approvals(1) == 0


def test_plus_active_behavior_enables_stacks():
    from backend.plus import PlusActiveBehavior
    inst = PlusActiveBehavior()
    assert inst.can_use_stacks() is True
    assert inst.get_stack_approval_action_types() == [
        "stack_edit", "stack_delete", "stack_deploy", "stack_destroy",
    ]
    assert "manage_orphan_stacks" in inst.get_extra_portal_permissions()


def test_scope_manifest_has_stacks_scopes():
    from backend.features.api_surface.manifest import SCOPE_MANIFEST_BY_NAME
    for name in ("stacks:read", "stacks:write", "stacks:delete"):
        assert name in SCOPE_MANIFEST_BY_NAME
        assert SCOPE_MANIFEST_BY_NAME[name].plus_only is True


def test_handler_registry_has_stack_actions():
    from backend.plus.approvals.handlers import HANDLER_REGISTRY
    assert "stack_edit" in HANDLER_REGISTRY
    assert "stack_delete" in HANDLER_REGISTRY


def test_extract_action_target_stack():
    from backend.plus.approvals_plus import _extract_action_target
    assert _extract_action_target("stack_edit", {"stack_id": 42}) == "42"
    assert _extract_action_target("stack_delete", {"stack_id": 7}) == "7"


# ── etag_of ──────────────────────────────────────────────────────────────────

def test_etag_deterministic():
    assert etag_of("name: web\n") == etag_of("name: web\n")


def test_etag_is_sha256():
    txt = "name: web\n"
    assert etag_of(txt) == hashlib.sha256(txt.encode()).hexdigest()


def test_etag_differs():
    assert etag_of("a") != etag_of("b")


def test_etag_length():
    assert len(etag_of("x")) == 64
