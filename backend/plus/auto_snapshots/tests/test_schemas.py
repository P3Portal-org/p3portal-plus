# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-77: Pydantic-Schema-Tests (TargetSpec, AutoConfigJobConfig, AutoVmJobConfig)."""
import pytest
from pydantic import ValidationError

from backend.plus.auto_snapshots.schemas import (
    AutoConfigJobConfig, AutoVmJobConfig, RunSummary,
    SingleTarget, TargetSpec,
)

pytestmark = pytest.mark.plus_only


def test_target_spec_requires_at_least_one_source():
    with pytest.raises(ValidationError):
        TargetSpec()


def test_target_spec_singles_ok():
    spec = TargetSpec(singles=[SingleTarget(portal_node_id=1, vmid=100, kind="qemu")])
    assert spec.singles[0].vmid == 100
    assert spec.kind_filter == "both"


def test_target_spec_max_tags():
    with pytest.raises(ValidationError):
        TargetSpec(tags=[f"t{i}" for i in range(11)])


def test_target_spec_strips_empty_tags():
    spec = TargetSpec(tags=["prod", " ", "", "db"])
    assert spec.tags == ["prod", "db"]


def test_auto_config_job_defaults():
    cfg = AutoConfigJobConfig(
        target_spec=TargetSpec(portal_node_ids=[1]),
    )
    assert cfg.keep_last == 7
    assert cfg.skip_if_no_changes is True
    assert cfg.max_parallel == 5
    assert cfg.gfs_enabled is False


def test_auto_config_job_keep_last_bounds():
    with pytest.raises(ValidationError):
        AutoConfigJobConfig(
            target_spec=TargetSpec(portal_node_ids=[1]), keep_last=0,
        )
    with pytest.raises(ValidationError):
        AutoConfigJobConfig(
            target_spec=TargetSpec(portal_node_ids=[1]), keep_last=101,
        )


def test_auto_vm_job_include_ram_default_false():
    cfg = AutoVmJobConfig(target_spec=TargetSpec(pool_ids=[1]))
    assert cfg.include_ram is False


def test_gfs_enabled_requires_tier_value():
    with pytest.raises(ValidationError):
        AutoConfigJobConfig(
            target_spec=TargetSpec(portal_node_ids=[1]),
            gfs_enabled=True, keep_daily=0, keep_weekly=0, keep_monthly=0,
        )


def test_max_parallel_bounds():
    with pytest.raises(ValidationError):
        AutoVmJobConfig(target_spec=TargetSpec(pool_ids=[1]), max_parallel=11)


def test_run_summary_defaults():
    s = RunSummary(status="success")
    assert s.created_count == 0
    assert s.failed_details == []
