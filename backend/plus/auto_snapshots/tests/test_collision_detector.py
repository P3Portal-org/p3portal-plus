# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-77: Tests für collision_detector.is_locked_response."""
import pytest

from backend.plus.auto_snapshots.collision_detector import (
    LOCK_PATTERNS, is_locked_response,
)

pytestmark = pytest.mark.plus_only


def test_lock_patterns_frozenset():
    assert isinstance(LOCK_PATTERNS, frozenset)
    assert "vm is locked" in LOCK_PATTERNS
    assert "backup lock" in LOCK_PATTERNS


def test_proxmox_vm_locked_response():
    assert is_locked_response(500, "VM is locked (backup)") is True


def test_lxc_locked_response():
    assert is_locked_response(500, "CT is locked (snapshot)") is True


def test_lock_pattern_via_task_exitstatus():
    assert is_locked_response(200, "OK", task_exitstatus="got lock timeout") is True


def test_migration_tunnel_statuscodes():
    assert is_locked_response(595, "") is True
    assert is_locked_response(596, "") is True
    assert is_locked_response(598, "") is True


def test_unrelated_500_is_not_locked():
    assert is_locked_response(500, "storage 'foo' does not exist") is False


def test_empty_input():
    assert is_locked_response(None, None) is False
    assert is_locked_response(200, "") is False


def test_dict_body_lock_pattern():
    body = {"errors": ["VM is locked (snapshot)"]}
    assert is_locked_response(500, body) is True


def test_case_insensitive_match():
    assert is_locked_response(500, "VM Is LoCkEd") is True
