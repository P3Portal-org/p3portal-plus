# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-75: Pydantic response models for the cluster-topology view.

Pure read-view — no DB tables. IDs are prefixed by installation (+node for
node-local objects) so gleichnamige VMs/Nodes/Bridges across installations never
collide (AC-MI-4 / AC-NET-VIEW-9 / EC-10).
"""
from __future__ import annotations

from pydantic import BaseModel


# ── Compute view (/api/topology/cluster) ──────────────────────────────────────

class TopoNode(BaseModel):
    id: str                 # inst{pnid}-node-{name}
    node: str               # physical Proxmox node name (for /compute/{node})
    label: str
    status: str             # online | offline
    cpu_count: int = 0
    ram_total: int = 0      # bytes
    disk_total: int = 0     # bytes


class TopoGuest(BaseModel):
    id: str                 # inst{pnid}-{vm|lxc}-{vmid}
    parent_node_id: str
    node: str               # physical node name (for /vm/{node}/{type}/{vmid})
    type: str               # vm | lxc
    label: str
    vmid: int
    status: str             # running | stopped | paused
    cpu: float = 0.0        # fraction 0.0–1.0
    maxcpu: int = 0
    mem: int = 0            # bytes used
    maxmem: int = 0         # bytes total
    disk: int = 0           # bytes used (QEMU often 0 = N/A)
    maxdisk: int = 0        # bytes total
    managed_by_stack: str | None = None  # stack name when stack-managed (PROJ-76/86)
    ssh_managed: bool = False            # PROJ-83/84 ansible-inventory flag
    is_template: bool = False
    ip: str | None = None                # first non-loopback IPv4 (best-effort)


class TopoInstallation(BaseModel):
    id: str                 # inst{pnid} | inst-default
    name: str
    unreachable: bool = False
    nodes: list[TopoNode] = []
    guests: list[TopoGuest] = []


class TopoStats(BaseModel):
    installations: int = 0
    nodes: int = 0
    vms: int = 0
    lxcs: int = 0
    running: int = 0
    stack_managed: int = 0


class ClusterTopologyResponse(BaseModel):
    installations: list[TopoInstallation] = []
    stats: TopoStats = TopoStats()
    stacks: list[str] = []  # active stack names for the filter dropdown


# ── Network view (/api/topology/network) ──────────────────────────────────────

class TopoNetwork(BaseModel):
    id: str                 # inst{pnid}-{node}-{bridge} | inst{pnid}-sdn-{vnet}
    installation_id: str
    kind: str               # node_bridge | sdn_vnet | stack_bridge | unknown
    label: str
    scope: str              # node | cluster
    node: str | None = None         # physical node (node-local nets)
    vlan_tag: int | None = None
    owning_stack: str | None = None  # set for stack-owned bridges (PROJ-87)
    address: str | None = None       # bridge IP/CIDR (e.g. 192.168.1.1/24), if any


class TopoEdgeConn(BaseModel):
    guest_id: str
    network_id: str


class TopoNetDiag(BaseModel):
    """Per-installation diagnostics for the network view (PROJ-75).

    Surfaced in the UI so a silently-empty network view becomes debuggable:
    if ``guests_failed`` is high the per-VM ``get_vm_config`` calls are failing
    (token VM.Audit / timeout / unreachable) — the bridges can still show while
    no connectivity edges are produced.
    """
    installation_id: str
    name: str
    guests_total: int = 0       # visible guests probed for connectivity
    guests_ok: int = 0          # config fetched successfully
    guests_failed: int = 0      # config fetch raised (see sample_errors)
    networks_found: int = 0     # bridges + VNets + stack/unknown for this inst
    edges_found: int = 0        # connectivity edges produced for this inst
    sample_errors: list[str] = []  # top reasons (e.g. "ReadTimeout", "403")


class NetworkTopologyResponse(BaseModel):
    networks: list[TopoNetwork] = []
    edges_conn: list[TopoEdgeConn] = []
    unreachable_installations: list[str] = []  # installation ids best-effort
    diagnostics: list[TopoNetDiag] = []        # per-installation connectivity diag
