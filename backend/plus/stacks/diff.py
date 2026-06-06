# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-76: Eigener YAML-Diff-Walker (Tech-Design A Open-Point 1).

Kein PyPI-deepdiff. PyYAML safe_load → flach gepunktete Key-Pfade rekursiv
vergleichen → list[DiffEntry] (added/removed/changed/unchanged). YAML-Reihenfolge
ist irrelevant; das Frontend rendert die strukturierten Einträge.
"""
from __future__ import annotations

from typing import Any

import yaml

from .schemas import DiffEntry


def _flatten(obj: Any, prefix: str = "") -> dict[str, str]:
    """Flatten a parsed YAML structure to dotted key → stringified scalar.

    Lists are indexed (``resources.0.name``). Scalars are stringified so that
    Proxmox-style int/str mixes compare cleanly.
    """
    flat: dict[str, str] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            flat.update(_flatten(v, key))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            key = f"{prefix}.{i}" if prefix else str(i)
            flat.update(_flatten(v, key))
    else:
        flat[prefix] = "" if obj is None else str(obj)
    return flat


def _parse(yaml_text: str) -> dict:
    """Parse YAML into a dict; tolerant of empty/None (returns {})."""
    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def diff_yaml(from_yaml: str, to_yaml: str) -> list[DiffEntry]:
    """Produce a full diff list comparing two YAML definitions.

    Includes unchanged keys so the frontend can render a complete table.
    """
    base = _flatten(_parse(from_yaml))
    comp = _flatten(_parse(to_yaml))
    entries: list[DiffEntry] = []
    for key in sorted(set(base) | set(comp)):
        bv = base.get(key)
        cv = comp.get(key)
        if bv is None and cv is not None:
            entries.append(DiffEntry(key=key, from_value=None, to_value=cv, change="added"))
        elif bv is not None and cv is None:
            entries.append(DiffEntry(key=key, from_value=bv, to_value=None, change="removed"))
        elif bv != cv:
            entries.append(DiffEntry(key=key, from_value=bv, to_value=cv, change="changed"))
        else:
            entries.append(DiffEntry(key=key, from_value=bv, to_value=cv, change="unchanged"))
    return entries
