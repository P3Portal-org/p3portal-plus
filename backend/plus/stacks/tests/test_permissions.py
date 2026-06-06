# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-76: Tests für permissions.py (Admin OR Owner)."""
from __future__ import annotations

import pytest

from backend.plus.stacks.permissions import can_manage_stack

pytestmark = pytest.mark.plus_only


def test_admin_always_allowed():
    assert can_manage_stack("admin", None, None) is True
    assert can_manage_stack("admin", 5, 99) is True


def test_owner_allowed():
    assert can_manage_stack("operator", 10, 10) is True


def test_non_owner_denied():
    assert can_manage_stack("operator", 10, 20) is False


def test_no_user_id_denied():
    assert can_manage_stack("operator", None, 10) is False


def test_orphan_owner_null_denied_for_non_admin():
    assert can_manage_stack("operator", 10, None) is False
