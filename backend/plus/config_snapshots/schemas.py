# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""Pydantic schemas for PROJ-74 VM/LXC Config-Snapshots."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class SnapshotIn(BaseModel):
    """Request body for POST /api/config-snapshots/{node}/{vmid}/create."""
    note: str = Field(..., min_length=1, max_length=500)
    name: Optional[str] = Field(
        None,
        max_length=80,
        pattern=r"^[a-zA-Z0-9_\-\.]+$",
    )


class SnapshotOut(BaseModel):
    """Lightweight snapshot list entry."""
    id: str
    portal_node_id: Optional[int]
    proxmox_node: str
    vmid: int
    kind: str
    name: str
    note: str
    description: Optional[str]
    source: str
    created_at: str
    created_by_user_id: Optional[int]
    created_by_username: Optional[str] = None
    is_orphan: bool
    orphaned_at: Optional[str]
    vm_name_at_delete: Optional[str]

    @field_validator("is_orphan", mode="before")
    @classmethod
    def coerce_orphan(cls, v: Any) -> bool:
        return bool(v)


class SnapshotDetail(SnapshotOut):
    """Full snapshot with decoded payload."""
    payload: dict[str, Any]
    etag: str  # SHA-256 of canonical payload_json


class RestoreIn(BaseModel):
    """Request body for POST /api/config-snapshots/{id}/restore."""
    vm_name_confirm: str = Field(..., min_length=1, max_length=80)
    create_pre_restore_snapshot: bool = True
    restart_after_restore: bool = False
    etag: str = Field(..., description="SHA-256 of live config at diff time")


class RestoreKeysIn(BaseModel):
    """Request body for POST /api/config-snapshots/{id}/restore-keys."""
    keys: list[str] = Field(..., min_length=1, max_length=50)
    etag: str = Field(..., description="SHA-256 of live config at diff time")


class DiffEntry(BaseModel):
    """Single key diff entry."""
    key: str
    live_value: Optional[str] = None
    snapshot_value: Optional[str] = None
    change: str  # "added" | "removed" | "changed" | "unchanged"


class DiffOut(BaseModel):
    """Result of GET /api/config-snapshots/{id}/diff-live."""
    snapshot_id: str
    live_etag: str
    snapshot_etag: str
    diff: list[DiffEntry]


class DiffABOut(BaseModel):
    """Result of GET /api/config-snapshots/diff?a={id}&b={id}."""
    snapshot_a_id: str
    snapshot_b_id: str
    diff: list[DiffEntry]


class BulkIds(BaseModel):
    """Generic list of snapshot IDs for bulk operations."""
    ids: list[str] = Field(..., min_length=1, max_length=200)


class UploadOut(BaseModel):
    """Response for POST .../upload."""
    snapshot_id: str
    warnings: list[str]
    keys_dropped: int


class OrphanOut(BaseModel):
    """Orphaned snapshot summary."""
    id: str
    proxmox_node: str
    vmid: int
    kind: str
    name: str
    note: str
    source: str
    created_at: str
    orphaned_at: Optional[str]
    vm_name_at_delete: Optional[str]
