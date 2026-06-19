# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-96: schema tests."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.plus.dependencies.schemas import DependencyIn, DependencyOut

pytestmark = pytest.mark.plus_only


def test_dependency_in_label_optional():
    d = DependencyIn(source_node_id=1, source_vmid=100, target_node_id=2, target_vmid=200)
    assert d.dep_label is None


def test_dependency_in_label_max_length():
    with pytest.raises(ValidationError):
        DependencyIn(
            source_node_id=1, source_vmid=100, target_node_id=2, target_vmid=200,
            dep_label="x" * 201,
        )


def test_dependency_out_coerces_stale_int_to_bool():
    out = DependencyOut(
        id=1, source_node_id=1, source_vmid=100, source_node="pve1", source_name=None,
        target_node_id=2, target_vmid=200, target_node="pve2", target_name=None,
        dep_label=None, created_at="t", created_by=None, stale=1, stale_at="t2",
    )
    assert out.stale is True
