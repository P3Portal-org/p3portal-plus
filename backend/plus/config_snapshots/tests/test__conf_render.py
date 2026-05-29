# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-74: Tests für _conf_render.py (conf-Serializer)."""
from __future__ import annotations

import pytest

from backend.plus.config_snapshots._conf_render import render_conf

pytestmark = pytest.mark.plus_only


def test_empty_keys_no_description():
    result = render_conf({}, description="")
    assert result == ""


def test_keys_only_no_description():
    result = render_conf({"cores": "4", "memory": "2048"})
    lines = result.rstrip("\n").splitlines()
    assert lines == ["cores: 4", "memory: 2048"]


def test_alphabetic_sort():
    result = render_conf({"name": "vm", "cores": "2", "agent": "1"})
    lines = result.rstrip("\n").splitlines()
    assert lines[0].startswith("agent:")
    assert lines[1].startswith("cores:")
    assert lines[2].startswith("name:")


def test_description_only():
    result = render_conf({}, description="My VM")
    lines = result.splitlines()
    assert lines[0] == "# My VM"
    assert lines[1] == ""  # blank separator


def test_description_and_keys():
    result = render_conf({"cores": "2"}, description="desc")
    lines = result.rstrip("\n").splitlines()
    assert lines[0] == "# desc"
    assert lines[1] == ""
    assert lines[2] == "cores: 2"


def test_multi_line_description():
    result = render_conf({}, description="Line one\nLine two")
    lines = result.splitlines()
    assert lines[0] == "# Line one"
    assert lines[1] == "# Line two"
    assert lines[2] == ""


def test_blank_line_in_description_becomes_hash():
    result = render_conf({}, description="before\n\nafter")
    lines = result.rstrip("\n").splitlines()
    assert lines[0] == "# before"
    assert lines[1] == "#"
    assert lines[2] == "# after"


def test_output_ends_with_newline():
    result = render_conf({"x": "1"})
    assert result.endswith("\n")


def test_colon_in_value():
    result = render_conf({"name": "vm:test"})
    assert "name: vm:test" in result


def test_single_key_output():
    result = render_conf({"agent": "enabled=1"})
    assert result.strip() == "agent: enabled=1"
