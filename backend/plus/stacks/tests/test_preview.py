# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-76: Tests für preview.py (count → Suffix-Auflösung)."""
from __future__ import annotations

import pytest

from backend.plus.stacks.preview import resolve_resources, resolved_resource_dicts
from backend.plus.stacks.schemas import StackSpec, VMResource

pytestmark = pytest.mark.plus_only


def _spec(resources):
    return StackSpec(name="webcluster", resources=resources)


def test_count_one_no_suffix():
    spec = _spec([VMResource(name="web", node="pve", template="deb12", count=1)])
    res = resolve_resources(spec)
    assert [r.name for r in res] == ["web"]


def test_count_many_suffix():
    spec = _spec([VMResource(name="web", node="pve", template="deb12", count=3)])
    res = resolve_resources(spec)
    assert [r.name for r in res] == ["web-1", "web-2", "web-3"]


def test_mixed_resources():
    spec = _spec([
        VMResource(name="lb-01", node="pve", template="deb12", count=1),
        VMResource(name="web", node="pve", template="deb12", count=3),
    ])
    res = resolve_resources(spec)
    assert [r.name for r in res] == ["lb-01", "web-1", "web-2", "web-3"]


def test_resource_count_total():
    spec = _spec([VMResource(name="web", node="pve", template="deb12", count=4)])
    assert len(resolve_resources(spec)) == 4


def test_resolved_dicts_drop_count():
    spec = _spec([VMResource(name="web", node="pve", template="deb12", count=2)])
    dicts = resolved_resource_dicts(spec)
    assert all("count" not in d for d in dicts)
    assert {d["name"] for d in dicts} == {"web-1", "web-2"}


def test_preview_carries_node_template():
    spec = _spec([VMResource(name="web", node="pve-01", template="deb12", cores=4, memory=8192)])
    res = resolve_resources(spec)
    assert res[0].node == "pve-01"
    assert res[0].template == "deb12"
    assert res[0].cores == 4
