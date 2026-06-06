# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""Pydantic schemas for PROJ-76 Phase 1 Stacks."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ── Resource spec (strict validation model) ──────────────────────────────────

class NetworkConfig(BaseModel):
    model_config = {"extra": "ignore"}
    bridge: str = "vmbr0"
    tag: Optional[int] = Field(None, ge=1, le=4094)


class VMResource(BaseModel):
    """Strict validation model for a single VM resource (AC-YAML-4/5/6)."""
    model_config = {"extra": "ignore"}

    type: Literal["vm"] = "vm"
    name: str = Field(..., min_length=1, max_length=64)
    node: str = Field(..., min_length=1)
    template: str = Field(..., min_length=1)
    # Optional explicit VMID. Default (None) → Proxmox auto-assigns a free VMID
    # (collision-safe, AC-2B-ISO-3). When set + count>1 the instances get
    # vmid, vmid+1, … (base + offset). A taken VMID makes Proxmox reject the
    # apply (surfaced via the plan/apply diagnostics).
    vmid: Optional[int] = Field(None, ge=100, le=999999999)
    count: int = Field(1, ge=1, le=50)
    cores: int = Field(1, ge=1, le=128)
    sockets: int = Field(1, ge=1, le=4)
    memory: int = Field(2048, ge=512, le=1048576)
    disk: int = Field(32, ge=1, le=16384)
    cpu_type: str = "host"
    # QEMU guest agent. Default False = fast deploy: bpg does not wait for the
    # agent to report an IP (apply finishes in ~1-2 min). True = full Proxmox
    # agent integration (IP display, agent-based graceful shutdown) at the cost
    # of bpg waiting up to its agent timeout (~15 min on slow cloud-init boots).
    agent: bool = False
    network: Optional[NetworkConfig] = None
    tags: list[str] = Field(default_factory=list, max_length=10)
    pool: Optional[str] = None
    start_after_create: bool = True


