# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-76: Tests für den YAML-Diff-Walker (diff.py)."""
from __future__ import annotations

import pytest

from backend.plus.stacks.diff import _flatten, _parse, diff_yaml

pytestmark = pytest.mark.plus_only


def _by_change(entries):
    out = {"added": [], "removed": [], "changed": [], "unchanged": []}
    for e in entries:
        out[e.change].append(e.key)
    return out


def test_flatten_nested_dict():
    flat = _flatten({"a": {"b": 1}, "c": 2})
    assert flat == {"a.b": "1", "c": "2"}


def test_flatten_list_indexed():
    flat = _flatten({"resources": [{"name": "web"}]})
    assert flat["resources.0.name"] == "web"


def test_flatten_none_to_empty():
    assert _flatten({"x": None}) == {"x": ""}


def test_parse_invalid_yaml_returns_empty():
    assert _parse("a: [unterminated") == {}


def test_parse_non_mapping_returns_empty():
    assert _parse("- just\n- a\n- list") == {}


def test_diff_identical():
    y = "name: web\nversion: '1.0.0'\n"
    by = _by_change(diff_yaml(y, y))
    assert by["added"] == [] and by["removed"] == [] and by["changed"] == []
    assert "name" in by["unchanged"]


def test_diff_added_key():
    a = "name: web\n"
    b = "name: web\ndescription: x\n"
    by = _by_change(diff_yaml(a, b))
    assert "description" in by["added"]


def test_diff_removed_key():
    a = "name: web\ndescription: x\n"
    b = "name: web\n"
    by = _by_change(diff_yaml(a, b))
    assert "description" in by["removed"]


def test_diff_changed_value():
    a = "version: '1.0.0'\n"
    b = "version: '2.0.0'\n"
    by = _by_change(diff_yaml(a, b))
    assert "version" in by["changed"]


def test_diff_resource_count_change():
    a = "resources:\n  - name: web\n    count: 3\n"
    b = "resources:\n  - name: web\n    count: 2\n"
    by = _by_change(diff_yaml(a, b))
    assert "resources.0.count" in by["changed"]


def test_diff_includes_unchanged():
    a = "name: web\nversion: '1.0.0'\n"
    b = "name: web\nversion: '2.0.0'\n"
    keys = {e.key for e in diff_yaml(a, b)}
    assert "name" in keys and "version" in keys


def test_diff_int_str_normalization():
    a = "tag: 100\n"
    b = "tag: '100'\n"
    by = _by_change(diff_yaml(a, b))
    assert "tag" in by["unchanged"]
