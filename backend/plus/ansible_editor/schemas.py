# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-93: Pydantic model for the Ansible Visual Editor.

The structured ``AnsibleEditorModel`` is the Source of Truth. It is persisted
verbatim as the ``.p3editor.json`` Sidecar inside ``ansible/<id>/`` and
transpiled (pure fn, ``transpile.py``) into a native Ansible playbook
``<id>.yml`` + ``meta.yaml`` + side-files. The YAML is a generated projection;
there is **no reverse YAML parser** (Stacks/PROJ-92 structured-SoT, AC-ROUND-3).

Design notes (Tech-Design § C):
  * Unlike PROJ-92 (whose plugin field-set was hardcoded in the Pydantic model),
    the **task parameter schema is dynamic** — it comes from ``ansible-doc`` at
    runtime (``doc_cache.py``). Therefore ``AnsibleTask.params`` is an open
    ``dict[str, Any]`` (type-correct values, § F) and module existence + required
    params are checked in ``hard_validate`` against the schema cache, NOT in
    Pydantic (the model stays cache-decoupled, § K).
  * Jinja is just a YAML string. The editor stores each parameter value
    type-correctly in ``params``: a literal int as ``2``, a literal bool as
    ``true``, a Jinja expression as the string ``"{{ var }}"``, a Raw-YAML field
    as a parsed list/dict. ``yaml.safe_dump`` serialises that structurally →
    Ansible renders Jinja itself, P3 does no escaping/eval (AC-JINJA-2 / AC-VAL-2).
  * The module/schema wrappers (ModuleSummary/ModuleParam/ModuleSchema) are the
    response shapes the ``doc_cache`` loader produces for the form generator.
