# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-93: ansible-doc schema loader & cache (AC-MOD-1/2/3, § D/E)."""
from __future__ import annotations

import shutil

import pytest

from backend.plus.ansible_editor import doc_cache as dc

pytestmark = pytest.mark.plus_only

_HAS_ANSIBLE_DOC = shutil.which("ansible-doc") is not None


# ── Loader against the mini cache (deterministic, no ansible-doc) ─────────────


def test_list_modules_from_cache():
    mods = dc.list_modules()
    names = {m.name for m in mods}
    assert "ansible.builtin.copy" in names and "ansible.builtin.apt" in names
    # sorted by name
    assert [m.name for m in mods] == sorted(m.name for m in mods)
    apt = next(m for m in mods if m.name == "ansible.builtin.apt")
    assert apt.short_description == "Manages apt-packages"


def test_widget_mapping():
    by = {p.name: p for p in dc.module_schema("ansible.builtin.copy").params}
    assert by["dest"].widget == "text" and by["dest"].required is True
    assert by["mode"].widget == "text"  # type raw → text
    svc = {p.name: p for p in dc.module_schema("ansible.builtin.service").params}
    assert svc["state"].widget == "dropdown" and svc["state"].choices
    assert svc["enabled"].widget == "toggle"
    uri = {p.name: p for p in dc.module_schema("ansible.builtin.uri").params}
    assert uri["headers"].widget == "raw_yaml"  # type dict
    assert uri["status_code"].widget == "raw_yaml"  # type list
    assert uri["method"].widget == "dropdown"


def test_required_params_sorted_first():
    params = dc.module_schema("ansible.builtin.copy").params
    assert params[0].name == "dest" and params[0].required is True


def test_module_exists():
    assert dc.module_exists("ansible.builtin.copy") is True
    assert dc.module_exists("ansible.builtin.does_not_exist") is False
    assert dc.module_exists("community.general.foo") is False


def test_module_schema_bad_name_raises():
    with pytest.raises(dc.ModuleNotFound):
        dc.module_schema("not_a_module")


# ── rST markup stripping (§ D) ────────────────────────────────────────────────


def test_strip_markup():
    s = dc._strip_markup("Run C(apt-get update), see M(ansible.builtin.apt) and V(latest).")
    assert "C(" not in s and "M(" not in s and "V(" not in s
    assert "apt-get update" in s and "ansible.builtin.apt" in s and "latest" in s
    assert dc._strip_markup("a HORIZONTALLINE b") == "a b"


def test_norm_choices_dict_to_list():
    assert dc._norm_choices({"all": "x", "no": "y"}) == ["all", "no"]
    assert dc._norm_choices(["a", "b"]) == ["a", "b"]
    assert dc._norm_choices(None) is None


# ── Cache-miss fallback / build against the real ansible-doc ───────────────────


@pytest.mark.skipif(not _HAS_ANSIBLE_DOC, reason="ansible-doc not installed")
def test_build_cache_and_load(tmp_path, monkeypatch):
    cache = tmp_path / "real-cache"
    monkeypatch.setenv("P3_ANSIBLE_DOC_CACHE_DIR", str(cache))
    dc._reset_cache()
    count = dc.build_cache()
    assert count > 50  # ~71 core modules
    assert (cache / "_modules.json").is_file()
    dc._reset_cache()
    sch = dc.module_schema("ansible.builtin.copy")
    assert any(p.name == "dest" and p.required for p in sch.params)


@pytest.mark.skipif(not _HAS_ANSIBLE_DOC, reason="ansible-doc not installed")
def test_cache_miss_fallback(tmp_path, monkeypatch):
    # Empty cache dir → loader falls back to a live ansible-doc subprocess.
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("P3_ANSIBLE_DOC_CACHE_DIR", str(empty))
    dc._reset_cache()
    sch = dc.module_schema("ansible.builtin.service")
    by = {p.name: p for p in sch.params}
    assert by["state"].widget == "dropdown"
