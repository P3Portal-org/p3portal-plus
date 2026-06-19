# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-92: Pydantic model for the Packer Visual Editor.

The structured ``PackerEditorModel`` is the Source of Truth. It is persisted
verbatim as the ``.p3editor.json`` Sidecar and transpiled (pure fn) into a
native HCL2-JSON ``.pkr.json`` + side-files.

Design notes (Tech-Design § B/C/E):
  * Source is a discriminated union (``proxmox-clone`` | ``proxmox-iso``) on the
    ``type`` field. A ``before``-validator injects the discriminator default to
    sidestep the Pydantic-v2 discriminated-union gotcha (a ``Literal=default``
    alone does NOT satisfy the discriminator if ``type`` is absent in the input;
    Stacks S631/632 lesson).
  * Build parameters (vm_id/vm_name/node/storage_pool/iso_file) are **never**
    in the model — they are ``var.*`` wired by the transpiler and emitted into
    ``meta.yaml`` to be filled per build. The model holds only the **fixed**
    definition values (cores/memory/disk/bridge/qemu_agent/cloud_init/...).
  * Installer passwords arrive as ``*_password_plain`` (transient, never
    persisted) → service.py hashes them server-side (sha512-crypt) into
    ``*_password_hash`` (the only thing the Sidecar stores).