"""
from __future__ import annotations

import json
import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# id charset — a single safe path segment (directory name), no traversal.
# Ansible playbook ids may carry dots (versions) — AC-EDIT-2 — but never "..".
_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")
# Side-file names: a single safe path segment, no traversal.
_FILE_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")
# FQCN of a core module: only ansible.builtin in the MVP (decision 5).
_MODULE_RE = re.compile(r"^ansible\.builtin\.[a-z0-9_]+$")
# Task / handler / register names (Ansible-side identifiers / free text).
_REGISTER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,127}$")

# Caps for side-file content + the whole params blob (EC-8: very large files).
_MAX_FILE_BYTES = 256 * 1024
_MAX_FILE_LINES = 20_000
_MAX_PARAMS_BYTES = 256 * 1024
_MAX_TASKS = 256


def _has_nul(v: Any) -> bool:
    """Recursively check for a NUL byte in any string key/value (json.dumps
    escapes NUL to \\u0000, so it can't be found in the serialised blob)."""
    if isinstance(v, str):
        return "\x00" in v
    if isinstance(v, dict):
        return any(_has_nul(k) or _has_nul(x) for k, x in v.items())
    if isinstance(v, (list, tuple)):
        return any(_has_nul(x) for x in v)
    return False


def _check_text_caps(value: str, *, field: str) -> str:
    if len(value.encode("utf-8")) > _MAX_FILE_BYTES:
        raise ValueError(f"{field}: content exceeds {_MAX_FILE_BYTES} bytes")
    if value.count("\n") > _MAX_FILE_LINES:
        raise ValueError(f"{field}: content exceeds {_MAX_FILE_LINES} lines")
    if "\x00" in value:
        raise ValueError(f"{field}: content contains a NUL byte")
    return value


# ── Play header ───────────────────────────────────────────────────────────────


class AnsiblePlayHeader(BaseModel):
    """Play-level target/behaviour. Drives meta.yaml.targets + the hosts: line.

    ``targets`` selects the run path: ``guest`` → PROJ-83 dynamic inventory
    (hosts: managed, TOFU-SSH) / ``localhost`` → Proxmox-REST style. The editor
    only sets meta.yaml.targets+become; jobs.py dispatch + the GuestScopeSelector
    are 100% reused (Tech-Design § A/G).
    """

    model_config = ConfigDict(extra="ignore")

    targets: Literal["guest", "localhost"] = "guest"
    become: bool = False
    gather_facts: bool = False


# ── Task ──────────────────────────────────────────────────────────────────────


class AnsibleTask(BaseModel):
    """A single task = one ansible.builtin.* module with its parameters.

    ``params`` is an open dict (dynamic schema, § C). Task-level fields are only
    emitted into the YAML when set (None/empty → absent, AC-LEVEL-2).
    """

    model_config = ConfigDict(extra="ignore")

    name: str = Field(default="", max_length=256)
    module: str = Field(max_length=128)
    params: dict[str, Any] = Field(default_factory=dict)
    # Optional task-level fields (None/[] → not emitted).
    when: Optional[str] = Field(default=None, max_length=4096)
    loop: Optional[Any] = None  # Jinja string OR a list
    # ``register`` would shadow BaseModel.register (ABCMeta) → use register_var;
    # the transpiler emits the YAML key ``register`` (§ F).
    register_var: Optional[str] = Field(default=None, max_length=128)
    become: Optional[bool] = None  # task-level become; None → not emitted
    tags: list[str] = Field(default_factory=list, max_length=64)
    notify: list[str] = Field(default_factory=list, max_length=64)

    @field_validator("module")
    @classmethod
    def _check_module(cls, v: str) -> str:
        if not _MODULE_RE.match(v):
            raise ValueError(
                "module must be a core FQCN matching "
                "^ansible\\.builtin\\.[a-z0-9_]+$"
            )
        return v

    @field_validator("register_var")
    @classmethod
    def _check_register(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v != "" and not _REGISTER_RE.match(v):
            raise ValueError(f"invalid register variable name: {v!r}")
        return v

    @field_validator("tags", "notify")
    @classmethod
    def _check_str_list(cls, v: list[str]) -> list[str]:
        for item in v:
            if not isinstance(item, str) or len(item) > 256 or "\n" in item or "\x00" in item:
                raise ValueError("invalid tag/notify entry")
        return v

    @field_validator("params")
    @classmethod
    def _cap_params(cls, v: dict[str, Any]) -> dict[str, Any]:
        if len(v) > 256:
            raise ValueError("too many task parameters (max 256)")
        for key in v:
            if not isinstance(key, str) or len(key) > 128:
                raise ValueError(f"invalid parameter name: {key!r}")
        if _has_nul(v):
            raise ValueError("params contains a NUL byte")
        try:
            blob = json.dumps(v)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"params not JSON-serialisable: {exc}") from exc
        if len(blob.encode("utf-8")) > _MAX_PARAMS_BYTES:
            raise ValueError(f"params blob exceeds {_MAX_PARAMS_BYTES} bytes")
        return v


# ── Root model ────────────────────────────────────────────────────────────────


class AnsibleEditorModel(BaseModel):
    """The structured editor model = Source of Truth (persisted as Sidecar)."""

    model_config = ConfigDict(extra="ignore")

    schema_version: int = 1
    id: str
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=2048)
    category: Optional[str] = Field(default=None, max_length=64)
    required_role: Literal["viewer", "operator", "admin"] = "operator"
    header: AnsiblePlayHeader = Field(default_factory=AnsiblePlayHeader)
    tasks: list[AnsibleTask] = Field(default_factory=list, max_length=_MAX_TASKS)
    # Free side-files (name → content) under files/ — e.g. an index.html that a
    # copy task references via src. Path-/charset-/cap-hardening like PROJ-92.
    side_files: dict[str, str] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _check_id(cls, v: str) -> str:
        if not _ID_RE.match(v) or ".." in v:
            raise ValueError(
                "id must match ^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$ "
                "(letters, digits, ., - and _; no '..'; max 64 chars)"
            )
        return v

    @field_validator("category")
    @classmethod
    def _check_category(cls, v: Optional[str]) -> Optional[str]:
        if v in (None, ""):
            return None
        if v not in ("vm_deployment", "lxc_deployment", "vm_lxc_config"):
            raise ValueError(
                "category must be one of vm_deployment/lxc_deployment/vm_lxc_config"
            )
        return v

    @field_validator("side_files")
    @classmethod
    def _check_side_files(cls, v: dict[str, str]) -> dict[str, str]:
        if len(v) > 64:
            raise ValueError("too many side files (max 64)")
        for name, content in v.items():
            if not _FILE_NAME_RE.match(name) or ".." in name:
                raise ValueError(f"invalid side-file name: {name!r}")
            _check_text_caps(content, field=f"side_files[{name}]")
        return v


# ── Module / schema wrappers (doc_cache loader output, § D/E) ──────────────────


class ModuleSummary(BaseModel):
    """One ansible.builtin module in the picker (AC-MOD-1)."""

    name: str
    short_description: str = ""


# Widget the form should render for a parameter (§ E mapping).
ParamWidget = Literal["text", "number", "toggle", "dropdown", "raw_yaml"]


class ModuleParam(BaseModel):
    """A single module parameter, mapped to a form widget (§ E)."""

    name: str
    widget: ParamWidget
    type: str = "str"
    required: bool = False
    default: Any = None
    choices: Optional[list[Any]] = None
    elements: Optional[str] = None
    description: str = ""  # rST-markup stripped to plaintext (§ D)


class ModuleSchema(BaseModel):
    """The cleaned parameter schema of a module (AC-MOD-2, GET .../schema)."""

    module: str
    short_description: str = ""
    description: str = ""
    params: list[ModuleParam] = Field(default_factory=list)


# ── API request/response wrappers ─────────────────────────────────────────────


class DefinitionSummary(BaseModel):
    id: str
    name: str
    description: str
    required_role: str
    targets: str
    task_count: int


class ValidationResult(BaseModel):
    """hard_validate errors (blocking, 400 in the router) + non-blocking warnings."""

    ok: bool = True
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PreviewResult(BaseModel):
    """Read-only projection of the generated definition (YAML tab + file list)."""

    yaml: str
    meta_yaml: str
    files: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
