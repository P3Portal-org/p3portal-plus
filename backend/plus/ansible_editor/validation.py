# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-93: validation against the schema cache (Tech-Design § K).

Two layers (Pydantic-422 is the third, in the router):
  * ``hard_validate(model)`` — **blocking** errors checked against the dynamic
    ansible-doc schema cache: (a) every module exists in ansible.builtin;
    (b) each required module parameter is filled OR carries a Jinja value
    (AC-TASK-3). Returns a list of error strings → 400 in the router.
  * ``semantic_warnings(model)`` — **non-blocking** hints (empty playbook, task
    without name, unknown module parameter [forward-compat], localhost hint,
    missing referenced side-file).

**Architecture note (Raw-YAML, AC-SUB-2):** the model's ``task.params`` arrives
already structured (the frontend parses Raw-YAML list/dict fields with js-yaml
and shows parse errors client-side while typing). A structured dict/list IS, by
definition, parseable — so the backend does not re-parse Raw-YAML here. It checks
what it can against the schema (module existence + required params), keeping
validation cache-coupled but Proxmox-/Ansible-roundtrip-free (no live
``ansible-playbook`` run; an optional ``--syntax-check`` lives in the router).
"""
from __future__ import annotations

from typing import Any

from . import doc_cache
from .doc_cache import ModuleSchemaUnavailable
from .schemas import AnsibleEditorModel


def _is_filled(v: Any) -> bool:
    """True if a parameter value counts as set (a Jinja string counts; '' / [] / {}
    / None do not; bool/int/float always do)."""
    if v is None:
        return False
    if isinstance(v, str):
        return v.strip() != ""
    if isinstance(v, (list, dict)):
        return len(v) > 0
    return True


def hard_validate(model: AnsibleEditorModel) -> list[str]:
    """Blocking validation against the schema cache. Empty list = OK."""
    errors: list[str] = []
    for i, task in enumerate(model.tasks, start=1):
        label = f"Task {i} ({task.name or task.module})"
        if not doc_cache.module_exists(task.module):
            errors.append(f"{label}: Modul '{task.module}' existiert nicht in ansible.builtin.")
            continue
        # Required-parameter check (skipped if the schema is unavailable —
        # degraded mode; the run would catch a missing required param itself).
        try:
            schema = doc_cache.module_schema(task.module)
        except (ModuleSchemaUnavailable, doc_cache.ModuleNotFound):
            continue
        for param in schema.params:
            if param.required and not _is_filled(task.params.get(param.name)):
                errors.append(
                    f"{label}: Pflichtparameter '{param.name}' ist nicht gesetzt."
                )
    return errors


def semantic_warnings(model: AnsibleEditorModel) -> list[str]:
    """Non-blocking warnings."""
    warnings: list[str] = []

    if not model.tasks:
        warnings.append("Das Playbook hat keine Tasks — es wird ein leerer Play erzeugt.")

    if model.header.targets == "localhost":
        warnings.append(
            "Ziel 'localhost': Playbooks gegen die Proxmox-REST-API benötigen "
            "Variablen (z. B. API-URL/Token), die im MVP nur per Jinja-Freitextfeld "
            "referenziert werden können (parameters[]-Builder = Folge-Phase). "
            "Der Sweetspot ist Gast-Konfiguration ('guest')."
        )

    for i, task in enumerate(model.tasks, start=1):
        label = f"Task {i}"
        if not task.name:
            warnings.append(f"{label}: ohne Namen — ein 'name' verbessert die Lesbarkeit.")
        # Unknown module parameters → forward-compat warning (not blocking).
        try:
            schema = doc_cache.module_schema(task.module)
        except (ModuleSchemaUnavailable, doc_cache.ModuleNotFound):
            schema = None
        if schema is not None:
            known = {p.name for p in schema.params}
            for key in task.params:
                if key not in known:
                    warnings.append(
                        f"{label}: Parameter '{key}' ist nicht im Schema von "
                        f"'{task.module}' — wird unverändert übernommen."
                    )
        # copy/template src referencing files/<x> that is not a side-file.
        src = task.params.get("src")
        if isinstance(src, str) and src.startswith("files/"):
            name = src[len("files/"):]
            if name and name not in model.side_files:
                warnings.append(
                    f"{label}: src '{src}' verweist auf eine Nebendatei, die nicht "
                    "hinterlegt ist — der Run findet sie sonst nicht."
                )

    return warnings
