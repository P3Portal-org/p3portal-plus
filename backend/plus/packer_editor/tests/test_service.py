# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-92: file-based CRUD/service tests. AC-HOST-3 / AC-ROUND / EC-1/2/11 / § E/G."""
from __future__ import annotations

import json

import pytest
import yaml

from backend.plus.packer_editor import service
from backend.plus.packer_editor.schemas import PackerEditorModel
from backend.plus.packer_editor.service import (
    DefinitionExists,
    DefinitionNotFound,
    ForeignDefinition,
)

pytestmark = pytest.mark.plus_only


def _iso_model(**overrides) -> PackerEditorModel:
    base = dict(
        id="deb13",
        name="Debian 13",
        description="test build",
        required_role="operator",
        source={"type": "proxmox-iso", "ssh_private_key_name": "sysadm"},
        installer={
            "os_profile": "debian-preseed",
            "root_password_plain": "changeme123",
            "ssh_public_key": "ssh-ed25519 AAAA svc",
        },
        provisioners=[{"type": "file", "source_name": "cloud.cfg", "source_content": "# cfg", "destination": "/tmp/c"}],
        side_files={"sysadm": "PRIVKEY"},
    )
    base.update(overrides)
    return PackerEditorModel(**base)


def test_create_writes_full_directory(patch_packer_dir):
    service.save_definition(_iso_model(), is_update=False)
    d = patch_packer_dir / "deb13"
    assert (d / "deb13.pkr.hcl").is_file()
    assert not (d / "deb13.pkr.json").exists()  # HCL is the primary format
    assert (d / "meta.yaml").is_file()
    assert (d / "http" / "preseed.cfg").is_file()
    assert (d / "files" / "cloud.cfg").is_file()
    assert (d / "files" / "sysadm").is_file()
    assert (d / ".p3editor.json").is_file()  # Sidecar marker


def test_definition_is_valid_hcl(patch_packer_dir):
    service.save_definition(_iso_model(), is_update=False)
    text = (patch_packer_dir / "deb13" / "deb13.pkr.hcl").read_text()
    assert 'source "proxmox-iso" "builder" {' in text
    assert "build {" in text
    assert 'variable "vm_id" {' in text


def test_resave_clears_stale_pkrjson(patch_packer_dir):
    """A definition carrying a legacy .pkr.json is cleaned on re-save (EC-2)."""
    d = patch_packer_dir / "deb13"
    service.save_definition(_iso_model(), is_update=False)
    (d / "deb13.pkr.json").write_text("{}")  # simulate a pre-HCL leftover
    service.save_definition(_iso_model(), is_update=True)
    assert (d / "deb13.pkr.hcl").is_file()
    assert not (d / "deb13.pkr.json").exists()


def test_meta_yaml_has_standard_params(patch_packer_dir):
    service.save_definition(_iso_model(), is_update=False)
    meta = yaml.safe_load((patch_packer_dir / "deb13" / "meta.yaml").read_text())
    ids = {p["id"] for p in meta["parameters"]}
    assert ids == {"vm_id", "vm_name", "node", "storage_pool", "iso_file"}
    assert meta["required_role"] == "operator"
    # no credential leaked as a parameter
    assert "proxmox_api_token_secret" not in ids


def test_clone_meta_omits_iso_file(patch_packer_dir):
    m = PackerEditorModel(id="cl1", name="Clone", source={"type": "proxmox-clone", "clone_template": "t"})
    service.save_definition(m, is_update=False)
    meta = yaml.safe_load((patch_packer_dir / "cl1" / "meta.yaml").read_text())
    ids = {p["id"] for p in meta["parameters"]}
    assert "iso_file" not in ids


