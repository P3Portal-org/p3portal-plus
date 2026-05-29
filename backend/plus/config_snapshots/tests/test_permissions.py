# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-74: Tests für permissions.py (Permission-Resolver)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.plus.config_snapshots.permissions import (
    can_user_manage_config_snapshot,
    can_user_manage_orphan_snapshots,
)

pytestmark = pytest.mark.plus_only


def _make_db_mock(has_row: bool):
    """Return a context-manager mock for get_db() that simulates a DB row."""
    row_mock = MagicMock()
    row_mock.first.return_value = object() if has_row else None

    execute_mock = AsyncMock(return_value=row_mock)
    session_mock = AsyncMock()
    session_mock.execute = execute_mock
    session_mock.__aenter__ = AsyncMock(return_value=session_mock)
    session_mock.__aexit__ = AsyncMock(return_value=False)

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session_mock)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


# ── Admin always allowed ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_always_allowed():
    result = await can_user_manage_config_snapshot(
        user_id=1, user_role="admin", portal_node_id=1, vmid=100, kind="qemu"
    )
    assert result is True


@pytest.mark.asyncio
async def test_admin_allowed_without_portal_node():
    result = await can_user_manage_config_snapshot(
        user_id=1, user_role="admin", portal_node_id=None, vmid=100, kind="qemu"
    )
    assert result is True


# ── Non-admin checks ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_operator_with_no_ownership_denied():
    with patch(
        "backend.plus.config_snapshots.permissions.get_db",
        return_value=_make_db_mock(has_row=False),
    ):
        result = await can_user_manage_config_snapshot(
            user_id=5, user_role="operator", portal_node_id=1, vmid=100, kind="qemu"
        )
    assert result is False


@pytest.mark.asyncio
async def test_owner_allowed():
    with patch(
        "backend.plus.config_snapshots.permissions.get_db",
        return_value=_make_db_mock(has_row=True),
    ):
        result = await can_user_manage_config_snapshot(
            user_id=5, user_role="operator", portal_node_id=1, vmid=100, kind="qemu"
        )
    assert result is True


@pytest.mark.asyncio
async def test_no_user_id_denied():
    result = await can_user_manage_config_snapshot(
        user_id=None, user_role="operator", portal_node_id=1, vmid=100, kind="qemu"
    )
    assert result is False


@pytest.mark.asyncio
async def test_none_portal_node_non_admin_denied():
    result = await can_user_manage_config_snapshot(
        user_id=5, user_role="operator", portal_node_id=None, vmid=100, kind="qemu"
    )
    assert result is False


@pytest.mark.asyncio
async def test_unknown_kind_denied():
    result = await can_user_manage_config_snapshot(
        user_id=5, user_role="operator", portal_node_id=1, vmid=100, kind="template"
    )
    assert result is False


@pytest.mark.asyncio
async def test_lxc_kind_supported():
    with patch(
        "backend.plus.config_snapshots.permissions.get_db",
        return_value=_make_db_mock(has_row=True),
    ):
        result = await can_user_manage_config_snapshot(
            user_id=5, user_role="viewer", portal_node_id=1, vmid=200, kind="lxc"
        )
    assert result is True


# ── Orphan management ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_orphan_admin_allowed():
    assert await can_user_manage_orphan_snapshots("admin") is True


@pytest.mark.asyncio
async def test_orphan_operator_denied():
    assert await can_user_manage_orphan_snapshots("operator") is False


@pytest.mark.asyncio
async def test_orphan_viewer_denied():
    assert await can_user_manage_orphan_snapshots("viewer") is False