"""
from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# id charset — reused from the core packer_service convention (no traversal).
_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
# Side-file / script / playbook names: a single safe path segment, no traversal.
_FILE_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")
# Caps for side-file / installer content (EC-8: very large files).
_MAX_FILE_BYTES = 256 * 1024
_MAX_FILE_LINES = 20_000
_MAX_INLINE_LINE_LEN = 8 * 1024
_MAX_INLINE_LINES = 2_000


def _check_text_caps(value: str, *, field: str) -> str:
    if len(value.encode("utf-8")) > _MAX_FILE_BYTES:
        raise ValueError(f"{field}: content exceeds {_MAX_FILE_BYTES} bytes")
    if value.count("\n") > _MAX_FILE_LINES:
        raise ValueError(f"{field}: content exceeds {_MAX_FILE_LINES} lines")
    if "\x00" in value:
        raise ValueError(f"{field}: content contains a NUL byte")
    return value


# ── Source ──────────────────────────────────────────────────────────────────


class _SourceBase(BaseModel):
    """Fixed VM settings common to both proxmox-clone and proxmox-iso."""

    model_config = ConfigDict(extra="ignore")

    cores: int = Field(default=1, ge=1, le=512)
    memory_mb: int = Field(default=1024, ge=128, le=4_194_304)
    disk_size_gb: int = Field(default=20, ge=1, le=131_072)
    network_bridge: str = Field(default="vmbr0", max_length=64)
    network_model: str = Field(default="virtio", max_length=32)
    network_firewall: bool = False
    scsi_controller: str = Field(default="virtio-scsi-pci", max_length=32)
    qemu_agent: bool = True
    cloud_init: bool = True
    template_description: str = Field(default="", max_length=512)
    # SSH connection used to provision the build VM (both source types need it
    # when provisioners run; matches the debian-13 reference root+key setup).
    ssh_username: str = Field(default="root", max_length=64)
    ssh_timeout: str = Field(default="20m", max_length=16)
    # Private key file referenced from files/ (e.g. "sysadm"); empty → none.
    ssh_private_key_name: str = Field(default="", max_length=128)

    @field_validator("ssh_private_key_name")
    @classmethod
    def _check_key_name(cls, v: str) -> str:
        if v and not _FILE_NAME_RE.match(v):
            raise ValueError(f"invalid ssh_private_key_name: {v!r}")
        return v


class CloneSource(_SourceBase):
    type: Literal["proxmox-clone"] = "proxmox-clone"
    # Source template to clone from (proxmox-clone `clone_vm`). Free text +
    # dropdown in the UI; build params still drive node/vm_id/vm_name.
    clone_template: str = Field(min_length=1, max_length=128)
    full_clone: bool = True


class IsoSource(_SourceBase):
    type: Literal["proxmox-iso"] = "proxmox-iso"
    boot_command: list[str] = Field(default_factory=list, max_length=64)
    boot_wait: str = Field(default="5s", max_length=16)
    http_port: int = Field(default=8103, ge=1, le=65535)

    @field_validator("boot_command")
    @classmethod
    def _cap_boot_command(cls, v: list[str]) -> list[str]:
        for line in v:
            if len(line) > _MAX_INLINE_LINE_LEN:
                raise ValueError("boot_command line too long")
        return v


Source = Annotated[Union[CloneSource, IsoSource], Field(discriminator="type")]


# ── Installer (proxmox-iso only) ──────────────────────────────────────────────


class InstallerBlock(BaseModel):
    """OS-profile driven installer (Debian preseed / RHEL kickstart).

    Mandatory fields are typed; optional fields live in ``optional`` (add/remove
    kit). ``raw_override`` switches to the free-text content as the truth
    (one-way Form→Text, no reverse parse — Tech-Design § E).
    """

    model_config = ConfigDict(extra="ignore")

    os_profile: Literal["debian-preseed", "rhel-kickstart", "ubuntu-autoinstall"]
    # Mandatory typed fields (grounded in preseed.cfg.tpl).
    language: str = Field(default="en", max_length=16)
    country: str = Field(default="US", max_length=8)
    locale: str = Field(default="en_US.UTF-8", max_length=32)
    keyboard: str = Field(default="us", max_length=16)
    timezone: str = Field(default="UTC", max_length=64)
    hostname: str = Field(default="", max_length=64)
    # Passwords: plain is transient (write-only, hashed server-side, never
    # persisted); hash is what the Sidecar stores ($6$… sha512-crypt).
    root_password_plain: Optional[str] = Field(default=None, max_length=512)
    root_password_hash: Optional[str] = Field(default=None, max_length=512)
    username: str = Field(default="sysadm", max_length=32)
    user_uid: int = Field(default=1000, ge=0, le=65535)
    user_password_plain: Optional[str] = Field(default=None, max_length=512)
    user_password_hash: Optional[str] = Field(default=None, max_length=512)
    packages: list[str] = Field(default_factory=lambda: ["sudo", "openssh-server", "qemu-guest-agent"])
    ssh_public_key: str = Field(default="", max_length=4096)
    # Optional fields (kit): apt_mirror, ntp_server, extra_late_commands[],
    # partition_recipe, extra_packages[], etc. Free-form by key.
    optional: dict[str, Any] = Field(default_factory=dict)
    # Free-text override (CodeMirror). When raw_override=True, raw_content is the
    # truth and the form fields are read-only in the UI.
    raw_override: bool = False
    raw_content: str = ""

    @field_validator("packages")
    @classmethod
    def _cap_packages(cls, v: list[str]) -> list[str]:
        if len(v) > 256:
            raise ValueError("too many packages (max 256)")
        for p in v:
            if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9._+-]{0,127}$", p):
                raise ValueError(f"invalid package name: {p!r}")
        return v

    @field_validator("ssh_public_key")
    @classmethod
    def _ssh_key_no_newline(cls, v: str) -> str:
        if "\n" in v or "\r" in v:
            raise ValueError("ssh_public_key must be a single line")
        return v

    @field_validator("raw_content")
    @classmethod
    def _cap_raw(cls, v: str) -> str:
        return _check_text_caps(v, field="raw_content")


# ── Provisioners ──────────────────────────────────────────────────────────────


class ShellProvisioner(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: Literal["shell"] = "shell"
    mode: Literal["inline", "script"] = "inline"
    inline: list[str] = Field(default_factory=list)
    script_name: Optional[str] = Field(default=None, max_length=128)
    script_content: str = ""

    @field_validator("inline")
    @classmethod
    def _cap_inline(cls, v: list[str]) -> list[str]:
        if len(v) > _MAX_INLINE_LINES:
            raise ValueError("too many inline shell lines")
        for line in v:
            if len(line) > _MAX_INLINE_LINE_LEN:
                raise ValueError("inline shell line too long")
        return v

    @field_validator("script_name")
    @classmethod
    def _check_script_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _FILE_NAME_RE.match(v):
            raise ValueError(f"invalid script_name: {v!r}")
        return v

    @field_validator("script_content")
    @classmethod
    def _cap_script(cls, v: str) -> str:
        return _check_text_caps(v, field="script_content")

    @model_validator(mode="after")
    def _check_mode(self) -> "ShellProvisioner":
        if self.mode == "inline" and not self.inline:
            raise ValueError("shell provisioner (inline) needs at least one command")
        if self.mode == "script" and not self.script_name:
            raise ValueError("shell provisioner (script) needs a script_name")
        return self


class FileProvisioner(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: Literal["file"] = "file"
    source_name: str = Field(min_length=1, max_length=128)
    source_content: str = ""
    destination: str = Field(min_length=1, max_length=512)

    @field_validator("source_name")
    @classmethod
    def _check_source_name(cls, v: str) -> str:
        if not _FILE_NAME_RE.match(v):
            raise ValueError(f"invalid source_name: {v!r}")
        return v

    @field_validator("source_content")
    @classmethod
    def _cap_content(cls, v: str) -> str:
        return _check_text_caps(v, field="source_content")

    @field_validator("destination")
    @classmethod
    def _check_destination(cls, v: str) -> str:
        if "\n" in v or "\x00" in v:
            raise ValueError("invalid destination")
        return v


class AnsibleProvisioner(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: Literal["ansible"] = "ansible"
    playbook_name: str = Field(min_length=1, max_length=128)
    playbook_content: str = ""
    extra_vars: dict[str, str] = Field(default_factory=dict)

    @field_validator("playbook_name")
    @classmethod
    def _check_playbook_name(cls, v: str) -> str:
        if not _FILE_NAME_RE.match(v):
            raise ValueError(f"invalid playbook_name: {v!r}")
        return v

    @field_validator("playbook_content")
    @classmethod
    def _cap_content(cls, v: str) -> str:
        return _check_text_caps(v, field="playbook_content")


Provisioner = Annotated[
    Union[ShellProvisioner, FileProvisioner, AnsibleProvisioner],
    Field(discriminator="type"),
]


# ── Root model ────────────────────────────────────────────────────────────────


class PackerEditorModel(BaseModel):
    """The structured editor model = Source of Truth (persisted as Sidecar)."""

    model_config = ConfigDict(extra="ignore")

    schema_version: int = 1
    id: str
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=2048)
    required_role: Literal["viewer", "operator", "admin"] = "operator"
    source: Source
    installer: Optional[InstallerBlock] = None
    provisioners: list[Provisioner] = Field(default_factory=list, max_length=64)
    # Free side-files (name → content) under files/ that are NOT produced by a
    # provisioner/installer — e.g. the SSH private key referenced by
    # ssh_private_key_name, or a public key. Provisioner-produced files take
    # precedence on a name collision (transpile merges side_files first).
    side_files: dict[str, str] = Field(default_factory=dict)
    # HCL raw-override (analogous to the installer raw_override): when True, the
    # user edits the generated .pkr.hcl directly and ``hcl_content`` is written
    # verbatim as ``<id>.pkr.hcl`` (no HCL parser, no roundtrip). meta.yaml and
    # the side-files (installer/provisioners/side_files) are still generated from
    # the structured model. An admin can already upload arbitrary HCL via
    # ZIP/Git, so this opens no new trust boundary.
    hcl_override: bool = False
    hcl_content: str = ""

    @field_validator("hcl_content")
    @classmethod
    def _cap_hcl(cls, v: str) -> str:
        return _check_text_caps(v, field="hcl_content")

    @field_validator("side_files")
    @classmethod
    def _check_side_files(cls, v: dict[str, str]) -> dict[str, str]:
        if len(v) > 64:
            raise ValueError("too many side files (max 64)")
        for name, content in v.items():
            if not _FILE_NAME_RE.match(name):
                raise ValueError(f"invalid side-file name: {name!r}")
            _check_text_caps(content, field=f"side_files[{name}]")
        return v

    @field_validator("id")
    @classmethod
    def _check_id(cls, v: str) -> str:
        if not _ID_RE.match(v):
            raise ValueError(
                "id must match ^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$ "
                "(letters, digits, - and _; max 64 chars)"
            )
        return v

    @model_validator(mode="before")
    @classmethod
    def _inject_source_discriminator(cls, data: Any) -> Any:
        """Inject the source ``type`` default (Pydantic-v2 discriminated-union
        gotcha): a missing ``type`` would error instead of defaulting. The editor
        always sends it, but this makes hand-built / older payloads robust."""
        if isinstance(data, dict):
            src = data.get("source")
            if isinstance(src, dict) and "type" not in src:
                src["type"] = "proxmox-iso"
        return data

    @model_validator(mode="after")
    def _installer_only_for_iso(self) -> "PackerEditorModel":
        # Installer is meaningful only for proxmox-iso; a clone has no installer.
        if self.installer is not None and self.source.type != "proxmox-iso":
            raise ValueError("installer is only valid for a proxmox-iso source")
        return self


# ── API request/response wrappers ─────────────────────────────────────────────


class ValidationResult(BaseModel):
    """422 is raised by Pydantic; this carries the non-blocking semantic warnings."""

    ok: bool = True
    warnings: list[str] = Field(default_factory=list)


class PreviewResult(BaseModel):
    """Read-only projection of the generated definition (HCL tab + file list)."""

    hcl: str
    files: dict[str, str]
    meta_yaml: str
    warnings: list[str] = Field(default_factory=list)


class DefinitionSummary(BaseModel):
    id: str
    name: str
    description: str
    required_role: str
    source_type: str
