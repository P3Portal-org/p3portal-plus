# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-74: Tests für service.py (Config-Snapshot-Service)."""
from __future__ import annotations

import hashlib
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from backend.plus.config_snapshots.service import (
    _diff_dicts,
    _etag_of,
    get_snapshot,
    list_snapshots,
)

pytestmark = pytest.mark.plus_only


# ── _etag_of ─────────────────────────────────────────────────────────────────

def test_etag_of_deterministic():
    payload = {"cores": "4", "memory": "2048"}
    assert _etag_of(payload) == _etag_of(payload)


def test_etag_of_canonical_sorted_keys():
    a = {"b": "2", "a": "1"}
    b = {"a": "1", "b": "2"}
    assert _etag_of(a) == _etag_of(b)


def test_etag_of_is_sha256():
    payload = {"x": "y"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    expected = hashlib.sha256(canonical.encode()).hexdigest()
    assert _etag_of(payload) == expected


def test_etag_of_different_payloads():
    assert _etag_of({"a": "1"}) != _etag_of({"a": "2"})


def test_etag_of_empty_payload():
    result = _etag_of({})
    assert len(result) == 64  # SHA-256 hex length


# ── _diff_dicts ──────────────────────────────────────────────────────────────

def test_diff_dicts_identical():
    diff = _diff_dicts({"a": "1"}, {"a": "1"})
    assert len(diff) == 1
    assert diff[0].key == "a"
    assert diff[0].change == "unchanged"
    assert diff[0].snapshot_value == "1"
    assert diff[0].live_value == "1"


def test_diff_dicts_changed_value():
    diff = _diff_dicts({"cores": "2"}, {"cores": "4"})
    assert len(diff) == 1
    assert diff[0].key == "cores"
    assert diff[0].change == "changed"
    assert diff[0].snapshot_value == "2"
    assert diff[0].live_value == "4"


def test_diff_dicts_key_in_live_only():
    diff = _diff_dicts({}, {"name": "vm"})
    assert len(diff) == 1
    assert diff[0].change == "added"
    assert diff[0].live_value == "vm"
    assert diff[0].snapshot_value is None


def test_diff_dicts_key_removed_from_live():
    diff = _diff_dicts({"name": "vm"}, {})
    assert len(diff) == 1
    assert diff[0].change == "removed"
    assert diff[0].snapshot_value == "vm"
    assert diff[0].live_value is None


def test_diff_dicts_sorted_by_key():
    diff = _diff_dicts({"z": "1"}, {"a": "1", "z": "2"})
    keys = [d.key for d in diff]
    assert keys == sorted(keys)


def test_diff_dicts_multiple_changes():
    snap = {"a": "1", "b": "2", "c": "3"}
    live = {"a": "1", "b": "X", "d": "4"}
    diff = _diff_dicts(snap, live)
    changes = {d.key: d.change for d in diff}
    assert changes["b"] == "changed"
    assert changes["c"] == "removed"
    assert changes["d"] == "added"
    assert changes["a"] == "unchanged"


# ── get_snapshot ─────────────────────────────────────────────────────────────

def _make_snapshot_row():
    row = MagicMock()
    row.__getitem__ = lambda self, k: {
        "id": "snap-1",
        "portal_node_id": 1,
        "proxmox_node": "pve",
        "vmid": 100,
        "kind": "qemu",
        "name": "test-snap",
        "note": "before maintenance",
        "description": None,
        "source": "manual",
        "created_at": "2026-01-01T00:00:00",
        "created_by_user_id": None,
        "is_orphan": 0,
        "orphaned_at": None,
        "vm_name_at_delete": None,
        "payload_json": json.dumps({"cores": "4"}),
    }[k]
    return row


@pytest.mark.asyncio
async def test_get_snapshot_not_found_raises_404():
    session = AsyncMock()
    result_mock = MagicMock()
    result_mock.mappings.return_value.fetchone.return_value = None
    session.execute = AsyncMock(return_value=result_mock)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    def _get_db():
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    with (
        patch("backend.plus.config_snapshots.service.get_db", _get_db),
        pytest.raises(HTTPException) as exc_info,
    ):
        await get_snapshot("nonexistent")

    assert exc_info.value.status_code == 404
    assert "snapshot_not_found" in exc_info.value.detail


@pytest.mark.asyncio
async def test_get_snapshot_returns_detail():
    row = _make_snapshot_row()

    session = AsyncMock()
    result_mock = MagicMock()
    result_mock.mappings.return_value.fetchone.return_value = row
    result_mock.mappings.return_value.fetchall.return_value = []  # username lookup
    session.execute = AsyncMock(return_value=result_mock)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    call_count = [0]

    def _get_db():
        call_count[0] += 1
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    with patch("backend.plus.config_snapshots.service.get_db", _get_db):
        detail = await get_snapshot("snap-1")

    assert detail.id == "snap-1"
    assert detail.vmid == 100
    assert "cores" in detail.payload


# ── list_snapshots ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_snapshots_empty():
    session = AsyncMock()
    result_mock = MagicMock()
    result_mock.mappings.return_value.fetchall.return_value = []
    session.execute = AsyncMock(return_value=result_mock)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    def _get_db():
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    with patch("backend.plus.config_snapshots.service.get_db", _get_db):
        result = await list_snapshots(1, "pve", 100, "qemu")

    assert result == []


@pytest.mark.asyncio
async def test_list_snapshots_returns_rows():
    row = _make_snapshot_row()

    sessions: list = []
    for _ in range(2):
        s = AsyncMock()
        r = MagicMock()
        r.mappings.return_value.fetchall.return_value = [row] if _ == 0 else []
        s.execute = AsyncMock(return_value=r)
        s.__aenter__ = AsyncMock(return_value=s)
        s.__aexit__ = AsyncMock(return_value=False)
        sessions.append(s)

    idx = [0]

    def _get_db():
        cm = MagicMock()
        i = min(idx[0], len(sessions) - 1)
        idx[0] += 1
        cm.__aenter__ = AsyncMock(return_value=sessions[i])
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    with patch("backend.plus.config_snapshots.service.get_db", _get_db):
        result = await list_snapshots(1, "pve", 100, "qemu")

    assert len(result) == 1
    assert result[0].id == "snap-1"
