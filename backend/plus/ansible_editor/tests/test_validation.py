# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-93: hard_validate (against the schema cache) + semantic_warnings (§ K)."""
from __future__ import annotations

import pytest

from backend.plus.ansible_editor.schemas import (
    AnsibleEditorModel,
    AnsiblePlayHeader,
    AnsibleTask,
)
from backend.plus.ansible_editor.validation import hard_validate, semantic_warnings

pytestmark = pytest.mark.plus_only


def _m(tasks, **kw):
    base = dict(id="pb", name="PB", tasks=tasks)
    base.update(kw)
    return AnsibleEditorModel(**base)


# ── hard_validate ─────────────────────────────────────────────────────────────


def test_unknown_module_is_blocking():
    m = _m([AnsibleTask(module="ansible.builtin.does_not_exist")])
    errs = hard_validate(m)
    assert errs and "existiert nicht" in errs[0]


def test_missing_required_param_is_blocking():
    # copy.dest is required in the mini cache
    m = _m([AnsibleTask(name="cp", module="ansible.builtin.copy", params={"src": "x"})])
    errs = hard_validate(m)
    assert any("dest" in e for e in errs)


def test_required_param_filled_passes():
    m = _m([AnsibleTask(module="ansible.builtin.copy", params={"dest": "/etc/x"})])
    assert hard_validate(m) == []


def test_required_param_with_jinja_passes():
    m = _m([AnsibleTask(module="ansible.builtin.copy", params={"dest": "{{ target }}"})])
    assert hard_validate(m) == []


def test_required_param_empty_string_fails():
    m = _m([AnsibleTask(module="ansible.builtin.copy", params={"dest": "  "})])
    assert any("dest" in e for e in hard_validate(m))


def test_valid_multi_task_playbook_passes():
    m = _m([
        AnsibleTask(module="ansible.builtin.apt", params={"name": "nginx"}),
        AnsibleTask(module="ansible.builtin.service", params={"name": "nginx"}),
    ])
    assert hard_validate(m) == []


# ── semantic_warnings ─────────────────────────────────────────────────────────


def test_empty_playbook_warns():
    assert any("keine Tasks" in w for w in semantic_warnings(_m([])))


def test_task_without_name_warns():
    m = _m([AnsibleTask(module="ansible.builtin.ping", params={})])
    assert any("ohne Namen" in w for w in semantic_warnings(m))


def test_unknown_param_warns_not_blocks():
    m = _m([AnsibleTask(name="t", module="ansible.builtin.copy",
                        params={"dest": "/x", "totally_made_up": "v"})])
    warns = semantic_warnings(m)
    assert any("totally_made_up" in w for w in warns)
    assert hard_validate(m) == []  # unknown param does not block


def test_localhost_hint():
    m = _m([], header=AnsiblePlayHeader(targets="localhost"))
    assert any("localhost" in w.lower() for w in semantic_warnings(m))


def test_missing_referenced_side_file_warns():
    m = _m([AnsibleTask(name="t", module="ansible.builtin.copy",
                        params={"dest": "/x", "src": "files/missing.html"})])
    assert any("missing.html" in w for w in semantic_warnings(m))


def test_present_side_file_no_warning():
    m = _m([AnsibleTask(name="t", module="ansible.builtin.copy",
                        params={"dest": "/x", "src": "files/ok.html"})],
           side_files={"ok.html": "x"})
    assert not any("ok.html" in w for w in semantic_warnings(m))
