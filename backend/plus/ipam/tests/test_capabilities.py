# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-42 Phase 2: Capability + Core-No-op-Defaults + Plus-Gate + Permission."""
from types import SimpleNamespace

import pytest

import backend.core.plus_protocol as plus_protocol_module
from backend.core.plus_protocol import CAPABILITIES, CorePlusBehavior, plus_behavior

pytestmark = pytest.mark.plus_only


# ── Capability-Registrierung ─────────────────────────────────────────────────

def test_ipam_plus_capability_registered():
    assert CAPABILITIES.get("ipam_plus") == "can_use_ipam_plus"


def test_core_default_returns_false():
    assert CorePlusBehavior().can_use_ipam_plus() is False


def test_plus_active_returns_true(monkeypatch):
    monkeypatch.setattr(plus_protocol_module, "is_plus_edition", lambda: True)
    assert plus_behavior.can_use_ipam_plus() is True


# ── Plus-Extra-Permission manage_ipam ────────────────────────────────────────

def test_manage_ipam_permission_registered(monkeypatch):
    monkeypatch.setattr(plus_protocol_module, "is_plus_edition", lambda: True)
    assert "manage_ipam" in plus_behavior.get_extra_portal_permissions()


def test_manage_ipam_not_in_core(monkeypatch):
    monkeypatch.setattr(plus_protocol_module, "is_plus_edition", lambda: False)
    assert "manage_ipam" not in plus_behavior.get_extra_portal_permissions()


# ── Core-No-op-Defaults aller Plus-Hooks ─────────────────────────────────────

@pytest.mark.asyncio
async def test_core_hooks_are_noops():
    core = CorePlusBehavior()
    assert await core.ipam_reserved_ips(1) == set()
    assert await core.on_playbook_job_started_ipam("j", "pb", {}, "u") == 0
    assert await core.on_job_finished_ipam("j", True) == 0
    assert await core.ipam_assert_pool_deletable(1) is None
    assert await core.on_vm_lxc_deleted_ipam(1, 100, "u") == 0
    assert await core.on_cluster_refresh_vanished_resources_ipam(set(), 1) == 0
    assert await core.ipam_release_impact(1, 100) == []
    assert await core.ipam_filter_pools(SimpleNamespace(), ["p"]) == ["p"]
    assert await core.get_ipam_allocation_for_vm(1, 100) is None


@pytest.mark.asyncio
async def test_core_filter_networks_is_identity():
    core = CorePlusBehavior()
    b, v = await core.filter_visible_networks(SimpleNamespace(), ["vmbr0"], ["gn"], "pve")
    assert b == ["vmbr0"] and v == ["gn"]
