# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-101: Request/Response-DTOs für die Template-Replikation."""
from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

_STORAGE_RE = re.compile(r"[A-Za-z0-9._-]+")
_NODE_RE = re.compile(r"[A-Za-z0-9._-]+")


class PreflightStorage(BaseModel):
    """Ein Datastore einer Ziel-Node (content=images), inkl. shared-Markierung."""
    name: str
    type: str = ""
    shared: bool = False
    avail: int = 0
    total: int = 0


class PreflightTargetNode(BaseModel):
    """Eine mögliche Ziel-Node mit ihren image-fähigen Datastores."""
    node: str
    storages: list[PreflightStorage] = []


class PreflightResponse(BaseModel):
    """Treibt das Replikations-Modal: Quell-Status + verfügbare Ziele."""
    source_node: str
    source_vmid: int
    source_name: str
    is_template: bool
    # Quelle liegt bereits auf shared Storage → keine Replikation nötig (kein-Op).
    source_shared: bool = False
    source_storage: str | None = None
    single_node: bool = False          # keine weiteren cluster_nodes
    targets: list[PreflightTargetNode] = []


class ReplicationTarget(BaseModel):
    """Eine vom Nutzer gewählte Ziel-Node + Datastore (+ optionale VMID)."""
    node: str = Field(..., min_length=1)
    storage: str = Field(..., min_length=1)
    newid: int | None = None           # None → auto next-free

    @field_validator("node")
    @classmethod
    def _valid_node(cls, v: str) -> str:
        v = v.strip()
        if not _NODE_RE.fullmatch(v):
            raise ValueError("node contains invalid characters")
        return v

    @field_validator("storage")
    @classmethod
    def _valid_storage(cls, v: str) -> str:
        v = v.strip()
        if not _STORAGE_RE.fullmatch(v):
            raise ValueError("storage contains invalid characters")
        return v

    @field_validator("newid")
    @classmethod
    def _valid_newid(cls, v: int | None) -> int | None:
        if v is not None and not (100 <= v <= 999999999):
            raise ValueError("newid must be between 100 and 999999999")
        return v


class ReplicateRequest(BaseModel):
    """Start-Request: Quelle + explizite Ziel-Liste (vom Frontend aufgelöst)."""
    source_node: str = Field(..., min_length=1)
    source_vmid: int = Field(..., ge=100)
    targets: list[ReplicationTarget] = Field(..., min_length=1)
    # Optional: lokale Quelle nach erfolgreichem shared-Heben entfernen (Default AUS).
    remove_source_after_shared: bool = False

    @field_validator("source_node")
    @classmethod
    def _valid_source_node(cls, v: str) -> str:
        v = v.strip()
        if not _NODE_RE.fullmatch(v):
            raise ValueError("source_node contains invalid characters")
        return v
