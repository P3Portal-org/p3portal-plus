# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-76: 3-stufige Validierungs-Pipeline (Tech-Design F).

1. Struktur  – Pydantic StackSpec/VMResource: Pflichtfelder, Ranges, Regex → Error (blockt Save).
2. Semantik  – Node-/Template-/Pool-Existenz → Warning (blockt Save NIE).
3. Forward   – unbekannte YAML-Keys → Warning (AC-YAML-7).

Eingabe-Normalisierung: yaml_text ist Wahrheit wenn gesetzt; sonst strukturierte
Felder → kanonisches YAML. Kein Strict-YAML-Loader (Forward-Compat).
"""
from __future__ import annotations

from typing import Any, Optional

import yaml
from pydantic import ValidationError

from backend.core.plus_protocol import plus_behavior

from .schemas import StackCreateRequest, StackSpec, VMResource

# Bekannte Felder für Unknown-Field-Warnings (Forward-Compat)
_STACK_KNOWN = {"name", "description", "version", "resources"}
_VM_KNOWN = set(VMResource.model_fields.keys())
_NETWORK_KNOWN = {"bridge", "tag"}


class StackInputError(ValueError):
    """Raised when input cannot be parsed into a raw stack dict (e.g. broken YAML)."""


def parse_input(req: StackCreateRequest) -> tuple[dict[str, Any], str]:
    """Return (raw_dict, canonical_yaml_text).

    yaml_text mode  → stored verbatim, parsed for validation.
    structured mode → serialized to canonical YAML.
    Raises StackInputError on broken/empty input.
    """
    if req.yaml_text is not None and req.yaml_text.strip():
        try:
            raw = yaml.safe_load(req.yaml_text)
        except yaml.YAMLError as exc:
            raise StackInputError(f"yaml_parse_error: {exc}") from exc
        if not isinstance(raw, dict):
            raise StackInputError("yaml_root_not_mapping")
        return raw, req.yaml_text

    # structured mode
    raw = {}
    if req.name is not None:
        raw["name"] = req.name
    if req.description is not None:
        raw["description"] = req.description
    if req.version is not None:
        raw["version"] = req.version
    if req.resources is not None:
        raw["resources"] = req.resources
    if not raw:
        raise StackInputError("empty_input")
    canonical = yaml.safe_dump(raw, sort_keys=False, default_flow_style=False, allow_unicode=True)
    return raw, canonical


def _collect_unknown_field_warnings(raw: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    for k in raw:
        if k not in _STACK_KNOWN:
            warnings.append(f"unknown stack field '{k}' ignored")
    resources = raw.get("resources")
    if isinstance(resources, list):
        for i, res in enumerate(resources):
            if not isinstance(res, dict):
                continue
            for k in res:
                if k not in _VM_KNOWN:
                    warnings.append(f"unknown field '{k}' in resource #{i + 1} ignored")
            net = res.get("network")
            if isinstance(net, dict):
                for k in net:
                    if k not in _NETWORK_KNOWN:
                        warnings.append(f"unknown network field '{k}' in resource #{i + 1} ignored")
    return warnings


def _format_pydantic_errors(exc: ValidationError) -> list[str]:
    out: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"])
        out.append(f"{loc}: {err['msg']}")
    return out


def validate_structure(raw: dict[str, Any]) -> tuple[Optional[StackSpec], list[str], list[str]]:
    """Stage 1 (Pydantic) + Stage 3 (unknown fields).

    Returns (spec_or_none, errors, warnings). spec is None when errors exist.
    """
    warnings = _collect_unknown_field_warnings(raw)
    try:
        spec = StackSpec(**raw)
    except ValidationError as exc:
        return None, _format_pydantic_errors(exc), warnings

    # Eindeutigkeit der Resource-Namen im Stack (AC-YAML-4)
    names = [r.name for r in spec.resources]
    dupes = {n for n in names if names.count(n) > 1}
    errors: list[str] = []
    if dupes:
        errors.append(f"duplicate resource names: {', '.join(sorted(dupes))}")

    if errors:
        return None, errors, warnings
    return spec, [], warnings


async def semantic_warnings(spec: StackSpec) -> list[str]:
    """Stage 2 – best-effort semantic checks. Never raises, only warns."""
    warnings: list[str] = []
    if not spec.resources:
        return warnings

    pools_active = False
    try:
        pools_active = bool(plus_behavior.can_use_pools_quotas())
    except Exception:
        pools_active = False

    # Distinct node existence (real check against nodes table)
    distinct_nodes = {r.node for r in spec.resources}
    node_known: dict[str, bool] = {}
    for node_name in distinct_nodes:
        node_known[node_name] = await _node_exists(node_name)
        if not node_known[node_name]:
            warnings.append(f"node '{node_name}' not found")

    # Pool capability warnings (AC-YAML-9 / Edge 11)
    for i, r in enumerate(spec.resources):
        if r.pool and not pools_active:
            warnings.append(
                f"resource #{i + 1}: pool field ignored (no pools capability)"
            )

    return warnings


async def _node_exists(proxmox_node: str) -> bool:
    try:
        from backend.services.nodes_service import get_node_for_proxmox_name
        node = await get_node_for_proxmox_name(proxmox_node)
        return node is not None
    except Exception:
        # Can't verify (DB error / offline) → don't warn
        return True


async def validate_request(req: StackCreateRequest) -> tuple[Optional[StackSpec], str, list[str], list[str]]:
    """Full pipeline for the /validate endpoint and pre-save validation.

    Returns (spec_or_none, canonical_yaml, errors, warnings).
    On input parse error: spec=None, canonical='', errors set.
    """
    try:
        raw, canonical = parse_input(req)
    except StackInputError as exc:
        return None, "", [str(exc)], []

    spec, errors, warnings = validate_structure(raw)
    if spec is None:
        return None, canonical, errors, warnings

    warnings += await semantic_warnings(spec)
    return spec, canonical, [], warnings
