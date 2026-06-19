# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-75: Cluster-topology aggregation.

Two builders:
  * ``build_cluster_topology``  — cheap (cluster-cache + 3 bulk SELECTs, no
    per-VM Proxmox call), drives the 60-s poll of the default Compute view.
  * ``build_network_topology``  — expensive/lazy (per-VM ``get_vm_config`` for
    every *visible* guest, Semaphore-bounded), only fetched when the user
    switches to the Network view.

Both reuse the single-source RBAC/fan-out helpers in ``routers/cluster.py``
(``fetch_nodes`` / ``fetch_visible_vm_resources``) so the topology never sees a
guest the dashboard would hide (AC-RBAC-4). Multi-installation fan-out is
best-effort: an offline/misconfigured installation is flagged ``unreachable``
without failing the others (AC-BE-10 / EC-16).
"""
from __future__ import annotations

import logging
from collections import Counter

from backend.core.deps import CurrentUser
from backend.models.cluster import NodeInfo, VmInfo
from backend.routers.cluster import (
    _parse_networks,
    fetch_nodes,
    fetch_visible_vm_resources,
)
from backend.services.proxmox import ProxmoxAuth, ProxmoxClient

from .schemas import (
    ClusterTopologyResponse,
    NetworkTopologyResponse,
    TopoEdgeConn,
    TopoGuest,
    TopoInstallation,
    TopoNetDiag,
    TopoNetwork,
    TopoNode,
    TopoStats,
)

logger = logging.getLogger(__name__)

# Cap on concurrent per-VM config calls in the (lazy) network view.
_NETWORK_CONFIG_CONCURRENCY = 10

# Sentinel installation key for guests/nodes without a portal_node_id
# (proxmox-login / single default node without a configured portal node).
_DEFAULT_PNID = -1


# ── ID helpers (collision-free across installations) ──────────────────────────

def _inst_id(pnid: int | None) -> str:
    return f"inst{pnid}" if pnid is not None else "inst-default"


def _node_id(pnid: int | None, node: str) -> str:
    return f"{_inst_id(pnid)}-node-{node}"


def _guest_id(pnid: int | None, vm_type: str, vmid: int) -> str:
    return f"{_inst_id(pnid)}-{vm_type}-{vmid}"


def _bridge_id(pnid: int | None, node: str, bridge: str) -> str:
    return f"{_inst_id(pnid)}-{node}-{bridge}"


def _vnet_id(pnid: int | None, vnet: str) -> str:
    return f"{_inst_id(pnid)}-sdn-{vnet}"


def _ui_type(vm: VmInfo) -> str:
    """Proxmox 'qemu'|'lxc' → topology 'vm'|'lxc' (AC-BE-4)."""
    return "lxc" if vm.type == "lxc" else "vm"


# ── Installation metadata ─────────────────────────────────────────────────────

async def _installation_meta() -> dict[int, str]:
    """Map configured portal_node_id → installation name (best-effort)."""
    try:
        from backend.services.nodes_service import list_nodes
        rows = await list_nodes()
        return {row.id: row.name for row in rows}
    except Exception:
        return {}


def _pnid_of(obj: NodeInfo | VmInfo) -> int | None:
    return obj.portal_node_id


# ── Compute view ──────────────────────────────────────────────────────────────

async def build_cluster_topology(
    current_user: CurrentUser, force: bool = False
) -> ClusterTopologyResponse:
    nodes = await fetch_nodes(current_user, force=force, raise_on_empty=False)
    # with_ip=True so the compute view shows guest IPs (single source for all
    # views — board + network graph read the IP off the guest, no extra call).
    guests = await fetch_visible_vm_resources(current_user, force=force, with_ip=True)

    inst_names = await _installation_meta()

    # Bulk enrichment — Stack (one SELECT) + Ansible (one SELECT per installation).
    stack_map, stack_names = await _bulk_stack_map()
    ansible_map = await _bulk_ansible_states(guests)

    # Group by installation.
    inst_keys: list[int | None] = []
    seen: set[int | None] = set()
    # Order installations by configured order first, then any extras seen in data.
    for pnid in inst_names:
        if pnid not in seen:
            inst_keys.append(pnid)
            seen.add(pnid)
    for obj in (*nodes, *guests):
        k = _pnid_of(obj)
        if k not in seen:
            inst_keys.append(k)
            seen.add(k)

    nodes_by_inst: dict[int | None, list[NodeInfo]] = {}
    for n in nodes:
        nodes_by_inst.setdefault(_pnid_of(n), []).append(n)
    guests_by_inst: dict[int | None, list[VmInfo]] = {}
    for g in guests:
        guests_by_inst.setdefault(_pnid_of(g), []).append(g)

    installations: list[TopoInstallation] = []
    total_running = 0
    total_stack = 0
    total_vms = 0
    total_lxcs = 0

    for pnid in inst_keys:
        inst_nodes = nodes_by_inst.get(pnid, [])
        inst_guests = guests_by_inst.get(pnid, [])
        # A configured installation that returned no nodes is unreachable.
        unreachable = bool(pnid in inst_names) and not inst_nodes

        topo_nodes = [
            TopoNode(
                id=_node_id(pnid, n.node),
                node=n.node,
                label=n.node,
                status=n.status,
                cpu_count=n.maxcpu,
                ram_total=n.maxmem,
                disk_total=n.maxdisk,
            )
            for n in inst_nodes
        ]

        topo_guests: list[TopoGuest] = []
        for g in inst_guests:
            ut = _ui_type(g)
            if ut == "lxc":
                total_lxcs += 1
            else:
                total_vms += 1
            if g.status == "running":
                total_running += 1
            stack_name = stack_map.get((pnid, g.vmid))
            if stack_name:
                total_stack += 1
            topo_guests.append(
                TopoGuest(
                    id=_guest_id(pnid, ut, g.vmid),
                    parent_node_id=_node_id(pnid, g.node),
                    node=g.node,
                    type=ut,
                    label=g.name or str(g.vmid),
                    vmid=g.vmid,
                    status=g.status,
                    cpu=g.cpu,
                    maxcpu=g.maxcpu,
                    mem=g.mem,
                    maxmem=g.maxmem,
                    disk=g.disk,
                    maxdisk=g.maxdisk,
                    managed_by_stack=stack_name,
                    ssh_managed=ansible_map.get((pnid, g.vmid, g.type), False),
                    is_template=g.template == 1,
                    ip=g.ip,
                )
            )

        installations.append(
            TopoInstallation(
                id=_inst_id(pnid),
                name=inst_names.get(pnid) if pnid is not None else "default",
                unreachable=unreachable,
                nodes=topo_nodes,
                guests=topo_guests,
            )
        )

    stats = TopoStats(
        installations=len([i for i in installations if i.nodes or i.guests or i.unreachable]),
        nodes=sum(len(i.nodes) for i in installations),
        vms=total_vms,
        lxcs=total_lxcs,
        running=total_running,
        stack_managed=total_stack,
    )
    return ClusterTopologyResponse(
        installations=installations, stats=stats, stacks=stack_names
    )


async def _bulk_stack_map() -> tuple[dict[tuple[int | None, int], str], list[str]]:
    """Return ({(pnid, vmid) → stack_name}, [active stack names]) — best-effort.

    One SELECT each (Open-Point 7); unavailable Stacks module → empty maps.
    """
    try:
        from backend.plus.stacks.deployments import (
            bulk_stack_for_resources,
            list_active_stack_names,
        )
        raw = await bulk_stack_for_resources()
        names = await list_active_stack_names()
        return ({(pnid, vmid): name for (pnid, vmid), name in raw.items()}, names)
    except Exception:
        logger.debug("topology: stack bulk lookup unavailable", exc_info=True)
        return {}, []


async def _bulk_ansible_states(
    guests: list[VmInfo],
) -> dict[tuple[int | None, int, str], bool]:
    """Return {(pnid, vmid, kind) → ssh_managed} for guests with a portal_node_id."""
    out: dict[tuple[int | None, int, str], bool] = {}
    try:
        from backend.features.ansible_inventory.host_state import bulk_get_host_states
    except Exception:
        return out
    by_pnid: dict[int, list[tuple[int, str]]] = {}
    for g in guests:
        if g.portal_node_id is None:
            continue
        by_pnid.setdefault(g.portal_node_id, []).append((g.vmid, g.type))
    for pnid, candidates in by_pnid.items():
        try:
            states = await bulk_get_host_states(pnid, candidates)
        except Exception:
            continue
        for (vmid, kind), state in states.items():
            out[(pnid, vmid, kind)] = bool(state.get("ssh_managed"))
    return out


# ── Network view (lazy) ───────────────────────────────────────────────────────

def _is_bridge(raw: dict) -> bool:
    """Bridge-typed interface (vmbrN / ovsbrN / type 'bridge') — *not* a VLAN
    sub-interface (e.g. ``vmbr0.100``); those are never the ``bridge=`` target
    of a VM NIC."""
    if not isinstance(raw, dict):
        return False
    iface = str(raw.get("iface", ""))
    # Dotted numeric suffix → VLAN sub-interface, not a bridge.
    if "." in iface and iface.rsplit(".", 1)[-1].isdigit():
        return False
    typ = str(raw.get("type", "")).lower()
    if typ == "vlan":
        return False
    return "bridge" in typ or iface.startswith("vmbr") or iface.startswith("ovsbr")


def _bridge_address(raw: dict) -> str | None:
    """Bridge IP as CIDR (``192.168.1.1/24``) or plain address, if configured."""
    cidr = raw.get("cidr")
    if cidr:
        return str(cidr)
    addr = raw.get("address")
    if addr:
        netmask = raw.get("netmask")
        return f"{addr}/{netmask}" if netmask else str(addr)
    return None


def _resolve_installation_auth(node_row) -> tuple[ProxmoxClient, ProxmoxAuth] | None:
    """admin→operator→viewer token chain on a portal node (BUG-79-4 lesson).

    Reading /network and /cluster/sdn needs more than the viewer token; the
    topology view is authorized for every logged-in user so we pick the
    strongest available read token, mirroring PROJ-79/80.
    """
    from backend.services.service_accounts import _extract_token
    token = (
        _extract_token(node_row, "admin")
        or _extract_token(node_row, "operator")
        or _extract_token(node_row, "viewer")
    )
    if not token:
        return None
    client = ProxmoxClient(base_url=node_row.url, verify_ssl=node_row.verify_ssl)
    auth = ProxmoxAuth(kind="token", value=token.token_id, secret=token.token_secret)
    return client, auth


async def _collect_stack_bridges() -> dict[tuple[str, str], str]:
    """PROJ-87: best-effort map ``(node, bridge_name) → stack_name`` for
    stack-owned bridges, parsed from active stack specs (no tracking table)."""
    out: dict[tuple[str, str], str] = {}
    try:
        from backend.plus.stacks.deployments import list_active_stack_yaml
        from backend.plus.stacks.schemas import BridgeNetwork, StackSpec
        import yaml as _yaml
    except Exception:
        return out
    try:
        rows = await list_active_stack_yaml()
    except Exception:
        return out
    for row in rows:
        try:
            raw = _yaml.safe_load(row.get("yaml_text") or "")
            if not isinstance(raw, dict):
                continue
            spec = StackSpec(**raw)
        except Exception:
            continue
        for net in spec.networks:
            if isinstance(net, BridgeNetwork):
                out[(net.node, net.name)] = row["name"]
    return out


async def build_network_topology(
    current_user: CurrentUser, force: bool = False
) -> NetworkTopologyResponse:
    nodes = await fetch_nodes(current_user, force=force, raise_on_empty=False)
    # IPs come from the /cluster endpoint (single source); the network view only
    # needs bridges + connectivity → with_ip=False keeps the per-VM passes lean.
    guests = await fetch_visible_vm_resources(current_user, force=force, with_ip=False)

    stack_bridges = await _collect_stack_bridges()

    # Portal node rows by id for token resolution.
    node_rows: dict[int, object] = {}
    try:
        from backend.services.nodes_service import list_nodes
        for r in await list_nodes():
            node_rows[r.id] = r
    except Exception:
        node_rows = {}

    # Online physical node names per installation.
    online_nodes_by_inst: dict[int | None, list[str]] = {}
    for n in nodes:
        if n.status == "online":
            online_nodes_by_inst.setdefault(n.portal_node_id, []).append(n.node)

    networks: dict[str, TopoNetwork] = {}
    edges: list[TopoEdgeConn] = []
    unreachable: list[str] = []
    diagnostics: list[TopoNetDiag] = []

    inst_names = await _installation_meta()

    # Installations to walk: those that have a portal node row (token path).
    inst_pnids = sorted(
        {n.portal_node_id for n in nodes if n.portal_node_id is not None}
        | {g.portal_node_id for g in guests if g.portal_node_id is not None}
    )

    for pnid in inst_pnids:
        row = node_rows.get(pnid)
        resolved = _resolve_installation_auth(row) if row is not None else None
        if resolved is None:
            unreachable.append(_inst_id(pnid))
            diagnostics.append(TopoNetDiag(
                installation_id=_inst_id(pnid),
                name=inst_names.get(pnid, _inst_id(pnid)),
                sample_errors=["no_read_token"],
            ))
            continue
        client, auth = resolved
        nets_before = len(networks)
        edges_before = len(edges)

        # 1. SDN VNets (cluster-wide, one call). Silently skip when SDN absent.
        vnet_names: set[str] = set()
        try:
            for v in await client.get_sdn_vnets(auth):
                name = str(v.get("vnet") or "")
                if not name:
                    continue
                vnet_names.add(name)
                nid = _vnet_id(pnid, name)
                tag = v.get("tag")
                networks[nid] = TopoNetwork(
                    id=nid,
                    installation_id=_inst_id(pnid),
                    kind="sdn_vnet",
                    label=name,
                    scope="cluster",
                    node=None,
                    vlan_tag=int(tag) if isinstance(tag, int) else None,
                )
        except Exception:
            logger.debug("topology: SDN VNets unavailable for inst %s", pnid, exc_info=True)

        # 2. Node bridges per online node (mark stack-owned ones, PROJ-87).
        node_bridges: dict[str, set[str]] = {}
        for node_name in online_nodes_by_inst.get(pnid, []):
            try:
                ifaces = await client.get_node_network_interfaces(auth, node_name)
            except Exception:
                logger.debug(
                    "topology: bridges unavailable for inst %s node %s",
                    pnid, node_name, exc_info=True,
                )
                continue
            for raw in ifaces:
                if not _is_bridge(raw):
                    continue
                bname = str(raw.get("iface") or "")
                if not bname:
                    continue
                node_bridges.setdefault(node_name, set()).add(bname)
                owning = stack_bridges.get((node_name, bname))
                nid = _bridge_id(pnid, node_name, bname)
                networks[nid] = TopoNetwork(
                    id=nid,
                    installation_id=_inst_id(pnid),
                    kind="stack_bridge" if owning else "node_bridge",
                    label=bname,
                    scope="node",
                    node=node_name,
                    owning_stack=owning,
                    address=_bridge_address(raw),
                )

        # 3. Connectivity: per visible guest in this installation (Semaphore-bounded).
        inst_guests = [g for g in guests if g.portal_node_id == pnid]
        probed, ok, failed, reasons = await _add_connectivity_edges(
            client, auth, pnid, inst_guests, vnet_names, node_bridges, networks, edges
        )
        diagnostics.append(TopoNetDiag(
            installation_id=_inst_id(pnid),
            name=inst_names.get(pnid, _inst_id(pnid)),
            guests_total=probed,
            guests_ok=ok,
            guests_failed=failed,
            networks_found=len(networks) - nets_before,
            edges_found=len(edges) - edges_before,
            sample_errors=[r for r, _ in reasons.most_common(3)],
        ))
        if failed:
            logger.warning(
                "topology network view: inst %s — %d/%d guest configs failed "
                "(reasons: %s); bridges show but connectivity edges are missing",
                pnid, failed, probed, dict(reasons.most_common(5)),
            )

    return NetworkTopologyResponse(
        networks=list(networks.values()),
        edges_conn=edges,
        unreachable_installations=unreachable,
        diagnostics=diagnostics,
    )


async def _add_connectivity_edges(
    client: ProxmoxClient,
    auth: ProxmoxAuth,
    pnid: int | None,
    inst_guests: list[VmInfo],
    vnet_names: set[str],
    node_bridges: dict[str, set[str]],
    networks: dict[str, TopoNetwork],
    edges: list[TopoEdgeConn],
) -> tuple[int, int, int, Counter]:
    """Fetch each visible guest's config (Semaphore-bounded) and add one
    Gast→Netz edge per NIC. Returns ``(probed, ok, failed, reason_counter)`` for
    the per-installation diagnostics (PROJ-75 — a failing config fetch leaves the
    bridges visible but produces no connectivity edge)."""
    reasons: Counter = Counter()
    if not inst_guests:
        return 0, 0, 0, reasons

    # One client for the whole batch (keep-alive) → no TLS handshake per guest,
    # which made connectivity flaky on bigger installations (PROJ-75).
    cfg_map = await client.get_vm_configs_bulk(
        auth,
        [(vm.node, vm.vmid, vm.type) for vm in inst_guests],
        concurrency=_NETWORK_CONFIG_CONCURRENCY,
    )

    probed = len(inst_guests)
    ok = 0
    failed = 0
    for vm in inst_guests:
        cfg, reason = cfg_map.get((vm.node, vm.vmid), (None, "missing"))
        if reason is not None or cfg is None:
            failed += 1
            reasons[reason or "missing"] += 1
            continue
        ok += 1
        bridges = [nic.bridge for nic in _parse_networks(cfg) if nic.bridge]
        guest_id = _guest_id(pnid, _ui_type(vm), vm.vmid)
        for bridge in bridges:
            if bridge in vnet_names:
                target = _vnet_id(pnid, bridge)
            elif bridge in node_bridges.get(vm.node, set()):
                target = _bridge_id(pnid, vm.node, bridge)
            else:
                # EC-18: unknown network — keep the connectivity with a placeholder.
                target = _bridge_id(pnid, vm.node, bridge)
                if target not in networks:
                    networks[target] = TopoNetwork(
                        id=target,
                        installation_id=_inst_id(pnid),
                        kind="unknown",
                        label=bridge,
                        scope="node",
                        node=vm.node,
                    )
            edges.append(TopoEdgeConn(guest_id=guest_id, network_id=target))

    return probed, ok, failed, reasons
