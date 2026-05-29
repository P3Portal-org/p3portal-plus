# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-74: Tests für cleanup.py (Lifecycle-Hooks)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from backend.plus.config_snapshots.cleanup import (
    on_cluster_refresh_vanished_resources_config_snapshots,
    on_user_deleted_config_snapshots,
    on_vm_lxc_deleted,
)

pytestmark = pytest.mark.plus_only


def _db_mock_factory(*execute_returns):
    """Build a sequence of get_db() context-manager mocks.

    Each call to get_db() returns the next mock in the list.
    If only one element: all calls return it (repeat last).
    """
    mocks = []
    for row_result in execute_returns:
        result_mock = MagicMock()
        if hasattr(row_result, "__iter__"):
            result_mock.fetchall.return_value = list(row_result)
            result_mock.rowcount = len(list(row_result)) if hasattr(row_result, "__len__") else 0
        else:
            result_mock.rowcount = row_result

        session = AsyncMock()
        session.execute = AsyncMock(return_value=result_mock)
        session.commit = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        mocks.append(session)

    idx = [0]

    def _get_db():
        cm = MagicMock()
        i = min(idx[0], len(mocks) - 1)
        idx[0] += 1
        cm.__aenter__ = AsyncMock(return_value=mocks[i])
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    return _get_db


# ── on_vm_lxc_deleted ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_on_vm_lxc_deleted_no_rows():
    get_db = _db_mock_factory(0)
    with (
        patch("backend.plus.config_snapshots.cleanup.get_db", get_db),
        patch("backend.plus.config_snapshots.cleanup.write_audit_log", AsyncMock()) as mock_audit,
    ):
        count = await on_vm_lxc_deleted(1, "pve", 100, "qemu", None, "admin")

    assert count == 0
    mock_audit.assert_not_called()


@pytest.mark.asyncio
async def test_on_vm_lxc_deleted_with_rows_writes_audit():
    get_db = _db_mock_factory(3)
    mock_audit = AsyncMock()
    with (
        patch("backend.plus.config_snapshots.cleanup.get_db", get_db),
        patch("backend.plus.config_snapshots.cleanup.write_audit_log", mock_audit),
    ):
        count = await on_vm_lxc_deleted(1, "pve", 100, "qemu", "myvm", "admin")

    assert count == 3
    mock_audit.assert_called_once()
    args = mock_audit.call_args[0]
    assert args[0] == "config_snapshot_orphaned"


@pytest.mark.asyncio
async def test_on_vm_lxc_deleted_commits():
    session = AsyncMock()
    result_mock = MagicMock()
    result_mock.rowcount = 1
    session.execute = AsyncMock(return_value=result_mock)
    session.commit = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    def _get_db():
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    with (
        patch("backend.plus.config_snapshots.cleanup.get_db", _get_db),
        patch("backend.plus.config_snapshots.cleanup.write_audit_log", AsyncMock()),
    ):
        await on_vm_lxc_deleted(1, "pve", 100, "lxc", None, "admin")

    session.commit.assert_called_once()


# ── on_user_deleted_config_snapshots ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_on_user_deleted_nulls_and_commits():
    session = AsyncMock()
    result_mock = MagicMock()
    session.execute = AsyncMock(return_value=result_mock)
    session.commit = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    def _get_db():
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    with patch("backend.plus.config_snapshots.cleanup.get_db", _get_db):
        await on_user_deleted_config_snapshots(42)

    session.execute.assert_called_once()
    call_args = session.execute.call_args
    sql = str(call_args[0][0])
    assert "NULL" in sql or "created_by_user_id" in sql
    session.commit.assert_called_once()


# ── on_cluster_refresh_vanished_resources ─────────────────────────────────────

@pytest.mark.asyncio
async def test_vanished_resources_no_rows_does_nothing():
    rows: list = []

    session1 = AsyncMock()
    result1 = MagicMock()
    result1.fetchall.return_value = rows
    session1.execute = AsyncMock(return_value=result1)
    session1.__aenter__ = AsyncMock(return_value=session1)
    session1.__aexit__ = AsyncMock(return_value=False)

    call_count = [0]

    def _get_db():
        call_count[0] += 1
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session1)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    with patch("backend.plus.config_snapshots.cleanup.get_db", _get_db):
        await on_cluster_refresh_vanished_resources_config_snapshots(
            {(100, "pve", "qemu")}, portal_node_id=1
        )

    # Only the SELECT call happened, no UPDATE
    assert call_count[0] == 1


@pytest.mark.asyncio
async def test_vanished_resources_orphans_missing_vms():
    # Simulate DB has vmid=200 which is NOT in still_visible
    row = MagicMock()
    row.__getitem__ = lambda self, k: {"vmid": 200, "proxmox_node": "pve", "kind": "qemu"}[k]

    session1 = AsyncMock()
    result1 = MagicMock()
    result1.fetchall.return_value = [row]
    session1.execute = AsyncMock(return_value=result1)
    session1.__aenter__ = AsyncMock(return_value=session1)
    session1.__aexit__ = AsyncMock(return_value=False)

    session2 = AsyncMock()
    session2.execute = AsyncMock(return_value=MagicMock())
    session2.commit = AsyncMock()
    session2.__aenter__ = AsyncMock(return_value=session2)
    session2.__aexit__ = AsyncMock(return_value=False)

    sessions = [session1, session2]
    idx = [0]

    def _get_db():
        cm = MagicMock()
        i = min(idx[0], len(sessions) - 1)
        idx[0] += 1
        cm.__aenter__ = AsyncMock(return_value=sessions[i])
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    with patch("backend.plus.config_snapshots.cleanup.get_db", _get_db):
        await on_cluster_refresh_vanished_resources_config_snapshots(
            {(100, "pve", "qemu")},  # 200 is NOT here
            portal_node_id=1,
        )

    # Second session should have executed UPDATE
    session2.execute.assert_called_once()
    session2.commit.assert_called_once()


@pytest.mark.asyncio
async def test_vanished_resources_skips_visible_vms():
    row = MagicMock()
    row.__getitem__ = lambda self, k: {"vmid": 100, "proxmox_node": "pve", "kind": "qemu"}[k]

    session1 = AsyncMock()
    result1 = MagicMock()
    result1.fetchall.return_value = [row]
    session1.execute = AsyncMock(return_value=result1)
    session1.__aenter__ = AsyncMock(return_value=session1)
    session1.__aexit__ = AsyncMock(return_value=False)

    call_count = [0]

    def _get_db():
        call_count[0] += 1
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session1)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    with patch("backend.plus.config_snapshots.cleanup.get_db", _get_db):
        await on_cluster_refresh_vanished_resources_config_snapshots(
            {(100, "pve", "qemu")},  # 100 IS visible
            portal_node_id=1,
        )

    # Only the SELECT call; no UPDATE session opened
    assert call_count[0] == 1
