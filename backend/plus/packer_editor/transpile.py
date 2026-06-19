# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-92: transpile the structured editor model → native ``.pkr.hcl`` (HCL2).

Pure function — fully unit-testable without Packer/Proxmox (Stacks precedent).

HCL is the **primary output format** (user choice, 2026-06-17). The structured
P3 model stays the Source of Truth; this serializer is a deterministic
projection (Roundtrip-/Escaping-Problem still solved — see below).

Injection safety (EC-9):
  * **Code-generated HCL expressions** (``var.node``, the credential ternaries,
    ``file(...)``) are wrapped in :class:`Raw` and emitted **verbatim**. They
    never contain user data.
  * **Every user value** (template_description, network_bridge, clone_vm,
    shell inline lines, destinations, …) is emitted through ``json.dumps`` — an
    HCL2 string literal uses the same escaping as JSON, so a user value can
    **never break out of its string context** (quotes/backslashes escaped).
    ``${...}`` inside a value is interpolated by Packer exactly as it was with
    the previous ``.pkr.json`` (identical semantics, different representation).
  * The serializer never concatenates user data into an expression position.

Returns ``(hcl_text: str, files: dict[relpath -> content])``. ``files`` paths
are POSIX-relative to the definition directory (e.g. ``http/preseed.cfg``,
``files/cloud.cfg``). service.py writes them safely under ``packer/<id>/``.
"""
from __future__ import annotations

import json
from typing import Any

from . import installer as installer_mod
from .schemas import (
    AnsibleProvisioner,
    CloneSource,
    FileProvisioner,
    IsoSource,
    PackerEditorModel,
    ShellProvisioner,
)

# Pinned proxmox plugin (image bundle). Verification point against the actual
# packer-plugin-proxmox version in the container image (Tech-Design § N #3).
_PLUGIN_SOURCE = "github.com/hashicorp/proxmox"
_PLUGIN_VERSION = "~> 1.2.3"

# Credential-wiring expressions, identical to the hand-written reference HCL.
# username = user-mode user else token-id; token only in token-mode; password
# only in user-mode. The runner injects the actual values via -var / env.
_EXPR_USERNAME = 'var.proxmox_api_user != "" ? var.proxmox_api_user : var.proxmox_api_token_id'
_EXPR_TOKEN = 'var.proxmox_api_user != "" ? "" : var.proxmox_api_token_secret'
_EXPR_PASSWORD = 'var.proxmox_api_user != "" ? var.proxmox_api_password : ""'


class Raw(str):
    """A value to be emitted as a verbatim HCL expression.

    ONLY used for code-generated expressions (``var.*``, ternaries, ``file()``,
    HCL keywords like ``string``). NEVER wrap user data in this — user data must
    go through the normal (quoted/escaped) value path.
    """


# ── HCL value / body rendering ────────────────────────────────────────────────


def _val(v: Any, indent: str) -> str:
    """Render a single HCL value (injection-safe)."""
    if isinstance(v, Raw):
        return str(v)
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, str):
        # HCL2 string literal == JSON string escaping. ${...} stays interpolated
        # (same as the old .pkr.json); quotes/backslashes are escaped → no break.
        return json.dumps(v)
    if isinstance(v, list):
        if not v:
            return "[]"
        inner = ",\n".join(f"{indent}  {_val(x, indent + '  ')}" for x in v)
        return "[\n" + inner + "\n" + indent + "]"
    if isinstance(v, dict):
        # A map value (e.g. http_content): { "key" = value }
        lines = [f"{indent}  {json.dumps(k)} = {_val(val, indent + '  ')}" for k, val in v.items()]
        return "{\n" + "\n".join(lines) + "\n" + indent + "}"
    raise ValueError(f"unsupported HCL value type: {type(v).__name__}")  # pragma: no cover


# A "body" is a list of items. Each item is one of:
#   ("attr",  key:str, value)
#   ("block", btype:str, labels:list[str], body:list[item])
Item = tuple


def _attr(key: str, value: Any) -> Item:
    return ("attr", key, value)


def _block(btype: str, labels: list[str], body: list[Item]) -> Item:
    return ("block", btype, labels, body)


def _render_body(items: list[Item], indent: str) -> str:
    out: list[str] = []
    for it in items:
        if it[0] == "attr":
            _, key, value = it
            out.append(f"{indent}{key} = {_val(value, indent)}")
        else:  # block
            _, btype, labels, body = it
            label_str = "".join(f" {json.dumps(lbl)}" for lbl in labels)
            out.append(f"{indent}{btype}{label_str} {{")
            if body:
                out.append(_render_body(body, indent + "  "))
            out.append(f"{indent}}}")
    return "\n".join(out)


# ── Variable blocks ───────────────────────────────────────────────────────────


def _variable_block(name: str, *, default: Any = None, sensitive: bool = False) -> Item:
    body: list[Item] = [_attr("type", Raw("string"))]
    if sensitive:
        body.append(_attr("sensitive", True))
    if default is not None:
        body.append(_attr("default", default))
    return _block("variable", [name], body)


def _variable_blocks(model: PackerEditorModel) -> list[Item]:
    """Emit the exact variable set the -var runner expects (Tech-Design § A)."""
    is_iso = model.source.type == "proxmox-iso"
    blocks: list[Item] = [
        _variable_block("proxmox_api_url"),
        # Token mode (Portal-login)
        _variable_block("proxmox_api_token_id", default=""),
        _variable_block("proxmox_api_token_secret", default="", sensitive=True),
        # User mode (Proxmox-login, PROJ-22)
        _variable_block("proxmox_api_user", default=""),
        _variable_block("proxmox_api_password", default="", sensitive=True),
        # Build params (filled per build via -var)
        _variable_block("vm_id"),
        _variable_block("vm_name"),
        _variable_block("node"),
        _variable_block("storage_pool", default="local-lvm"),
        # Portal host IP for the Packer HTTP server (preseed/kickstart fetch)
        _variable_block("packer_http_ip", default=""),
    ]
    if is_iso:
        blocks.append(_variable_block("iso_file"))
    return blocks


# ── Source body ───────────────────────────────────────────────────────────────


def _common_source_body(model: PackerEditorModel) -> list[Item]:
    """VM settings shared by clone and iso (credentials + general + hw + net)."""
    src = model.source
    name = model.name or model.id
    body: list[Item] = [
        # Proxmox connection (dual auth mode, PROJ-22)
        _attr("proxmox_url", Raw("var.proxmox_api_url")),
        _attr("username", Raw(_EXPR_USERNAME)),
        _attr("token", Raw(_EXPR_TOKEN)),
        _attr("password", Raw(_EXPR_PASSWORD)),
        _attr("insecure_skip_tls_verify", True),
        # General
        _attr("node", Raw("var.node")),
        _attr("vm_id", Raw("var.vm_id")),
        _attr("vm_name", Raw('"tmpl-${var.vm_name}"')),
        _attr("template_description", src.template_description or f"{name} (built by P3)"),
        # System / hardware
        _attr("qemu_agent", src.qemu_agent),
        _attr("scsi_controller", src.scsi_controller),
        _attr("cores", str(src.cores)),
        _attr("memory", str(src.memory_mb)),
        # Network (single block)
        _block("network_adapters", [], [
            _attr("model", src.network_model),
            _attr("bridge", src.network_bridge),
            _attr("firewall", src.network_firewall),
        ]),
        # Cloud-init
        _attr("cloud_init", src.cloud_init),
        _attr("cloud_init_storage_pool", Raw("var.storage_pool")),
        # SSH connection for provisioning
        _attr("ssh_username", src.ssh_username),
        _attr("ssh_timeout", src.ssh_timeout),
    ]
    if src.ssh_private_key_name:
        # name is _FILE_NAME_RE-validated (no quotes) → safe inside the literal.
        body.append(_attr("ssh_private_key_file", Raw('"${path.root}/files/' + src.ssh_private_key_name + '"')))
    return body


def _iso_source_body(model: PackerEditorModel) -> list[Item]:
    assert isinstance(model.source, IsoSource)
    src = model.source
    body = _common_source_body(model)
    body += [
        _block("boot_iso", [], [
            _attr("type", "scsi"),
            _attr("iso_file", Raw("var.iso_file")),
            _attr("iso_storage_pool", "local"),
            _attr("unmount", True),
        ]),
        _block("disks", [], [
            _attr("disk_size", f"{src.disk_size_gb}G"),
            _attr("storage_pool", Raw("var.storage_pool")),
            _attr("type", "scsi"),
            _attr("discard", True),
            _attr("ssd", True),
        ]),
        _attr("boot", "c"),
        _attr("boot_wait", src.boot_wait),
        _attr("http_bind_address", "0.0.0.0"),
        _attr("http_port_min", src.http_port),
        _attr("http_port_max", src.http_port),
    ]
    # boot_command: explicit, else profile default wired with the installer URL.
    boot_command = src.boot_command
    if not boot_command:
        profile = model.installer.os_profile if model.installer else "debian-preseed"
        boot_command = installer_mod.default_boot_command(profile, src.http_port)
    body.append(_attr("boot_command", list(boot_command)))
    # Installer wiring (only when an installer block exists): the editor generates
    # the FINISHED installer file(s) (key inlined) → file() instead of
    # templatefile(). Ubuntu autoinstall serves two files (user-data + meta-data).
    if model.installer is not None:
        http_map = {
            f"/{name}": Raw('file("${path.root}/http/' + name + '")')
            for name in installer_mod.installer_filenames(model.installer.os_profile)
        }
        body.append(_attr("http_content", http_map))
    return body


def _clone_source_body(model: PackerEditorModel) -> list[Item]:
    assert isinstance(model.source, CloneSource)
    src = model.source
    body = _common_source_body(model)
    body += [
        _attr("clone_vm", src.clone_template),
        _attr("full_clone", src.full_clone),
        # A clone has no boot disk creation; resize via disks is optional and
        # left out in the MVP (the clone inherits the template disk).
    ]
    return body


# ── Provisioner blocks ─────────────────────────────────────────────────────────


def _provisioner_block(p: Any) -> Item:
    """One provisioner → an HCL ``provisioner "<type>" { ... }`` block."""
    if isinstance(p, ShellProvisioner):
        if p.mode == "script":
            return _block("provisioner", ["shell"], [_attr("script", f"files/{p.script_name}")])
        return _block("provisioner", ["shell"], [_attr("inline", list(p.inline))])
    if isinstance(p, FileProvisioner):
        return _block("provisioner", ["file"], [
            _attr("source", f"files/{p.source_name}"),
            _attr("destination", p.destination),
        ])
    if isinstance(p, AnsibleProvisioner):
        body: list[Item] = [_attr("playbook_file", f"files/{p.playbook_name}")]
        if p.extra_vars:
            # Packer ansible provisioner: extra_arguments ["--extra-vars", "k=v", ...]
            args: list[str] = []
            for k, v in p.extra_vars.items():
                args += ["--extra-vars", f"{k}={v}"]
            body.append(_attr("extra_arguments", args))
        return _block("provisioner", ["ansible"], body)
    raise ValueError(f"unknown provisioner type: {type(p).__name__}")  # pragma: no cover


# ── Top-level ──────────────────────────────────────────────────────────────────


def _build_side_files(model: PackerEditorModel) -> dict[str, str]:
    """Generate the side-files dict (http/ installer + files/ provisioner+free).

    Shared by the structured and the HCL-override path: even when the user edits
    the .pkr.hcl directly, the files it references (preseed/kickstart, scripts,
    cloud.cfg, ssh key) are still generated from the structured model.
    """
    is_iso = model.source.type == "proxmox-iso"
    files: dict[str, str] = {}
    # Free side-files first (ssh keys etc.); provisioner/installer files override.
    for fname, content in model.side_files.items():
        files[f"files/{fname}"] = content
    if is_iso and model.installer is not None:
        for ifname, content in installer_mod.installer_files(model.installer).items():
            files[f"http/{ifname}"] = content
    for p in model.provisioners:
        if isinstance(p, ShellProvisioner) and p.mode == "script" and p.script_name:
            files[f"files/{p.script_name}"] = p.script_content
        elif isinstance(p, FileProvisioner):
            files[f"files/{p.source_name}"] = p.source_content
        elif isinstance(p, AnsibleProvisioner):
            files[f"files/{p.playbook_name}"] = p.playbook_content
    return files


def stack_to_hcl(model: PackerEditorModel) -> tuple[str, dict[str, str]]:
    """Transpile the editor model → (hcl_text, files). Pure function.

    HCL raw-override: if ``hcl_override`` is set and ``hcl_content`` is non-empty,
    that text is returned verbatim as the .pkr.hcl (no parsing); the side-files
    are still generated from the structured model.
    """
    files = _build_side_files(model)
    if model.hcl_override and model.hcl_content.strip():
        return model.hcl_content, files

    is_iso = model.source.type == "proxmox-iso"
    source_type = "proxmox-iso" if is_iso else "proxmox-clone"
    source_body = _iso_source_body(model) if is_iso else _clone_source_body(model)

    top: list[Item] = []
    # packer { required_plugins { proxmox = { version, source } } }
    top.append(_block("packer", [], [
        _block("required_plugins", [], [
            _attr("proxmox", {"version": _PLUGIN_VERSION, "source": _PLUGIN_SOURCE}),
        ]),
    ]))
    # variable "..." { ... }
    top += _variable_blocks(model)
    # source "<type>" "builder" { ... }
    top.append(_block("source", [source_type, "builder"], source_body))
    # build { ... }
    build_body: list[Item] = [
        _attr("name", model.id),
        _attr("sources", [f"source.{source_type}.builder"]),
    ]
    build_body += [_provisioner_block(p) for p in model.provisioners]
    top.append(_block("build", [], build_body))

    hcl_text = "# Generated by P3 Packer Visual Editor — p3portal.org\n" + _render_body(top, "") + "\n"
    return hcl_text, files
