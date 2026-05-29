# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-74: Tests für schemas.py (Pydantic-Schemas)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.plus.config_snapshots.schemas import (
    BulkIds,
    DiffEntry,
    RestoreIn,
    SnapshotIn,
    SnapshotOut,
    UploadOut,
)

pytestmark = pytest.mark.plus_only


# ── SnapshotIn ────────────────────────────────────────────────────────────────

def test_snapshot_in_minimal():
    s = SnapshotIn(note="before maintenance")
    assert s.note == "before maintenance"
    assert s.name is None


def test_snapshot_in_with_name():
    s = SnapshotIn(note="x", name="my-snap_1.0")
    assert s.name == "my-snap_1.0"


def test_snapshot_in_empty_note_rejected():
    with pytest.raises(ValidationError):
        SnapshotIn(note="")


def test_snapshot_in_note_too_long():
    with pytest.raises(ValidationError):
        SnapshotIn(note="x" * 501)


def test_snapshot_in_invalid_name_chars():
    with pytest.raises(ValidationError):
        SnapshotIn(note="ok", name="bad name!")


def test_snapshot_in_name_too_long():
    with pytest.raises(ValidationError):
        SnapshotIn(note="ok", name="a" * 81)


# ── SnapshotOut coerce_orphan ─────────────────────────────────────────────────

_SNAPSHOT_OUT_BASE = dict(
    id="abc",
    portal_node_id=1,
    proxmox_node="pve",
    vmid=100,
    kind="qemu",
    name="snap-1",
    note="test",
    description=None,
    source="portal",
    created_at="2026-01-01T00:00:00",
    created_by_user_id=1,
    is_orphan=0,
    orphaned_at=None,
    vm_name_at_delete=None,
)


def test_snapshot_out_orphan_int_coerced():
    s = SnapshotOut(**_SNAPSHOT_OUT_BASE)
    assert s.is_orphan is False


def test_snapshot_out_orphan_one_coerced():
    data = {**_SNAPSHOT_OUT_BASE, "is_orphan": 1}
    s = SnapshotOut(**data)
    assert s.is_orphan is True


# ── RestoreIn ─────────────────────────────────────────────────────────────────

def test_restore_in_defaults():
    r = RestoreIn(vm_name_confirm="testvm", etag="abc123")
    assert r.create_pre_restore_snapshot is True
    assert r.restart_after_restore is False


def test_restore_in_empty_vm_name_rejected():
    with pytest.raises(ValidationError):
        RestoreIn(vm_name_confirm="", etag="abc")


def test_restore_in_vm_name_too_long():
    with pytest.raises(ValidationError):
        RestoreIn(vm_name_confirm="a" * 81, etag="abc")


# ── DiffEntry ─────────────────────────────────────────────────────────────────

def test_diff_entry_added():
    d = DiffEntry(key="cores", snapshot_value="4", change="added")
    assert d.live_value is None
    assert d.snapshot_value == "4"


def test_diff_entry_removed():
    d = DiffEntry(key="name", live_value="oldvm", change="removed")
    assert d.snapshot_value is None


def test_diff_entry_changed():
    d = DiffEntry(key="memory", live_value="2048", snapshot_value="4096", change="changed")
    assert d.change == "changed"


# ── BulkIds ───────────────────────────────────────────────────────────────────

def test_bulk_ids_valid():
    b = BulkIds(ids=["id1", "id2"])
    assert len(b.ids) == 2


def test_bulk_ids_empty_rejected():
    with pytest.raises(ValidationError):
        BulkIds(ids=[])


def test_bulk_ids_too_many_rejected():
    with pytest.raises(ValidationError):
        BulkIds(ids=[f"id{i}" for i in range(201)])


# ── UploadOut ─────────────────────────────────────────────────────────────────

def test_upload_out():
    u = UploadOut(snapshot_id="uuid-1", warnings=["dropped: foo"], keys_dropped=1)
    assert u.keys_dropped == 1
    assert len(u.warnings) == 1
