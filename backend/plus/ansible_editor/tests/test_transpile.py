# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-93: transpile model → playbook (§ F/G, AC-JINJA / AC-LEVEL / AC-YAML).

Includes the reference acceptance anchor (3-task nginx-setup, § P): byte-stable
output + a real ``ansible-playbook --syntax-check`` (skipped if absent)."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml

from backend.plus.ansible_editor.schemas import (
    AnsibleEditorModel,
    AnsiblePlayHeader,
    AnsibleTask,
)
from backend.plus.ansible_editor.transpile import build_play, transpile

pytestmark = pytest.mark.plus_only


def _m(**kw):
    base = dict(id="pb", name="PB")
    base.update(kw)
    return AnsibleEditorModel(**base)


# ── hosts line per target (§ G) ───────────────────────────────────────────────


def test_hosts_managed_for_guest():
    play = build_play(_m(header=AnsiblePlayHeader(targets="guest", become=True)))[0]
    assert play["hosts"] == "managed" and play["become"] is True
    assert play["gather_facts"] is False


def test_hosts_localhost_for_localhost():
    play = build_play(_m(header=AnsiblePlayHeader(targets="localhost")))[0]
    assert play["hosts"] == "localhost"
    assert "become" not in play  # not emitted when False


# ── task-level fields only when set (AC-LEVEL-2) ──────────────────────────────


def test_task_minimal_omits_empty_control_fields():
    t = AnsibleTask(name="ping", module="ansible.builtin.ping", params={})
    td = build_play(_m(tasks=[t]))[0]["tasks"][0]
    assert td == {"name": "ping", "ansible.builtin.ping": {}}


def test_task_level_fields_emitted_with_correct_keys():
    t = AnsibleTask(
        name="svc", module="ansible.builtin.service",
        params={"name": "nginx", "state": "started"},
        when="ok", register_var="res", become=True, tags=["web"], notify=["reload nginx"],
        loop="{{ items }}",
    )
    td = build_play(_m(tasks=[t]))[0]["tasks"][0]
    assert td["when"] == "ok"
    assert td["register"] == "res"  # register_var → YAML key 'register'
    assert td["become"] is True
    assert td["tags"] == ["web"]
    assert td["notify"] == "reload nginx"  # single → string
    assert td["loop"] == "{{ items }}"


def test_notify_multiple_stays_list():
    t = AnsibleTask(module="ansible.builtin.ping", notify=["a", "b"])
    td = build_play(_m(tasks=[t]))[0]["tasks"][0]
    assert td["notify"] == ["a", "b"]


def test_become_false_is_emitted_but_none_is_not():
    f = build_play(_m(tasks=[AnsibleTask(module="ansible.builtin.ping", become=False)]))[0]["tasks"][0]
    assert f["become"] is False
    n = build_play(_m(tasks=[AnsibleTask(module="ansible.builtin.ping")]))[0]["tasks"][0]
    assert "become" not in n


# ── Jinja verbatim (AC-JINJA-2) ───────────────────────────────────────────────


def test_jinja_value_round_trips_verbatim():
    t = AnsibleTask(module="ansible.builtin.copy", params={"dest": "{{ target_path }}", "mode": "0644"})
    yaml_text, _ = transpile(_m(tasks=[t]))
    parsed = yaml.safe_load(yaml_text)
    cp = parsed[0]["tasks"][0]["ansible.builtin.copy"]
    assert cp["dest"] == "{{ target_path }}"  # string, not evaluated
    assert cp["mode"] == "0644"  # stays a string (no octal coercion)


# ── side-files → files/ ───────────────────────────────────────────────────────


def test_side_files_go_under_files_dir():
    _, files = transpile(_m(side_files={"index.html": "<h1>x</h1>"}))
    assert files == {"files/index.html": "<h1>x</h1>"}


# ── empty playbook (EC-1) ─────────────────────────────────────────────────────


def test_empty_playbook_yields_valid_play():
    yaml_text, _ = transpile(_m(tasks=[]))
    parsed = yaml.safe_load(yaml_text)
    assert parsed[0]["tasks"] == []


# ── Reference acceptance anchor (§ P) ─────────────────────────────────────────


def _nginx_model():
    return AnsibleEditorModel(
        id="nginx-setup", name="Nginx Setup", category="vm_lxc_config",
        header=AnsiblePlayHeader(targets="guest", become=True, gather_facts=False),
        tasks=[
            AnsibleTask(name="nginx installieren", module="ansible.builtin.apt",
                        params={"name": "nginx", "state": "present", "update_cache": True}),
            AnsibleTask(name="index.html kopieren", module="ansible.builtin.copy",
                        params={"src": "files/index.html", "dest": "/var/www/html/index.html",
                                "owner": "www-data", "mode": "0644"}),
            AnsibleTask(name="nginx aktivieren", module="ansible.builtin.service",
                        params={"name": "nginx", "state": "started", "enabled": True}),
        ],
        side_files={"index.html": "<h1>P3 Portal</h1>\n"},
    )


def test_reference_nginx_structure():
    yaml_text, files = transpile(_nginx_model())
    parsed = yaml.safe_load(yaml_text)
    play = parsed[0]
    assert play["name"] == "Nginx Setup" and play["hosts"] == "managed" and play["become"] is True
    assert [list(t.keys())[1] for t in play["tasks"]] == [
        "ansible.builtin.apt", "ansible.builtin.copy", "ansible.builtin.service",
    ]
    assert files["files/index.html"] == "<h1>P3 Portal</h1>\n"


def test_reference_byte_stable():
    a, _ = transpile(_nginx_model())
    b, _ = transpile(_nginx_model())
    assert a == b  # same model → identical YAML


@pytest.mark.skipif(shutil.which("ansible-playbook") is None, reason="ansible-playbook not installed")
def test_reference_passes_syntax_check():
    yaml_text, _ = transpile(_nginx_model())
    with tempfile.TemporaryDirectory() as tmp:
        pb = Path(tmp) / "nginx-setup.yml"
        pb.write_text(yaml_text)
        proc = subprocess.run(
            ["ansible-playbook", "--syntax-check", str(pb)],
            capture_output=True, text=True, timeout=30,
        )
    assert proc.returncode == 0, proc.stderr or proc.stdout
