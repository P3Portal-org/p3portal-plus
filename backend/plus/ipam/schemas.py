# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-42 Phase 2: Pydantic-Schemas für das interne Plus-IPAM.

IPv4-only (MVP), Validierung via ``ipaddress``-Stdlib (keine externe Dependency).
"""
from __future__ import annotations

import ipaddress
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


def _validate_ipv4(value: str, field: str) -> str:
    try:
        addr = ipaddress.ip_address(value)
    except ValueError:
        raise ValueError(f"{field}: '{value}' ist keine gültige IP-Adresse")
    if addr.version != 4:
        raise ValueError(f"{field}: nur IPv4 wird unterstützt (MVP)")
    return str(addr)


# ── Allocations ───────────────────────────────────────────────────────────────

class AllocationResponse(BaseModel):
    id: int
    pool_id: int
    ip: str
    status: Literal["pending", "confirmed", "orphaned"]
    source: Literal["proxmox", "manual", "stack"]
    vmid: Optional[int] = None
    portal_node_id: Optional[int] = None
    owner_username: Optional[str] = None
    job_id: Optional[str] = None
    stack_deployment_id: Optional[int] = None
    note: Optional[str] = None
    created_at: Optional[str] = None
    confirmed_at: Optional[str] = None
    pending_expires_at: Optional[str] = None


class ManualAllocationRequest(BaseModel):
    """Eine Fremd-IP (Nicht-Proxmox) manuell als belegt eintragen."""
    pool_id: int
    ip: str
    note: Optional[str] = Field(default=None, max_length=500)

    @field_validator("ip")
    @classmethod
    def _v_ip(cls, v: str) -> str:
        return _validate_ipv4(v, "ip")


class PoolUsageResponse(BaseModel):
    """Auslastung eines Pools: belegt / frei / gesamt (nutzbare Host-IPs)."""
    pool_id: int
    total: int
    used: int
    free: int
    allocations: list[AllocationResponse] = Field(default_factory=list)


# ── Netz-Freigaben ────────────────────────────────────────────────────────────

class NetworkGrantResponse(BaseModel):
    id: int
    kind: Literal["bridge", "vnet"]
    network_name: str
    node: Optional[str] = None
    vlan_tag: Optional[int] = None
    grantee_kind: Literal["user", "group"]
    grantee_id: int
    grantee_name: Optional[str] = None      # aufgelöster Anzeigename (best-effort)
    created_by: Optional[str] = None
    created_at: Optional[str] = None


class NetworkGrantRequest(BaseModel):
    kind: Literal["bridge", "vnet"]
    network_name: str = Field(min_length=1, max_length=100)
    node: Optional[str] = Field(default=None, max_length=100)
    vlan_tag: Optional[int] = Field(default=None, ge=1, le=4094)
    grantee_kind: Literal["user", "group"]
    grantee_id: int


# ── Konfiguration (Toggles) ───────────────────────────────────────────────────

class IpamConfigResponse(BaseModel):
    global_enabled: bool = False
    strict_network_visibility: bool = False
    updated_by: Optional[str] = None
    updated_at: Optional[str] = None


class IpamConfigUpdateRequest(BaseModel):
    global_enabled: Optional[bool] = None
    strict_network_visibility: Optional[bool] = None
