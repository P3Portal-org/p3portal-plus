# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-93: ansible-doc schema loader & cache (Tech-Design § D/E).

The one real difference from PROJ-92: the module parameter schema is **dynamic**.
``ansible-doc -j <module>`` yields, per parameter, ``type``/``elements``/
``required``/``default``/``choices``/``description``/``suboptions`` — verified
live against ansible-core 2.20. This module:

  * reads a **build-time cache** under ``ANSIBLE_DOC_CACHE_DIR`` (a Dockerfile RUN
    step pre-generates ``_modules.json`` + reduced ``<fqcn>.json`` for all ~71
    ``ansible.builtin`` modules) — keeps no examples/return blocks;
  * holds an in-memory cache;
  * on a **cache miss** runs a single ``ansible-doc -j <name>`` subprocess
    (arg-list, no shell, 10 s timeout) — EC-2/3; if ``ansible-doc`` is missing
    entirely → ``ModuleSchemaUnavailable`` surfaces in the module picker, never
    in the save path;
  * maps the cleaned schema to a form **widget** (§ E) and strips the rST markup
    (``V()/C()/O()/B()/M()/U()`` …) in the descriptions to plaintext.

``ansible-doc`` output is public documentation — no secrets (AC-RBAC-3).

Run ``python -m backend.plus.ansible_editor.doc_cache --build`` to (re)generate
the cache (used by the Dockerfile + tests).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Optional

from .schemas import ModuleParam, ModuleSchema, ModuleSummary

# Only core modules in the MVP (decision 5).
COLLECTION = "ansible.builtin"
_MODULE_RE = re.compile(r"^ansible\.builtin\.[a-z0-9_]+$")
_DOC_TIMEOUT_S = 10
_MODULES_FILE = "_modules.json"


def cache_dir() -> Path:
    """Cache directory (env-overridable for tests / build)."""
    return Path(os.environ.get("P3_ANSIBLE_DOC_CACHE_DIR", "/opt/p3/ansible-doc-cache"))


class ModuleSchemaUnavailable(Exception):
    """ansible-doc is unavailable and the module is not in the cache."""


class ModuleNotFound(Exception):
    """The requested module is not a valid ansible.builtin.* name / not found."""


# ── rST markup stripping (§ D) ────────────────────────────────────────────────

# Ansible doc semantic markers: B(bold) C(code) E(env) I(italic) L(text,url)
# M(module) O(option) P(plugin) R(text,ref) RV(return value) U(url) V(value).
_RST_MACRO = re.compile(r"\b(B|C|E|I|L|M|O|P|R|RV|U|V)\(([^)]*)\)")


def _strip_markup(text: str) -> str:
    text = text.replace("HORIZONTALLINE", "")
    # Keep the inner content of each marker; collapse repeatedly for nesting.
    prev = None
    while prev != text:
        prev = text
        text = _RST_MACRO.sub(lambda m: m.group(2), text)
    return re.sub(r"\s+", " ", text).strip()


def _join_description(desc: Any) -> str:
    if isinstance(desc, list):
        return _strip_markup(" ".join(str(x) for x in desc))
    if isinstance(desc, str):
        return _strip_markup(desc)
    return ""


def _norm_choices(c: Any) -> Optional[list]:
    """Normalise choices to a flat list. Newer modules give a {value: desc} dict
    (e.g. uri.follow_redirects) — keep the values (the selectable keys)."""
    if isinstance(c, dict):
        return list(c.keys())
    if isinstance(c, list):
        return c
    return None


# ── Reduce raw ansible-doc output → compact cached form ───────────────────────


def _reduce_raw(raw: dict, fqcn: str) -> dict:
    """Reduce a raw ``ansible-doc -j <fqcn>`` payload to the compact cached form.

    Drops ``examples``/``return`` and keeps only the form-relevant option fields.
    The descriptions are already markup-stripped here so the cache is render-ready.
    """
    entry = raw.get(fqcn) or next(iter(raw.values()), {})
    doc = entry.get("doc", {}) if isinstance(entry, dict) else {}
    options = doc.get("options", {}) or {}
    out_opts: dict[str, dict] = {}
    for name, opt in options.items():
        if not isinstance(opt, dict):
            continue
        out_opts[name] = {
            "type": opt.get("type", "str"),
            "elements": opt.get("elements"),
            "required": bool(opt.get("required", False)),
            "default": opt.get("default"),
            "choices": _norm_choices(opt.get("choices")),
            "has_suboptions": "suboptions" in opt,
            "description": _join_description(opt.get("description")),
        }
    return {
        "module": fqcn,
        "short_description": _strip_markup(str(doc.get("short_description", ""))),
        "description": _join_description(doc.get("description")),
        "options": out_opts,
    }


# ── Schema → widget mapping (§ E) ─────────────────────────────────────────────


def _widget_for(opt: dict) -> str:
    if opt.get("choices"):
        return "dropdown"
    typ = opt.get("type")
    if typ in ("list", "dict") or opt.get("elements") == "dict" or opt.get("has_suboptions"):
        return "raw_yaml"
    if typ == "bool":
        return "toggle"
    if typ in ("int", "float"):
        return "number"
    return "text"  # str, path, raw, …


