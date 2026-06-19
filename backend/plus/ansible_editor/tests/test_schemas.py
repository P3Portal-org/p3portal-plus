# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-93: schema validation (Pydantic-422 layer, AC-EDIT-2 / AC-VAL-1/2)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.plus.ansible_editor.schemas import (
    AnsibleEditorModel,
    AnsiblePlayHeader,
    AnsibleTask,
)

pytestmark = pytest.mark.plus_only


def _model(**kw):
    base = dict(id="pb1", name="PB", tasks=[])
    base.update(kw)
    return AnsibleEditorModel(**base)


# ── id pattern ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("good", ["nginx-setup", "pb1", "my.playbook.v2", "a_b-c.1"])
def test_id_accepts_valid(good):
    assert _model(id=good).id == good


@pytest.mark.parametrize("bad", ["", "../etc", "a/b", "a..b", "-leading", ".dot", "x" * 65, "spaces here"])
def test_id_rejects_invalid(bad):
    with pytest.raises(ValidationError):
        _model(id=bad)


# ── module FQCN pattern ───────────────────────────────────────────────────────


def test_task_module_must_be_core_fqcn():
    AnsibleTask(module="ansible.builtin.copy")  # ok
    for bad in ["copy", "community.general.foo", "ansible.builtin.Copy", "ansible.builtin."]:
        with pytest.raises(ValidationError):
            AnsibleTask(module=bad)


# ── register_var (renamed to avoid BaseModel.register shadow) ──────────────────


def test_register_var_validation():
    AnsibleTask(module="ansible.builtin.copy", register_var="result")  # ok
    with pytest.raises(ValidationError):
        AnsibleTask(module="ansible.builtin.copy", register_var="2bad name")


def test_register_var_round_trips_in_dump():
    t = AnsibleTask(module="ansible.builtin.copy", register_var="out")
    assert t.model_dump()["register_var"] == "out"


# ── params caps ───────────────────────────────────────────────────────────────


def test_params_reject_nul_byte():
    with pytest.raises(ValidationError):
        AnsibleTask(module="ansible.builtin.copy", params={"content": "a\x00b"})


def test_params_accept_typed_and_jinja_values():
    t = AnsibleTask(
        module="ansible.builtin.copy",
        params={"mode": "0644", "src": "{{ my_src }}", "force": True, "n": 3, "headers": {"a": "b"}},
    )
    assert t.params["force"] is True and t.params["n"] == 3


# ── side_files ────────────────────────────────────────────────────────────────


def test_side_files_name_hardening():
    _model(side_files={"index.html": "x"})  # ok
    for bad in {"../evil": "x"}, {"a/b": "x"}, {"..": "x"}:
        with pytest.raises(ValidationError):
            _model(side_files=bad)


# ── category ──────────────────────────────────────────────────────────────────


def test_category_whitelist():
    assert _model(category="vm_lxc_config").category == "vm_lxc_config"
    assert _model(category="").category is None
    assert _model(category=None).category is None
    with pytest.raises(ValidationError):
        _model(category="nonsense")


# ── header defaults ───────────────────────────────────────────────────────────


def test_header_defaults_to_guest():
    h = AnsiblePlayHeader()
    assert h.targets == "guest" and h.become is False and h.gather_facts is False
