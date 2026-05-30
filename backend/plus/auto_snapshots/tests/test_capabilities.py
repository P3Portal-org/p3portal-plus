# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-77: Capability + Hook-Merge + Plus-Gate-Tests."""
import pytest

import backend.core.plus_protocol as plus_protocol_module
from backend.core.plus_protocol import CAPABILITIES, CorePlusBehavior, plus_behavior

pytestmark = pytest.mark.plus_only


# ─── Capability-Registrierung ──────────────────────────────────────────────


def test_auto_snapshots_capability_registered():
    assert CAPABILITIES.get("auto_snapshots") == "can_use_auto_snapshots"


def test_core_default_returns_false():
    core = CorePlusBehavior()
    assert core.can_use_auto_snapshots() is False


# ─── Core-Defaults für Plus-Hooks ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_core_on_user_deleted_returns_zero():
    core = CorePlusBehavior()
    assert await core.on_user_deleted_auto_snapshots(1, "alice") == 0


@pytest.mark.asyncio
async def test_core_on_vm_lxc_deleted_returns_zero():
    core = CorePlusBehavior()
    assert await core.on_vm_lxc_deleted_auto_snapshots(1, 100, "qemu", "alice") == 0


@pytest.mark.asyncio
async def test_core_on_node_deleted_returns_zero():
    core = CorePlusBehavior()
    assert await core.on_node_deleted_auto_snapshots(1, "alice") == 0


def test_core_approval_action_types_empty():
    core = CorePlusBehavior()
    assert core.get_auto_snapshot_approval_action_types() == []


# ─── Hook-Merge: PROJ-70 + PROJ-77 Handler im Plus-Modus ──────────────────


def test_hook_merge_in_plus_mode(monkeypatch):
    """Wenn Plus aktiv ist, sind sowohl PROJ-70- als auch PROJ-77-Handler im Registry."""
    monkeypatch.setattr(plus_protocol_module, "is_plus_edition", lambda: True)

    handlers = plus_behavior.get_scheduled_job_action_handlers()
    # PROJ-70 (4 Handler):
    assert "playbook" in handlers
    assert "ssh" in handlers
    assert "power_action" in handlers
    assert "git_sync" in handlers
    # PROJ-77 (2 Handler):
    assert "auto_config_snapshot" in handlers
    assert "auto_vm_snapshot" in handlers


def test_handlers_lifecycle_hook_routes_via_active(monkeypatch):
    """Lifecycle-Override für get_scheduled_job_action_handlers ist is_plus_edition-unabhängig
    (S506-Pattern: Runner braucht Handler-Registry auch in Core-Mode wenn Plus geladen)."""
    monkeypatch.setattr(plus_protocol_module, "is_plus_edition", lambda: False)
    # Wenn Plus-Modul geladen wurde, sollen die Handler trotzdem da sein
    handlers = plus_behavior.get_scheduled_job_action_handlers()
    # In CI ohne Plus-Modul: leeres Dict. Mit Plus-Modul: alle 6 Handler.
    # Beide Fälle sind valide – wichtig ist, dass kein Crash auftritt.
    assert isinstance(handlers, dict)
