# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-77: Tests für GFS-Tier-Berechnung + Retention-Logik (rotation.py)."""
from datetime import datetime, timezone

import pytest

from backend.plus.auto_snapshots.rotation import (
    _bucket_keys, determine_keep_set,
)

pytestmark = pytest.mark.plus_only


# ─── Bucket-Keys ────────────────────────────────────────────────────────────


def test_bucket_keys_format_iso_week_and_month():
    dt = datetime(2026, 5, 29, 12, 30, tzinfo=timezone.utc)
    w, m = _bucket_keys(dt)
    # ISO Week: 2026 KW22
    assert w == "2026-W22"
    assert m == "2026-05"


def test_bucket_keys_year_boundary():
    # 30. Dez 2025 ist ISO-Year 2026, Week 1 (Donnerstag)
    dt = datetime(2025, 12, 30, 0, 0, tzinfo=timezone.utc)
    w, _ = _bucket_keys(dt)
    assert w == "2026-W01"


# ─── Retention: determine_keep_set ──────────────────────────────────────────


def _snap(sid: str, *tiers: str) -> dict:
    return {"id": sid, "gfs_tiers": list(tiers), "created_at": "2026-05-29T12:00:00+00:00"}


def test_keep_last_floor_only():
    snaps = [_snap("a"), _snap("b"), _snap("c"), _snap("d"), _snap("e")]
    # keep_last=2 → nur die jüngsten 2
    keep = determine_keep_set(snaps, keep_last=2, keep_daily=0, keep_weekly=0, keep_monthly=0)
    assert keep == {"a", "b"}


def test_keep_zero_drops_everything():
    snaps = [_snap("a"), _snap("b")]
    keep = determine_keep_set(snaps, keep_last=0, keep_daily=0, keep_weekly=0, keep_monthly=0)
    assert keep == set()


def test_gfs_union_with_keep_last():
    # 5 daily, 2 weekly, 1 monthly Snapshot mit Überlappung
    snaps = [
        _snap("d1", "daily", "weekly", "monthly"),
        _snap("d2", "daily", "weekly"),
        _snap("d3", "daily"),
        _snap("d4", "daily"),
        _snap("d5", "daily"),
    ]
    # keep_last=2 + keep_daily=3 + keep_weekly=1 + keep_monthly=1
    keep = determine_keep_set(snaps, keep_last=2, keep_daily=3, keep_weekly=1, keep_monthly=1)
    # keep_last: d1, d2
    # daily-Pool[:3]: d1, d2, d3
    # weekly-Pool[:1]: d1
    # monthly-Pool[:1]: d1
    # Union: {d1, d2, d3}
    assert keep == {"d1", "d2", "d3"}


def test_gfs_disabled_keep_n_zero_means_no_pool():
    snaps = [_snap("a", "daily"), _snap("b", "daily"), _snap("c", "daily")]
    keep = determine_keep_set(snaps, keep_last=1, keep_daily=0, keep_weekly=0, keep_monthly=0)
    assert keep == {"a"}


def test_keep_last_more_than_available():
    snaps = [_snap("a"), _snap("b")]
    keep = determine_keep_set(snaps, keep_last=10, keep_daily=0, keep_weekly=0, keep_monthly=0)
    assert keep == {"a", "b"}
