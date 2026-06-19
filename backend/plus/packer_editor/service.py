# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-92: file-based CRUD for editor-managed packer definitions.

The structured model lives in a Sidecar ``.p3editor.json`` inside the
definition directory ``packer/<id>/`` (Tech-Design § C). The Sidecar's mere
existence is the **marker** that a directory is editor-managed (§ G): the editor
lists/opens only marked directories, and refuses to overwrite a foreign
(ZIP/Git) directory that has no marker.

Passwords arrive as plain text and are hashed server-side (sha512-crypt) before
anything is persisted — the Sidecar/preseed only ever holds the ``$6$…`` hash
(§ E / § M). Side-files are written through a path-traversal guard.
"""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import yaml
from passlib.hash import sha512_crypt
from pydantic import ValidationError

from backend.core.config import settings
from backend.models.packer import PackerMeta, PackerParameter

from .installer import installer_filename, render_installer  # noqa: F401 (render via transpile)
from .schemas import DefinitionSummary, PackerEditorModel
from .transpile import stack_to_hcl

_SIDECAR_NAME = ".p3editor.json"


class DefinitionExists(Exception):
    """Target id already exists as an editor-managed definition (use PUT)."""


class ForeignDefinition(Exception):
    """Target id exists but is NOT editor-managed (ZIP/Git) — never overwritten."""


class DefinitionNotFound(Exception):
    """No editor-managed definition with this id."""


def _packer_dir() -> Path:
    return Path(settings.packer_dir)


def _def_dir(definition_id: str) -> Path:
    return _packer_dir() / definition_id


def _sidecar_path(definition_id: str) -> Path:
    return _def_dir(definition_id) / _SIDECAR_NAME


def is_editor_managed(definition_id: str) -> bool:
    return _sidecar_path(definition_id).is_file()


# ── Loading ───────────────────────────────────────────────────────────────────


def _load_sidecar(definition_id: str) -> PackerEditorModel | None:
    sidecar = _sidecar_path(definition_id)
    if not sidecar.is_file():
        return None
    try:
        raw = json.loads(sidecar.read_text())
        model = raw.get("model") if isinstance(raw, dict) and "model" in raw else raw
        return PackerEditorModel.model_validate(model)
    except (json.JSONDecodeError, ValidationError, OSError):
        return None


def list_definitions() -> list[DefinitionSummary]:
    packer_dir = _packer_dir()
    if not packer_dir.is_dir():
        return []
    out: list[DefinitionSummary] = []
    for entry in sorted(packer_dir.iterdir()):
        if not entry.is_dir() or not (entry / _SIDECAR_NAME).is_file():
            continue
        model = _load_sidecar(entry.name)
        if model is None:
            continue
        out.append(
            DefinitionSummary(
                id=model.id,
                name=model.name,
                description=model.description,
                required_role=model.required_role,
                source_type=model.source.type,
            )
        )
    return out


def get_definition(definition_id: str) -> PackerEditorModel | None:
    return _load_sidecar(definition_id)


# ── Password hashing (server-side, never persist plain) ───────────────────────


def _resolve_password_hashes(model: PackerEditorModel) -> None:
    """Turn any plain password into a sha512-crypt hash, then drop the plain.

    Mutates ``model.installer`` in place. After this the Sidecar/preseed never
    sees a plaintext password (§ E / § M). A user-supplied hash is left as-is.
    """
    inst = model.installer
    if inst is None:
        return
    if inst.root_password_plain:
        inst.root_password_hash = sha512_crypt.hash(inst.root_password_plain)
    inst.root_password_plain = None
    if inst.user_password_plain:
        inst.user_password_hash = sha512_crypt.hash(inst.user_password_plain)
    inst.user_password_plain = None


# ── meta.yaml generation (Tech-Design § H) ────────────────────────────────────


def _build_meta_yaml(model: PackerEditorModel) -> str:
    """Generate meta.yaml with the standard build-parameter set."""
    params = [
        PackerParameter(id="vm_id", label="VM ID", type="integer", required=True,
                        min=100, max=999999999, default=1000),
        PackerParameter(id="vm_name", label="Template Name (tmpl-NAME)", type="string", required=True),
        PackerParameter(id="node", label="Proxmox Node", type="string", required=True),
        PackerParameter(id="storage_pool", label="Storage Pool", type="string",
                        required=False, default="local-lvm"),
    ]
    if model.source.type == "proxmox-iso":
        params.append(
            PackerParameter(id="iso_file", label="ISO Datei (Proxmox-Pfad)", type="string", required=False)
        )
    meta = PackerMeta(
        name=model.name,
        description=model.description,
        required_role=model.required_role,
        parameters=params,
    )
    body = yaml.safe_dump(meta.model_dump(exclude_none=True), sort_keys=False, allow_unicode=True)
    return "# p3portal.org (generated by P3 Packer Visual Editor)\n" + body


def _sidecar_payload(model: PackerEditorModel) -> dict:
    """The on-disk Sidecar: the model (plain passwords already None) + audit."""
    return {
        "model": model.model_dump(),
        "_editor": {
            "marker": "p3-packer-editor",
            "schema_version": model.schema_version,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    }


# ── Safe side-file writing ────────────────────────────────────────────────────


def _write_safe(root: Path, relpath: str, content: str) -> None:
    """Write ``content`` to ``root/relpath`` after verifying it stays inside root.

    Defense-in-depth: the relpath comes from the transpiler with already
    charset-validated names, but we re-verify via commonpath (reuse of the
    _zip_safety hardening approach) before touching the filesystem.
    """
    root_resolved = str(root.resolve())
    target_norm = os.path.normpath(os.path.join(root_resolved, relpath))
    if os.path.commonpath([root_resolved, target_norm]) != root_resolved:
        raise ValueError(f"unsafe side-file path: {relpath!r}")
    target = Path(target_norm)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)


# ── Save / delete ─────────────────────────────────────────────────────────────


def save_definition(model: PackerEditorModel, *, is_update: bool) -> PackerEditorModel:
    """Persist the model + generate the definition directory.

    is_update=False (POST): the id must not collide. Existing **editor-managed**
    id → DefinitionExists (use PUT); existing **foreign** dir → ForeignDefinition.
    is_update=True (PUT): the id must already be editor-managed (DefinitionNotFound).

    EC-2: previously-generated http/ + files/ are cleared before re-writing so
    no-longer-referenced side-files are removed. Foreign definitions are never
    touched (§ G).
    """
    _resolve_password_hashes(model)

    def_dir = _def_dir(model.id)
    exists = def_dir.is_dir()
    marker = is_editor_managed(model.id)

    if is_update:
        if not exists or not marker:
            raise DefinitionNotFound(model.id)
    else:
        if exists and marker:
            raise DefinitionExists(model.id)
        if exists and not marker:
            raise ForeignDefinition(model.id)

    hcl_text, files = stack_to_hcl(model)
    meta_yaml = _build_meta_yaml(model)

    def_dir.mkdir(parents=True, exist_ok=True)
    # EC-2: clear generated content first (orphan side-file cleanup).
    for sub in ("http", "files"):
        shutil.rmtree(def_dir / sub, ignore_errors=True)
    # HCL is the primary output format. Clear any stale generated definition
    # file of either extension (a definition saved before the HCL switch may
    # still carry a .pkr.json) so exactly one definition file remains.
    for pattern in ("*.pkr.hcl", "*.pkr.json"):
        for stale in def_dir.glob(pattern):
            stale.unlink()

    (def_dir / f"{model.id}.pkr.hcl").write_text(hcl_text)
    (def_dir / "meta.yaml").write_text(meta_yaml)
    for relpath, content in files.items():
        _write_safe(def_dir, relpath, content)
    _sidecar_path(model.id).write_text(json.dumps(_sidecar_payload(model), indent=2) + "\n")

    return model


def build_preview(model: PackerEditorModel) -> tuple[str, dict[str, str], str]:
    """Generate the read-only projection without persisting (POST /preview).

    Returns the generated ``.pkr.hcl`` text + side-files + meta.yaml. Resolves
    plain passwords to hashes on the transient model so the preview shows the
    same ``$6$…`` hash that a save would write — the plain password is never
    returned (it is set to None by _resolve_password_hashes).
    """
    _resolve_password_hashes(model)
    hcl_text, files = stack_to_hcl(model)
    meta_yaml = _build_meta_yaml(model)
    return hcl_text, files, meta_yaml


def delete_definition(definition_id: str) -> bool:
    """Delete an editor-managed definition directory (EC-11).

    Returns False if it doesn't exist. Raises ForeignDefinition for a directory
    without the editor marker (never delete a ZIP/Git definition from here).
    """
    def_dir = _def_dir(definition_id)
    if not def_dir.is_dir():
        return False
    if not is_editor_managed(definition_id):
        raise ForeignDefinition(definition_id)
    shutil.rmtree(def_dir)
    return True
