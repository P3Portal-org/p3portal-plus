# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-92: semantic-validation tests (non-blocking warnings). AC-VAL-1 / EC-4/6/7."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.plus.packer_editor.schemas import PackerEditorModel
from backend.plus.packer_editor.validation import semantic_warnings

pytestmark = pytest.mark.plus_only


def _iso(**ov) -> PackerEditorModel:
    base = dict(id="x", name="X", source={"type": "proxmox-iso"})
    base.update(ov)
    return PackerEditorModel(**base)


def test_iso_without_installer_warns():
    w = semantic_warnings(_iso())
    assert any("ohne Installer" in x for x in w)


def test_iso_with_installer_no_installer_warning():
    m = _iso(installer={"os_profile": "debian-preseed", "root_password_hash": "$6$x"})
    w = semantic_warnings(m)
    assert not any("ohne Installer" in x for x in w)


def test_raw_override_warns():
    m = _iso(installer={"os_profile": "debian-preseed", "raw_override": True, "raw_content": "# x"})
    w = semantic_warnings(m)
    assert any("Freitext-Override" in x for x in w)


def test_boot_command_not_referencing_installer_warns():
    m = _iso(
        source={"type": "proxmox-iso", "boot_command": ["<enter>", "auto"]},
        installer={"os_profile": "debian-preseed", "root_password_hash": "$6$x"},
    )
    w = semantic_warnings(m)
    assert any("boot_command" in x for x in w)


def test_boot_command_referencing_installer_ok():
    m = _iso(
        source={"type": "proxmox-iso", "boot_command": ["preseed.cfg"]},
        installer={"os_profile": "debian-preseed", "root_password_hash": "$6$x"},
    )
    w = semantic_warnings(m)
    assert not any("boot_command" in x for x in w)


def test_provisioner_without_ssh_key_warns():
    m = _iso(
        installer={"os_profile": "debian-preseed", "root_password_hash": "$6$x"},
        provisioners=[{"type": "shell", "mode": "inline", "inline": ["echo hi"]}],
    )
    w = semantic_warnings(m)
    assert any("ssh_private_key_name" in x for x in w)


def test_ssh_key_not_in_side_files_warns():
    m = _iso(
        source={"type": "proxmox-iso", "ssh_private_key_name": "sysadm"},
        installer={"os_profile": "debian-preseed", "root_password_hash": "$6$x"},
    )
    w = semantic_warnings(m)
    assert any("nicht vorhanden" in x for x in w)


def test_ssh_key_present_in_side_files_ok():
    m = _iso(
        source={"type": "proxmox-iso", "ssh_private_key_name": "sysadm"},
        installer={"os_profile": "debian-preseed", "root_password_hash": "$6$x"},
        side_files={"sysadm": "KEY"},
    )
    w = semantic_warnings(m)
    assert not any("nicht vorhanden" in x for x in w)


def test_empty_ansible_playbook_warns():
    m = _iso(
        source={"type": "proxmox-iso", "ssh_private_key_name": "k"},
        installer={"os_profile": "debian-preseed", "root_password_hash": "$6$x"},
        side_files={"k": "K"},
        provisioners=[{"type": "ansible", "playbook_name": "p.yml", "playbook_content": "   "}],
    )
    w = semantic_warnings(m)
    assert any("leeres Playbook" in x for x in w)


# ── Hard validation (Pydantic 422) ────────────────────────────────────────────


def test_invalid_id_rejected():
    with pytest.raises(ValidationError):
        PackerEditorModel(id="../escape", name="X", source={"type": "proxmox-iso"})


def test_installer_on_clone_rejected():
    with pytest.raises(ValidationError):
        PackerEditorModel(
            id="x", name="X",
            source={"type": "proxmox-clone", "clone_template": "t"},
            installer={"os_profile": "debian-preseed"},
        )


def test_invalid_side_file_name_rejected():
    with pytest.raises(ValidationError):
        PackerEditorModel(id="x", name="X", source={"type": "proxmox-iso"},
                          side_files={"../evil": "x"})


def test_invalid_script_name_rejected():
    with pytest.raises(ValidationError):
        PackerEditorModel(
            id="x", name="X", source={"type": "proxmox-iso"},
            provisioners=[{"type": "shell", "mode": "script", "script_name": "../e", "script_content": "x"}],
        )


def test_ssh_public_key_newline_rejected():
    with pytest.raises(ValidationError):
        PackerEditorModel(
            id="x", name="X", source={"type": "proxmox-iso"},
            installer={"os_profile": "debian-preseed", "ssh_public_key": "key\ninjected"},
        )


def test_source_type_default_injected():
    """Pydantic-v2 discriminated-union gotcha: missing source.type defaults to iso."""
    m = PackerEditorModel(id="x", name="X", source={"cores": 2})
    assert m.source.type == "proxmox-iso"
    assert m.source.cores == 2
