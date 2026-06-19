# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-92: transpile tests (pure fn, no Packer/Proxmox). AC-VAL-2 / AC-REF-1.

HCL is the primary output format (user choice). These tests assert on the
generated ``.pkr.hcl`` text + injection safety (EC-9).
"""
from __future__ import annotations

import pytest

from backend.plus.packer_editor.schemas import PackerEditorModel
from backend.plus.packer_editor.transpile import (
    _PLUGIN_SOURCE,
    _PLUGIN_VERSION,
    stack_to_hcl,
)

pytestmark = pytest.mark.plus_only


def _iso_model(**overrides) -> PackerEditorModel:
    base = dict(
        id="deb13",
        name="Debian 13",
        source={
            "type": "proxmox-iso",
            "cores": 1,
            "memory_mb": 1024,
            "disk_size_gb": 20,
            "network_bridge": "vmbr0",
            "ssh_private_key_name": "sysadm",
        },
        installer={
            "os_profile": "debian-preseed",
            "root_password_hash": "$6$x$y",
            "ssh_public_key": "ssh-ed25519 AAAA svc",
        },
        provisioners=[
            {"type": "shell", "mode": "inline", "inline": ["echo a", "echo b"]},
            {"type": "file", "source_name": "cloud.cfg", "source_content": "# cfg", "destination": "/tmp/cloud.cfg"},
        ],
        side_files={"sysadm": "PRIVKEY"},
    )
    base.update(overrides)
    return PackerEditorModel(**base)


def test_required_plugins_pinned():
    hcl, _ = stack_to_hcl(_iso_model())
    assert "required_plugins {" in hcl
    assert f'"version" = "{_PLUGIN_VERSION}"' in hcl
    assert f'"source" = "{_PLUGIN_SOURCE}"' in hcl


def test_variable_blocks_match_reference():
    """The variable set must match the hand-written debian-13 HCL so the -var
    runner injection works unchanged (Tech-Design § A)."""
    hcl, _ = stack_to_hcl(_iso_model())
    for name in (
        "proxmox_api_url", "proxmox_api_token_id", "proxmox_api_token_secret",
        "proxmox_api_user", "proxmox_api_password",
        "vm_id", "vm_name", "node", "storage_pool", "packer_http_ip", "iso_file",
    ):
        assert f'variable "{name}" {{' in hcl
    # sensitive flags preserved (token secret + password)
    assert hcl.count("sensitive = true") == 2
    # type is a bare HCL keyword, not a quoted string
    assert "type = string" in hcl
    assert 'type = "string"' not in hcl


def test_clone_omits_iso_file_variable():
    m = PackerEditorModel(
        id="clone1", name="Clone", source={"type": "proxmox-clone", "clone_template": "ubuntu-tmpl"}
    )
    hcl, _ = stack_to_hcl(m)
    assert 'variable "iso_file"' not in hcl
    assert 'source "proxmox-clone" "builder" {' in hcl
    assert 'clone_vm = "ubuntu-tmpl"' in hcl


def test_credentials_wired_as_expressions_not_inline():
    """No inline credentials — both auth modes via ternary expressions (AC-SRC-2)."""
    hcl, _ = stack_to_hcl(_iso_model())
    # bare expressions (not quoted strings)
    assert "proxmox_url = var.proxmox_api_url" in hcl
    assert 'username = var.proxmox_api_user != "" ? var.proxmox_api_user : var.proxmox_api_token_id' in hcl
    assert 'token = var.proxmox_api_user != "" ? "" : var.proxmox_api_token_secret' in hcl
    assert 'password = var.proxmox_api_user != "" ? var.proxmox_api_password : ""' in hcl


def test_build_param_wiring():
    hcl, _ = stack_to_hcl(_iso_model())
    assert "node = var.node" in hcl
    assert "vm_id = var.vm_id" in hcl
    assert 'vm_name = "tmpl-${var.vm_name}"' in hcl
    assert "storage_pool = var.storage_pool" in hcl
    assert "iso_file = var.iso_file" in hcl


def test_http_content_uses_file_not_templatefile():
    """SSH key already inlined → file() not templatefile() (Tech-Design § D)."""
    hcl, _ = stack_to_hcl(_iso_model())
    assert '"/preseed.cfg" = file("${path.root}/http/preseed.cfg")' in hcl
    assert "templatefile" not in hcl


def test_boot_command_wires_preseed_url():
    hcl, _ = stack_to_hcl(_iso_model())
    assert "preseed/url=http://${var.packer_http_ip}:{{ .HTTPPort }}/preseed.cfg" in hcl


def test_provisioner_order_and_types():
    hcl, _ = stack_to_hcl(_iso_model())
    # shell block appears before the file block
    shell_at = hcl.index('provisioner "shell" {')
    file_at = hcl.index('provisioner "file" {')
    assert shell_at < file_at
    assert '"echo a"' in hcl and '"echo b"' in hcl
    assert 'source = "files/cloud.cfg"' in hcl
    assert 'destination = "/tmp/cloud.cfg"' in hcl


def test_shell_script_mode_references_file():
    m = _iso_model(provisioners=[
        {"type": "shell", "mode": "script", "script_name": "setup.sh", "script_content": "#!/bin/sh\necho hi"},
    ])
    hcl, files = stack_to_hcl(m)
    assert 'script = "files/setup.sh"' in hcl
    assert files["files/setup.sh"] == "#!/bin/sh\necho hi"


def test_ansible_provisioner_extra_vars():
    m = _iso_model(provisioners=[
        {"type": "ansible", "playbook_name": "play.yml", "playbook_content": "- hosts: all",
         "extra_vars": {"foo": "bar"}},
    ])
    hcl, files = stack_to_hcl(m)
    assert 'provisioner "ansible" {' in hcl
    assert 'playbook_file = "files/play.yml"' in hcl
    assert '"--extra-vars"' in hcl and '"foo=bar"' in hcl
    assert files["files/play.yml"] == "- hosts: all"


def test_side_files_generated():
    _, files = stack_to_hcl(_iso_model())
    assert files["files/sysadm"] == "PRIVKEY"
    assert files["files/cloud.cfg"] == "# cfg"
    assert "http/preseed.cfg" in files


def test_ssh_private_key_file_wired():
    hcl, _ = stack_to_hcl(_iso_model())
    assert 'ssh_private_key_file = "${path.root}/files/sysadm"' in hcl


def test_iso_without_installer_has_no_http_content():
    m = _iso_model(installer=None)
    hcl, files = stack_to_hcl(m)
    assert "http_content" not in hcl
    assert not any(k.startswith("http/") for k in files)


def test_build_name_is_id():
    hcl, _ = stack_to_hcl(_iso_model())
    assert 'name = "deb13"' in hcl
    assert '"source.proxmox-iso.builder"' in hcl


def test_ubuntu_http_content_and_files_have_user_and_meta_data():
    """Ubuntu autoinstall wires + writes two http files (user-data + meta-data)."""
    m = _iso_model(installer={
        "os_profile": "ubuntu-autoinstall",
        "root_password_hash": "$6$x$y",
        "ssh_public_key": "ssh-ed25519 AAAA svc",
    })
    hcl, files = stack_to_hcl(m)
    assert '"/user-data" = file("${path.root}/http/user-data")' in hcl
    assert '"/meta-data" = file("${path.root}/http/meta-data")' in hcl
    assert "http/user-data" in files
    assert "http/meta-data" in files
    assert files["http/user-data"].startswith("#cloud-config")
    assert files["http/meta-data"] == ""


def test_hcl_override_returns_verbatim_with_generated_files():
    """HCL raw-override: hcl_content is returned verbatim; side-files (preseed,
    provisioner files) are still generated from the structured model."""
    m = _iso_model(hcl_override=True, hcl_content='source "proxmox-iso" "x" {\n  custom = true\n}\n')
    hcl, files = stack_to_hcl(m)
    assert hcl == 'source "proxmox-iso" "x" {\n  custom = true\n}\n'
    # structured generation is bypassed (no auto packer{} header)
    assert "required_plugins" not in hcl
    # but the referenced side-files are still generated
    assert "http/preseed.cfg" in files
    assert files["files/sysadm"] == "PRIVKEY"
    assert files["files/cloud.cfg"] == "# cfg"


def test_hcl_override_empty_falls_back_to_generation():
    """An empty hcl_content does not override (full structured generation)."""
    m = _iso_model(hcl_override=True, hcl_content="   ")
    hcl, _ = stack_to_hcl(m)
    assert "required_plugins" in hcl  # generated, not the (blank) override


def test_user_value_cannot_break_out_of_string_ec9():
    """EC-9: a user value with quotes / ${...} stays inside its HCL string
    literal (escaped) — no HCL structure injection."""
    m = _iso_model()
    m.source.template_description = 'evil" \n attacker = "x'
    hcl, _ = stack_to_hcl(m)
    # the embedded quote is escaped → cannot open a new attribute
    assert 'template_description = "evil\\" \\n attacker = \\"x"' in hcl
    assert "\n attacker = " not in hcl  # no raw newline-injected attribute
