# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-77: Tests für handlers.py-Hilfsfunktionen (Snapname-Format, Status-Bewertung)."""
from datetime import datetime, timezone

import pytest

from backend.plus.auto_snapshots.handlers import (
    _determine_overall_status, _hash_payload, _job_id_short, build_snapname,
)
from backend.plus.auto_snapshots.models import SNAP_NAME_PREFIX
from backend.plus.auto_snapshots.schemas import FailedDetail, RunSummary

pytestmark = pytest.mark.plus_only


# ─── Snapname-Format ────────────────────────────────────────────────────────


def test_job_id_short_strips_dashes_and_truncates():
    raw = "abcdef12-3456-7890-1234-567890abcdef"
    assert _job_id_short(raw) == "abcdef12"


def test_build_snapname_format():
    now = datetime(2026, 5, 29, 12, 45, tzinfo=timezone.utc)
    name = build_snapname("abcdef1234567890" * 2, now)
    assert name.startswith(SNAP_NAME_PREFIX)
    assert name == f"{SNAP_NAME_PREFIX}abcdef12_20260529_1245"


def test_build_snapname_with_seconds_suffix():
    now = datetime(2026, 5, 29, 12, 45, 7, tzinfo=timezone.utc)
    name = build_snapname("abcdef1234567890" * 2, now, suffix_seconds=True)
    assert name.endswith("_07")


# ─── Hash-Stabilität ────────────────────────────────────────────────────────


def test_hash_payload_stable_key_order():
    a = _hash_payload({"x": 1, "a": 2})
    b = _hash_payload({"a": 2, "x": 1})
    assert a == b


def test_hash_payload_different_for_different_content():
    assert _hash_payload({"x": 1}) != _hash_payload({"x": 2})


# ─── Status-Bewertung ───────────────────────────────────────────────────────


def test_status_success_when_all_created():
    s = RunSummary(status="success", targets_total=3, created_count=3)
    assert _determine_overall_status(s) == "success"


def test_status_skipped_when_no_targets():
    s = RunSummary(status="success", targets_total=0)
    assert _determine_overall_status(s) == "skipped"


def test_status_partial_when_some_failed_some_created():
    s = RunSummary(
        status="success", targets_total=3, created_count=2, failed_count=1,
        failed_details=[FailedDetail(node="n", vmid=1, error_class="x", error_msg="y")],
    )
    assert _determine_overall_status(s) == "partial_success"


def test_status_failed_when_all_failed():
    s = RunSummary(status="success", targets_total=2, failed_count=2)
    assert _determine_overall_status(s) == "failed"


def test_status_skipped_when_all_owner_skipped():
    s = RunSummary(status="success", targets_total=2, skipped_not_owner_count=2)
    assert _determine_overall_status(s) == "skipped"


def test_status_success_when_all_skipped_no_change():
    s = RunSummary(status="success", targets_total=3, skipped_no_change_count=3)
    assert _determine_overall_status(s) == "success"
