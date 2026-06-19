# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-93: file-based CRUD + marker/collision/orphan logic (§ J, AC-ROUND/EC)."""
from __future__ import annotations

import pytest
import yaml

from backend.plus.ansible_editor import service
from backend.plus.ansible_editor.schemas import (
    AnsibleEditorModel,
    AnsiblePlayHeader,
    AnsibleTask,
)
from backend.plus.ansible_editor.service import (
    DefinitionExists,
    DefinitionNotFound,
    ForeignDefinition,
)

pytestmark = pytest.mark.plus_only


def _m(id="pb1", **kw):
    base = dict(
        id=id, name="PB", category="vm_lxc_config",
        header=AnsiblePlayHeader(targets="guest", become=True),
        tasks=[AnsibleTask(name="cp", module="ansible.builtin.copy",
                           params={"dest": "/x", "src": "files/a.txt"})],
        side_files={"a.txt": "hello"},
    )
    base.update(kw)
    return AnsibleEditorModel(**base)


# ── save / load / list ────────────────────────────────────────────────────────


def test_save_creates_full_definition(isolated_env):
    service.save_definition(_m(), is_update=False)
    d = isolated_env / "pb1"
    assert (d / ".p3editor.json").is_file()
    assert (d / "pb1.yml").is_file()
    assert (d / "meta.yaml").is_file()
    assert (d / "files" / "a.txt").read_text() == "hello"
    # the generated yml is valid + hosts: managed
    play = yaml.safe_load((d / "pb1.yml").read_text())
    assert play[0]["hosts"] == "managed"


def test_meta_yaml_content(isolated_env):
    service.save_definition(_m(), is_update=False)
    meta = yaml.safe_load((isolated_env / "pb1" / "meta.yaml").read_text())
    assert meta["playbook"] == "pb1.yml"
    assert meta["targets"] == "guest" and meta["become"] is True
    assert meta["category"] == "vm_lxc_config"
    assert meta["parameters"] == []  # MVP empty (AC-META-2)


def test_round_trip_load():
    service.save_definition(_m(), is_update=False)
    loaded = service.get_definition("pb1")
    assert loaded is not None
    assert loaded.id == "pb1" and loaded.tasks[0].module == "ansible.builtin.copy"
    assert loaded.side_files == {"a.txt": "hello"}


def test_list_only_editor_managed(isolated_env):
    service.save_definition(_m(id="pb1"), is_update=False)
    # a foreign (ZIP/Git) playbook: a dir with meta.yaml but NO sidecar
    foreign = isolated_env / "foreign"
    foreign.mkdir()
    (foreign / "meta.yaml").write_text("name: x\ndescription: y\nplaybook: foreign.yml\n")
    defs = service.list_definitions()
    assert [d.id for d in defs] == ["pb1"]
    assert defs[0].targets == "guest" and defs[0].task_count == 1


# ── collision / marker (AC-ROUND-2, EC-4) ─────────────────────────────────────


def test_create_existing_editor_managed_raises():
    service.save_definition(_m(), is_update=False)
    with pytest.raises(DefinitionExists):
        service.save_definition(_m(), is_update=False)


def test_create_foreign_dir_raises(isolated_env):
    foreign = isolated_env / "pb1"
    foreign.mkdir()
    (foreign / "meta.yaml").write_text("name: x\n")
    with pytest.raises(ForeignDefinition):
        service.save_definition(_m(id="pb1"), is_update=False)
    # the foreign meta.yaml is untouched
    assert (foreign / "meta.yaml").read_text() == "name: x\n"


def test_update_requires_editor_managed():
    with pytest.raises(DefinitionNotFound):
        service.save_definition(_m(), is_update=True)


def test_update_overwrites_managed():
    service.save_definition(_m(), is_update=False)
    service.save_definition(_m(name="Renamed"), is_update=True)
    assert service.get_definition("pb1").name == "Renamed"


# ── orphan cleanup (EC-12) ────────────────────────────────────────────────────


def test_orphan_side_file_removed_on_resave(isolated_env):
    service.save_definition(_m(side_files={"old.txt": "x", "a.txt": "hello"}), is_update=False)
    assert (isolated_env / "pb1" / "files" / "old.txt").is_file()
    service.save_definition(_m(side_files={"a.txt": "hello"}), is_update=True)
    assert not (isolated_env / "pb1" / "files" / "old.txt").exists()
    assert (isolated_env / "pb1" / "files" / "a.txt").is_file()


# ── delete (EC-6) ─────────────────────────────────────────────────────────────


def test_delete_managed():
    service.save_definition(_m(), is_update=False)
    assert service.delete_definition("pb1") is True
    assert service.get_definition("pb1") is None


def test_delete_nonexistent_returns_false():
    assert service.delete_definition("nope") is False


def test_delete_foreign_raises(isolated_env):
    foreign = isolated_env / "fz"
    foreign.mkdir()
    (foreign / "meta.yaml").write_text("name: x\n")
    with pytest.raises(ForeignDefinition):
        service.delete_definition("fz")
    assert foreign.is_dir()  # never deleted
