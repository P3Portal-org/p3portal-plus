# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-96: Pydantic-Schemas für VM-Abhängigkeiten."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


# ── Verwalten (CRUD) ──────────────────────────────────────────────────────────

class DependencyIn(BaseModel):
    """Request body für POST /api/dependencies.

    source = die abhängige VM, target = die VM von der sie abhängt.
    VM-Identität immer über (portal_node_id, vmid); installationsübergreifend
    erlaubt (Quelle/Ziel dürfen auf verschiedenen Portal-Nodes liegen).
    """
    source_node_id: int
    source_vmid: int
    target_node_id: int
    target_vmid: int
    dep_label: Optional[str] = Field(None, max_length=200)


class DependencyLabelIn(BaseModel):
    """Request body für PATCH /api/dependencies/{id}."""
    dep_label: Optional[str] = Field(None, max_length=200)


class DependencyOut(BaseModel):
    """Eine Abhängigkeits-Kante."""
    id: int
    source_node_id: int
    source_vmid: int
    source_node: str
    source_name: Optional[str]
    target_node_id: int
    target_vmid: int
    target_node: str
    target_name: Optional[str]
    dep_label: Optional[str]
    created_at: str
    created_by: Optional[int]
    stale: bool
    stale_at: Optional[str]
    # Installation-Namen (best-effort aus nodes.name aufgelöst)
    source_installation: Optional[str] = None
    target_installation: Optional[str] = None

    @field_validator("stale", mode="before")
    @classmethod
    def _coerce_stale(cls, v: Any) -> bool:
        return bool(v)


class VmDependenciesResponse(BaseModel):
    """Beide Richtungen für eine VM (VM-Detailseite)."""
    depends_on: list[DependencyOut] = []      # diese VM hängt ab von …
    dependents: list[DependencyOut] = []      # … hängen von dieser VM ab


# ── Aktions-Impact-Warnung (Body des 409) ────────────────────────────────────

class DependentEntry(BaseModel):
    """Ein direkter Abhängiger in der Impact-Warnung."""
    vmid: int
    name: Optional[str] = None
    node: Optional[str] = None
    installation: Optional[str] = None
    dep_label: Optional[str] = None


# ── Topologie-Sicht (gerichteter Graph) ──────────────────────────────────────

class DepGuest(BaseModel):
    """Ein VM/LXC-Knoten in der Abhängigkeits-Sicht."""
    id: str                 # inst{pnid}-{vm|lxc}-{vmid}
    vmid: int
    node: str               # physischer Proxmox-Node
    type: str               # vm | lxc
    label: str
    status: str             # running | stopped | paused
    installation: Optional[str] = None
    portal_node_id: Optional[int] = None


class DepEdge(BaseModel):
    """Gerichtete Abhängigkeits-Kante source → target („source hängt von target ab")."""
    id: int
    source_id: str
    target_id: str
    dep_label: Optional[str] = None
    stale: bool = False


class DependencyTopologyResponse(BaseModel):
    guests: list[DepGuest] = []
    edges: list[DepEdge] = []