def _compact_to_schema(compact: dict) -> ModuleSchema:
    params: list[ModuleParam] = []
    for name, opt in (compact.get("options") or {}).items():
        params.append(
            ModuleParam(
                name=name,
                widget=_widget_for(opt),  # type: ignore[arg-type]
                type=str(opt.get("type", "str")),
                required=bool(opt.get("required", False)),
                default=opt.get("default"),
                choices=opt.get("choices"),
                elements=opt.get("elements"),
                description=opt.get("description", ""),
            )
        )
    params.sort(key=lambda p: (not p.required, p.name))
    return ModuleSchema(
        module=compact["module"],
        short_description=compact.get("short_description", ""),
        description=compact.get("description", ""),
        params=params,
    )


# ── ansible-doc subprocess (no shell, timeout) ────────────────────────────────


def _run_ansible_doc(args: list[str]) -> dict:
    """Run ``ansible-doc <args>`` (arg-list, no shell) and parse its JSON.

    Raises ModuleSchemaUnavailable if ansible-doc is missing/errors/times out.
    """
    try:
        proc = subprocess.run(  # noqa: S603 (fixed arg-list, no shell)
            ["ansible-doc", *args],
            capture_output=True,
            text=True,
            timeout=_DOC_TIMEOUT_S,
        )
    except (FileNotFoundError, subprocess.TimeoutError, subprocess.SubprocessError) as exc:
        raise ModuleSchemaUnavailable(str(exc)) from exc
    if proc.returncode != 0 or not proc.stdout.strip():
        raise ModuleSchemaUnavailable(
            f"ansible-doc {' '.join(args)} failed (rc={proc.returncode})"
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise ModuleSchemaUnavailable(f"ansible-doc returned invalid JSON: {exc}") from exc


# ── In-memory cache ───────────────────────────────────────────────────────────

_modules_mem: Optional[dict[str, str]] = None
_schema_mem: dict[str, dict] = {}


def _reset_cache() -> None:
    """Clear the in-memory cache (tests)."""
    global _modules_mem
    _modules_mem = None
    _schema_mem.clear()


# ── Public loader API ─────────────────────────────────────────────────────────


def _load_modules_map() -> dict[str, str]:
    """{fqcn: short_description} for the module picker (cache → fallback)."""
    global _modules_mem
    if _modules_mem is not None:
        return _modules_mem
    cached = cache_dir() / _MODULES_FILE
    if cached.is_file():
        try:
            data = json.loads(cached.read_text())
            if isinstance(data, dict):
                _modules_mem = {str(k): _strip_markup(str(v)) for k, v in data.items()}
                return _modules_mem
        except (json.JSONDecodeError, OSError):
            pass
    # Fallback: ansible-doc -l -j → {fqcn: short_description}
    raw = _run_ansible_doc(["-l", "-j", COLLECTION])
    _modules_mem = {str(k): _strip_markup(str(v)) for k, v in raw.items()}
    return _modules_mem


def list_modules() -> list[ModuleSummary]:
    """All ansible.builtin modules (name + short_description), sorted (AC-MOD-1)."""
    mods = _load_modules_map()
    out = [ModuleSummary(name=name, short_description=desc) for name, desc in mods.items()]
    out.sort(key=lambda m: m.name)
    return out


def _load_compact(name: str) -> dict:
    """Reduced module doc dict (cache → fallback). Caches in memory."""
    if name in _schema_mem:
        return _schema_mem[name]
    cached = cache_dir() / f"{name}.json"
    if cached.is_file():
        try:
            compact = json.loads(cached.read_text())
            if isinstance(compact, dict) and "options" in compact:
                _schema_mem[name] = compact
                return compact
        except (json.JSONDecodeError, OSError):
            pass
    # Fallback: a single ansible-doc -j <name> subprocess, then reduce.
    raw = _run_ansible_doc(["-j", name])
    compact = _reduce_raw(raw, name)
    _schema_mem[name] = compact
    return compact


def module_schema(name: str) -> ModuleSchema:
    """Cleaned parameter schema of one module (AC-MOD-2). Raises on bad name."""
    if not _MODULE_RE.match(name):
        raise ModuleNotFound(name)
    return _compact_to_schema(_load_compact(name))


def module_exists(name: str) -> bool:
    """True if ``name`` is a known ansible.builtin module (for hard_validate)."""
    if not _MODULE_RE.match(name):
        return False
    try:
        return name in _load_modules_map()
    except ModuleSchemaUnavailable:
        # Degraded: trust the FQCN pattern if the module list is unavailable.
        return True


# ── Build-time cache generation (Dockerfile + tests) ──────────────────────────


def build_cache(target: Optional[Path] = None) -> int:
    """Generate the on-disk cache from a live ``ansible-doc``. Returns module count.

    Writes ``_modules.json`` (full list) + one reduced ``<fqcn>.json`` per module.
    Used by the Dockerfile RUN step and by tests (which point the env var at a
    temp dir). Idempotent.
    """
    out = target or cache_dir()
    out.mkdir(parents=True, exist_ok=True)
    modules_raw = _run_ansible_doc(["-l", "-j", COLLECTION])
    (out / _MODULES_FILE).write_text(json.dumps(modules_raw, sort_keys=True))
    count = 0
    for fqcn in modules_raw:
        try:
            raw = _run_ansible_doc(["-j", fqcn])
        except ModuleSchemaUnavailable:
            continue
        compact = _reduce_raw(raw, fqcn)
        (out / f"{fqcn}.json").write_text(json.dumps(compact, sort_keys=True))
        count += 1
    return count


if __name__ == "__main__":  # pragma: no cover
    import sys

    if "--build" in sys.argv:
        n = build_cache()
        print(f"ansible-doc cache built: {n} modules → {cache_dir()}")
    else:
        print("usage: python -m backend.plus.ansible_editor.doc_cache --build")
