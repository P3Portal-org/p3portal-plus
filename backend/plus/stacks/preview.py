# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-76: Resource-Auflösung für Preview (count → Suffix-Liste).

count>1 erzeugt N VMs mit Suffix ``-1``, ``-2`` … (AC-YAML-6, Edge 1).
count==1 lässt den Namen unverändert (kein Suffix).
"""
from __future__ import annotations

from .schemas import PreviewResource, StackSpec, VMResource


def resolve_resources(spec: StackSpec) -> list[PreviewResource]:
    """Expand each VMResource into one PreviewResource per ``count`` instance."""
    out: list[PreviewResource] = []
    for r in spec.resources:
        out.extend(_expand_one(r))
    return out


def _expand_one(r: VMResource) -> list[PreviewResource]:
    if r.count <= 1:
        return [_to_preview(r, r.name)]
    return [_to_preview(r, f"{r.name}-{i}") for i in range(1, r.count + 1)]


def _to_preview(r: VMResource, resolved_name: str) -> PreviewResource:
    return PreviewResource(
        type=r.type,
        name=resolved_name,
        node=r.node,
        template=r.template,
        cores=r.cores,
        memory=r.memory,
        disk=r.disk,
        pool=r.pool,
    )


def resolved_resource_dicts(spec: StackSpec) -> list[dict]:
    """Full resolved resource definitions for stack_resources denormalization."""
    dicts: list[dict] = []
    for r in spec.resources:
        names = [r.name] if r.count <= 1 else [f"{r.name}-{i}" for i in range(1, r.count + 1)]
        for resolved_name in names:
            d = r.model_dump()
            d["name"] = resolved_name
            d.pop("count", None)
            dicts.append(d)
    return dicts
