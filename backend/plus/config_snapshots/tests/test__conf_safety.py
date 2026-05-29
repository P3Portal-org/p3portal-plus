# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-74: Tests für _conf_safety.py (Layer-3-Parser)."""
from __future__ import annotations

import pytest

from backend.plus.config_snapshots._conf_safety import (
    PROXMOX_QEMU_KEYS,
    PROXMOX_LXC_KEYS,
    UnsafeConfValue,
    ParsedConf,
    parse_conf_text,
)

pytestmark = pytest.mark.plus_only


# ── Key whitelists ────────────────────────────────────────────────────────────

def test_qemu_keys_frozenset():
    assert isinstance(PROXMOX_QEMU_KEYS, frozenset)
    assert "cores" in PROXMOX_QEMU_KEYS
    assert "memory" in PROXMOX_QEMU_KEYS
    assert "name" in PROXMOX_QEMU_KEYS
    assert "scsi0" in PROXMOX_QEMU_KEYS


def test_lxc_keys_frozenset():
    assert isinstance(PROXMOX_LXC_KEYS, frozenset)
    assert "hostname" in PROXMOX_LXC_KEYS
    assert "memory" in PROXMOX_LXC_KEYS
    assert "cores" in PROXMOX_LXC_KEYS


def test_unknown_key_not_in_either_whitelist():
    assert "completely_unknown_key_xyz" not in PROXMOX_QEMU_KEYS
    assert "completely_unknown_key_xyz" not in PROXMOX_LXC_KEYS


# ── parse_conf_text – basic ───────────────────────────────────────────────────

def test_parse_simple_qemu_conf():
    text = "cores: 4\nmemory: 2048\nname: testvm\n"
    result = parse_conf_text(text, kind="qemu")
    assert isinstance(result, ParsedConf)
    assert result.keys["cores"] == "4"
    assert result.keys["memory"] == "2048"
    assert result.keys["name"] == "testvm"


def test_parse_simple_lxc_conf():
    text = "hostname: mycontainer\nmemory: 512\ncores: 1\n"
    result = parse_conf_text(text, kind="lxc")
    assert result.keys["hostname"] == "mycontainer"
    assert result.keys["memory"] == "512"


def test_parse_description_extracted():
    text = "# My VM Description\n# Line two\ncores: 2\n"
    result = parse_conf_text(text, kind="qemu")
    assert result.description == "My VM Description\nLine two"
    assert "cores" in result.keys


def test_parse_unknown_keys_dropped():
    text = "cores: 2\nunknown_future_key_xyz: value\n"
    result = parse_conf_text(text, kind="qemu")
    assert "cores" in result.keys
    assert "unknown_future_key_xyz" not in result.keys


def test_parse_snap_section_stops_parsing():
    text = "cores: 2\n[snap-mysnap]\ncores: 1\n"
    result = parse_conf_text(text, kind="qemu")
    assert result.keys["cores"] == "2"


def test_parse_empty_text():
    result = parse_conf_text("", kind="qemu")
    assert result.keys == {}
    assert result.description == ""


def test_parse_only_comments():
    text = "# Just a description\n# More text\n"
    result = parse_conf_text(text, kind="qemu")
    assert result.description == "Just a description\nMore text"
    assert result.keys == {}


def test_parse_colon_in_value():
    text = "name: vm:test\n"
    result = parse_conf_text(text, kind="qemu")
    assert result.keys["name"] == "vm:test"


# ── UnsafeConfValue ───────────────────────────────────────────────────────────

def test_unsafe_conf_value_is_exception():
    exc = UnsafeConfValue("bad input")
    assert isinstance(exc, ValueError)


# ── Null byte / control char rejection ───────────────────────────────────────

def test_null_byte_in_value_rejected():
    text = "name: vm\x00bad\n"
    with pytest.raises(UnsafeConfValue):
        parse_conf_text(text, kind="qemu")


def test_control_char_in_value_rejected():
    text = "name: vm\x08bad\n"
    with pytest.raises(UnsafeConfValue):
        parse_conf_text(text, kind="qemu")
