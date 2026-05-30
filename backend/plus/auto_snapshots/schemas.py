# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-77: Pydantic-Schemas für Auto-Snapshots.

Diese Schemas beschreiben:
- die Job-Config-Payloads ``AutoConfigJobConfig`` und ``AutoVmJobConfig``
  (gespeichert als JSON in scheduled_jobs.config)
- die Target-Selektion (``TargetSpec``)
- Run-Summary für die Run-Details-EPs
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


# ─── Target-Selektion ────────────────────────────────────────────────────────


class SingleTarget(BaseModel):
    """Einzeln ausgewähltes (Portal-Node, VMID, kind)-Tripel."""
    portal_node_id: int = Field(..., ge=1)
    vmid: int = Field(..., ge=1)
    kind: Literal["qemu", "lxc"]


class TargetSpec(BaseModel):
    """Target-Auswahl (UNION über alle gesetzten Typen).

    Mindestens ein Typ muss befüllt sein (AC-TGT-1..7).
    """
    singles: list[SingleTarget] = Field(default_factory=list)
    pool_ids: list[int] = Field(default_factory=list)
    portal_node_ids: list[int] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list, max_length=10)
    kind_filter: Literal["qemu", "lxc", "both"] = "both"

    @model_validator(mode="after")
    def _at_least_one_source(self) -> "TargetSpec":
        if not (self.singles or self.pool_ids or self.portal_node_ids or self.tags):
            raise ValueError(
                "target_spec leer – mind. ein Selektor (singles, pool_ids, "
                "portal_node_ids, tags) erforderlich"
            )
        # Tag-Liste säubern (whitespace, leere Strings)
        if self.tags:
            cleaned = [t.strip() for t in self.tags if t and t.strip()]
            object.__setattr__(self, "tags", cleaned[:10])
        return self


# ─── Job-Config (gespeichert in scheduled_jobs.config) ──────────────────────


class _BaseAutoJobConfig(BaseModel):
    """Gemeinsamer Anteil beider Auto-Snapshot-Job-Konfigurationen."""

    target_spec: TargetSpec
    keep_last: int = Field(7, ge=1, le=100)
    gfs_enabled: bool = False
    keep_daily: int = Field(0, ge=0, le=100)
    keep_weekly: int = Field(0, ge=0, le=100)
    keep_monthly: int = Field(0, ge=0, le=100)
    max_parallel: int = Field(5, ge=1, le=10)

    @model_validator(mode="after")
    def _gfs_requires_at_least_one_tier(self) -> "_BaseAutoJobConfig":
        if self.gfs_enabled and (
            self.keep_daily == 0 and self.keep_weekly == 0 and self.keep_monthly == 0
        ):
            raise ValueError(
                "gfs_enabled=true erfordert mindestens einen positiven keep_* Wert"
            )
        return self


class AutoConfigJobConfig(_BaseAutoJobConfig):
    """Job-Config für ``auto_config_snapshot``-Action-Type."""

    skip_if_no_changes: bool = True
    # Optional: vom Frontend zur Anzeige zurückgegebener Name (kein Pflichtfeld)
    note: Optional[str] = None


class AutoVmJobConfig(_BaseAutoJobConfig):
    """Job-Config für ``auto_vm_snapshot``-Action-Type."""

    include_ram: bool = False
    # Optional: zusätzliche Beschreibung für den Proxmox-Snapshot
    note: Optional[str] = None


# ─── Run-Summary ─────────────────────────────────────────────────────────────


class FailedDetail(BaseModel):
    node: str
    vmid: int
    error_class: str
    error_msg: str


class RunSummary(BaseModel):
    """Aggregierte Run-Zusammenfassung, persistiert in ``scheduled_job_runs.output``."""

    status: Literal["success", "partial_success", "failed", "skipped"]
    targets_total: int = 0
    created_count: int = 0
    skipped_no_change_count: int = 0
    skipped_locked_count: int = 0
    skipped_not_owner_count: int = 0
    failed_count: int = 0
    rotated_count: int = 0
    # Erste 100 Failures (AC-RUN-3)
    failed_details: list[FailedDetail] = Field(default_factory=list)


# ─── Run-Detail-Output (für GET /api/auto-snapshots/runs/{run_id}/details) ──


class RunDetailEntry(BaseModel):
    """Eine VM-Zeile in der Run-Details-Tabelle."""
    portal_node_id: int
    proxmox_node: str
    vmid: int
    kind: Literal["qemu", "lxc"]
    status: Literal[
        "created", "skipped_no_change", "skipped_locked",
        "skipped_not_owner", "failed", "rotated_only",
    ]
    snapshot_id: Optional[str] = None
    snapname: Optional[str] = None
    error_msg: Optional[str] = None


class RunDetailsResponse(BaseModel):
    run_id: str
    job_id: str
    summary: RunSummary
    entries: list[RunDetailEntry] = Field(default_factory=list)


# ─── Native-Snapshot-Bulk-Lookup-Response ───────────────────────────────────


class NativeSnapshotEntry(BaseModel):
    """Eine Zeile aus vm_native_snapshots, sichtbar im Frontend-Snapshots-Tab."""
    id: str
    scheduled_job_id: str
    portal_node_id: int
    proxmox_node: str
    vmid: int
    kind: Literal["qemu", "lxc"]
    snapname: str
    created_at: str
    include_ram: bool
    gfs_tiers: list[str] = Field(default_factory=list)
    status: str