class StackSpec(BaseModel):
    """Strict validation model for a whole stack definition (AC-YAML-1/2/3)."""
    model_config = {"extra": "ignore"}

    name: str = Field(..., min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    description: Optional[str] = Field(None, max_length=500)
    version: str = "1.0.0"
    resources: list[VMResource] = Field(default_factory=list)


# ── Write requests ────────────────────────────────────────────────────────────

class StackCreateRequest(BaseModel):
    """POST /api/stacks – YAML-Text ODER strukturierter JSON-Body (AC-API-2).

    Wenn ``yaml_text`` gesetzt ist, ist es die Wahrheit (verbatim gespeichert).
    Sonst werden die strukturierten Felder zu kanonischem YAML serialisiert.
    """
    model_config = {"extra": "ignore"}

    yaml_text: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    version: Optional[str] = None
    resources: Optional[list[dict[str, Any]]] = None
    source_kind: str = "structured"


class StackUpdateRequest(StackCreateRequest):
    """PUT /api/stacks/{id} – mit ETag-Concurrency (AC-CONC-1/2)."""
    expected_etag: str = Field(..., min_length=64, max_length=64)
    base_yaml: Optional[str] = None       # Pass-Through für 409-Body
    change_summary: Optional[str] = None


class StackValidateRequest(StackCreateRequest):
    """POST /api/stacks/validate – identische Form, ohne Persistenz."""
    pass


class RestoreVersionRequest(BaseModel):
    version_number: int = Field(..., ge=1)
    change_summary: Optional[str] = None
    # Optionaler ETag-Concurrency-Schutz (Edge 9): wenn gesetzt, muss er dem
    # aktuellen Stack-ETag entsprechen, sonst HTTP 409 (analog PUT, BUG-76-2).
    expected_etag: Optional[str] = Field(None, min_length=64, max_length=64)


class ReassignRequest(BaseModel):
    owner_user_id: int = Field(..., ge=1)


# ── Responses ─────────────────────────────────────────────────────────────────

class StackResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    version: str
    status: str
    source_kind: str
    owner_user_id: Optional[int]
    owner_username: Optional[str] = None
    is_orphan: bool
    resource_count: int
    current_etag: str
    created_at: str
    updated_at: str
    # Phase 2b: derived deployment badge (None for Phase-1-only / not-deployed reads)
    deployment_state: Optional[str] = None
    last_drift_state: Optional[str] = None


class StackDetailResponse(StackResponse):
    yaml_text: str
    resources: list[dict[str, Any]]   # aufgelöste Resource-Definitionen (denormalisiert)
    yaml_corrupt: bool = False        # True wenn yaml_text leer/nicht parsebar (BUG-76-4, Edge 16)


class StackVersionResponse(BaseModel):
    version_number: int
    yaml_text: str
    etag: str
    change_summary: Optional[str]
    edited_by_user_id: Optional[int]
    edited_by_username: Optional[str] = None
    created_at: str


class StackVersionSummary(BaseModel):
    """Listen-Eintrag ohne yaml_text (leichtgewichtig)."""
    version_number: int
    etag: str
    change_summary: Optional[str]
    edited_by_user_id: Optional[int]
    edited_by_username: Optional[str] = None
    created_at: str


class DiffEntry(BaseModel):
    key: str
    from_value: Optional[str] = None
    to_value: Optional[str] = None
    change: str   # "added" | "removed" | "changed" | "unchanged"


class StackDiffResponse(BaseModel):
    from_label: str
    to_label: str
    from_etag: str
    to_etag: str
    diff: list[DiffEntry]


class ValidationResult(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PreviewResource(BaseModel):
    type: str
    name: str
    node: str
    template: str
    cores: int
    memory: int
    disk: int
    pool: Optional[str] = None


class PreviewResult(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    resources: list[PreviewResource] = Field(default_factory=list)
    resource_count: int = 0


class EtagConflictResponse(BaseModel):
    """HTTP 409 Body bei ETag-Mismatch (AC-CONC-2)."""
    current_etag: str
    current_yaml: str
    your_yaml: str
    base_yaml: Optional[str] = None


class OrphanStackResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    version: str
    resource_count: int
    orphaned_at: Optional[str]
    ex_owner_user_id: Optional[int]


class PendingApprovalResponse(BaseModel):
    """HTTP 202 Body bei aktivem Approval-Workflow (AC-APPR-2/4)."""
    status: str = "pending_approval"
    approval_id: str
    poll_url: str


# ── Phase 2b: Deploy / Plan / Drift / Deployments ─────────────────────────────

class PlanResource(BaseModel):
    """Eine geplante Ressourcen-Änderung im tofu-Plan."""
    name: str
    action: str   # "create" | "update" | "delete" | "replace"


class PlanSummary(BaseModel):
    create: int = 0
    change: int = 0
    destroy: int = 0
    replace: int = 0
    resources: list[PlanResource] = Field(default_factory=list)


class PlanResponse(BaseModel):
    """POST /api/stacks/{id}/plan – Plan-Übersicht + Token (AC-2B-PLAN-1)."""
    plan_token: str
    operation: str          # "apply" | "destroy"
    summary: PlanSummary


class DeployRequest(BaseModel):
    """POST /api/stacks/{id}/deploy|destroy – führt exakt den reviewten Plan aus."""
    plan_token: str = Field(..., min_length=1)


class DeployJobResponse(BaseModel):
    """Job-Referenz nach Start eines Deploy/Destroy-Laufs."""
    job_id: str
    deployment_id: int
    operation: str
    deployment_state: str


class DeploymentResponse(BaseModel):
    id: int
    operation: str
    status: str
    job_id: Optional[str]
    plan_summary: Optional[PlanSummary] = None
    triggered_by_user_id: Optional[int]
    started_at: str
    finished_at: Optional[str]
    error_text: Optional[str]


class LiveResource(BaseModel):
    resource_name: str
    node: Optional[str]
    vmid: int
    kind: str = "vm"
    status: Optional[str] = None   # power status from cluster cache (running/stopped)
    portal_node_id: Optional[int] = None


class DriftItem(BaseModel):
    resource_name: str
    vmid: Optional[int] = None
    state: str   # "in_sync" | "changed" | "missing"


class DriftReport(BaseModel):
    drift_state: str   # "in_sync" | "out_of_sync"
    in_sync: int = 0
    changed: int = 0
    missing: int = 0
    items: list[DriftItem] = Field(default_factory=list)


class DeploymentStateResponse(BaseModel):
    deployment_state: str
    last_drift_state: Optional[str] = None
    last_drift_at: Optional[str] = None
