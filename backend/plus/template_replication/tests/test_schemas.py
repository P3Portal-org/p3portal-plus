# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-101: Schema-Validierung."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.plus.template_replication.schemas import ReplicateRequest, ReplicationTarget

pytestmark = pytest.mark.plus_only


def test_target_rejects_bad_storage():
    with pytest.raises(ValidationError):
        ReplicationTarget(node="pve2", storage="bad;rm -rf")


def test_target_rejects_bad_node():
    with pytest.raises(ValidationError):
        ReplicationTarget(node="pve 2$", storage="local-lvm")


def test_target_newid_range():
    with pytest.raises(ValidationError):
        ReplicationTarget(node="pve2", storage="local-lvm", newid=42)
    assert ReplicationTarget(node="pve2", storage="local-lvm", newid=101).newid == 101


def test_request_requires_at_least_one_target():
    with pytest.raises(ValidationError):
        ReplicateRequest(source_node="pve1", source_vmid=100, targets=[])


def test_request_defaults_remove_source_off():
    r = ReplicateRequest(source_node="pve1", source_vmid=100,
                         targets=[ReplicationTarget(node="pve2", storage="local-lvm")])
    assert r.remove_source_after_shared is False