def test_password_never_persisted_plain(patch_packer_dir):
    """§ E / § M: plain password is hashed server-side; Sidecar + preseed only hold $6$."""
    service.save_definition(_iso_model(), is_update=False)
    sidecar = (patch_packer_dir / "deb13" / ".p3editor.json").read_text()
    preseed = (patch_packer_dir / "deb13" / "http" / "preseed.cfg").read_text()
    assert "changeme123" not in sidecar
    assert "changeme123" not in preseed
    assert "$6$" in preseed
    # the sidecar stores the hash, plain is null
    payload = json.loads(sidecar)
    assert payload["model"]["installer"]["root_password_plain"] is None
    assert payload["model"]["installer"]["root_password_hash"].startswith("$6$")


def test_roundtrip_get_returns_model(patch_packer_dir):
    service.save_definition(_iso_model(), is_update=False)
    loaded = service.get_definition("deb13")
    assert loaded is not None
    assert loaded.id == "deb13"
    assert loaded.source.type == "proxmox-iso"
    assert loaded.installer.os_profile == "debian-preseed"
    assert loaded.side_files["sysadm"] == "PRIVKEY"


def test_list_only_editor_managed(patch_packer_dir):
    # editor definition
    service.save_definition(_iso_model(), is_update=False)
    # foreign (ZIP/Git) definition: directory + meta.yaml, NO sidecar
    foreign = patch_packer_dir / "foreign-tmpl"
    foreign.mkdir()
    (foreign / "foreign.pkr.hcl").write_text("# hcl")
    (foreign / "meta.yaml").write_text("name: x\ndescription: y\n")

    listing = service.list_definitions()
    ids = {d.id for d in listing}
    assert "deb13" in ids
    assert "foreign-tmpl" not in ids  # AC-ROUND-2: foreign not listed


def test_create_collision_editor_managed_raises_exists(patch_packer_dir):
    service.save_definition(_iso_model(), is_update=False)
    with pytest.raises(DefinitionExists):
        service.save_definition(_iso_model(), is_update=False)


def test_create_collision_foreign_raises_foreign(patch_packer_dir):
    # EC-1 / § G: foreign directory (no marker) is never overwritten
    foreign = patch_packer_dir / "deb13"
    foreign.mkdir()
    (foreign / "deb13.pkr.hcl").write_text("# foreign")
    with pytest.raises(ForeignDefinition):
        service.save_definition(_iso_model(), is_update=False)
    # foreign file untouched
    assert (foreign / "deb13.pkr.hcl").read_text() == "# foreign"


def test_update_requires_editor_managed(patch_packer_dir):
    with pytest.raises(DefinitionNotFound):
        service.save_definition(_iso_model(), is_update=True)


def test_update_cleans_orphan_side_files(patch_packer_dir):
    # EC-2: a file no longer referenced is removed on update
    service.save_definition(_iso_model(), is_update=False)
    assert (patch_packer_dir / "deb13" / "files" / "cloud.cfg").is_file()
    # update without the file provisioner
    service.save_definition(_iso_model(provisioners=[], side_files={}), is_update=True)
    assert not (patch_packer_dir / "deb13" / "files" / "cloud.cfg").exists()
    assert not (patch_packer_dir / "deb13" / "files" / "sysadm").exists()


def test_delete_editor_definition(patch_packer_dir):
    service.save_definition(_iso_model(), is_update=False)
    assert service.delete_definition("deb13") is True
    assert not (patch_packer_dir / "deb13").exists()


def test_delete_missing_returns_false(patch_packer_dir):
    assert service.delete_definition("nope") is False


def test_delete_foreign_blocked(patch_packer_dir):
    # EC-11: editor never deletes a foreign definition
    foreign = patch_packer_dir / "foreign"
    foreign.mkdir()
    (foreign / "foreign.pkr.hcl").write_text("# x")
    with pytest.raises(ForeignDefinition):
        service.delete_definition("foreign")
    assert foreign.exists()


def test_is_editor_managed(patch_packer_dir):
    service.save_definition(_iso_model(), is_update=False)
    assert service.is_editor_managed("deb13") is True
    assert service.is_editor_managed("nope") is False
