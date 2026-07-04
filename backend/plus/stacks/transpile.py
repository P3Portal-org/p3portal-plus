# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-76 Phase 2b: transpile the structured P3 model → OpenTofu ``.tf.json``.

Pure function — fully unit-testable without tofu/Proxmox (Tech-Design Open Point 1).

Design rules:
  * ``count > 1`` ⇒ **N separately named resources** (``web-1..web-N`` via the
    Phase-1 naming convention), **not** tofu ``count``/``for_each``. This keeps
    ``stack_deployed_resources.resource_name`` 1:1 with the Phase-1 preview and
    avoids ``count.index`` interpolation bugs.
  * **``vm_id`` omitted by default** → Proxmox auto-assigns a free VMID, so a
    stack never collides with or overwrites a foreign VM (AC-2B-ISO-3). An
    optional explicit ``vmid`` (base + offset for count>1) is honored when set.
  * **Provider block carries no inline credentials** — bpg reads the token from
    the environment injected by the engine (AC-2B-TRANS-4 / Phase 2a).
  * Only ``resource`` blocks are emitted — no ``import``, no node-wide
    ``data source`` (AC-2B-ISO-2).

bpg resource ``proxmox_virtual_environment_vm`` attribute mapping (AC-2B-TRANS-2):
  template → ``clone.vm_id`` (resolved template VMID) · cores/sockets → ``cpu``
  · memory → ``memory.dedicated`` · disk → ``disk.size`` · cpu_type → ``cpu.type``
  · network.bridge/tag → ``network_device.bridge``/``vlan_id`` · tags → ``tags``
  · pool → ``pool_id`` · start_after_create → ``started`` · count → N instances.
"""
from __future__ import annotations

import re
from typing import Any

from .schemas import BridgeNetwork, LXCResource, StackSpec, VMResource, VNetNetwork

# Pinned bpg provider (image bundle). Kept in sync with the Dockerfile
# ARG BPG_PROVIDER_VERSION; only the major.minor constraint is asserted here.
# PROJ-89: bumped 0.78 → 0.109 — the 0.109 SDN resources (zone/vnet/subnet/
# applier) carry the cluster-wide ``PUT /cluster/sdn`` that PROJ-89 needs, and
# the spike (S654) verified all existing VM/LXC/Bridge stacks transpile
# byte-stable on 0.109. ``~> 0.78`` would reject 0.109 → ``tofu init`` against
# the 0.109-only offline mirror would fail for EVERY stack, which is exactly why
# the /deploy precondition is "re-verify all deployed stacks on 0.109".
_PROVIDER_SOURCE = "bpg/proxmox"
_PROVIDER_VERSION = "~> 0.109"

# Default block interface for a cloned root disk (model has no datastore field
# in Phase 1; the clone inherits the template datastore — size triggers a resize).
_DEFAULT_DISK_INTERFACE = "scsi0"

# PROJ-87: bpg Linux-bridge resource type (node-local, no global SDN apply).
_BRIDGE_RESOURCE_TYPE = "proxmox_virtual_environment_network_linux_bridge"

# PROJ-89: bpg-0.109 SDN resource types (Schema-Dump data/bpg-0109-schema.json).
# The long ``…_sdn_*`` names are what the pinned 0.109 exposes — NOT the
# ``proxmox_sdn_*`` short names (those are the announced v1.0 rename). All four
# are flat resources (simple scalar attributes), so a single dict per resource is
# valid — no list-of-every-key gymnastics like network_device. They are marked
# ``deprecated`` in 0.109 (the v1.0 rename) → a deprecation warning, still works.
_SDN_ZONE_RESOURCE_TYPE = "proxmox_virtual_environment_sdn_zone_simple"
_SDN_VNET_RESOURCE_TYPE = "proxmox_virtual_environment_sdn_vnet"
_SDN_SUBNET_RESOURCE_TYPE = "proxmox_virtual_environment_sdn_subnet"
_SDN_APPLIER_RESOURCE_TYPE = "proxmox_virtual_environment_sdn_applier"
# A single applier per stack triggers the cluster-wide apply on create
# (Tech-Design B). Its tofu label is constant within a stack.
_APPLIER_LABEL = "stack_apply"


def _expanded_names(r: Any) -> list[str]:
    """Resolve a resource's instance names (count → suffix), matching Phase-1 preview.

    Duck-typed (``r.count`` / ``r.name``) so it works for both VM and LXC resources.
    """
    if r.count <= 1:
        return [r.name]
    return [f"{r.name}-{i}" for i in range(1, r.count + 1)]


_MP_INDEX_RE = re.compile(r"^mp([0-9]+)$")


def _mp_sort_key(m: Any) -> int:
    """Numeric index of a mountpoint id (``mp3`` → 3) for deterministic emit order."""
    match = _MP_INDEX_RE.match(getattr(m, "id", "") or "")
    return int(match.group(1)) if match else 0


def _cloud_init_block(ci: Any, for_lxc: bool = False) -> dict[str, Any]:
    """PROJ-85: map a resolved cloud-init record → bpg ``initialization{}`` (D).

    ``ci`` is a ``cloud_init.CloudInitResolved`` (duck-typed here to keep this
    module import-cycle-free and pure). Empty fields are omitted — no empty keys
    in the .tf.json. ``initialization`` is a *separate* attribute from ``clone``
    and is **not** added to ``lifecycle.ignore_changes`` → a cloud-init change is
    a real, tracked change on the next deploy (EC-7, intended).

    PROJ-86: ``for_lxc=True`` omits ``user_account.username`` — an LXC logs in as
    root, so the username field is ignored for LXC targets (AC-GUEST-2 / EC-7).
    """
    init: dict[str, Any] = {}

    user_account: dict[str, Any] = {}
    if not for_lxc and getattr(ci, "username", None):
        user_account["username"] = ci.username
    if getattr(ci, "password", None):
        user_account["password"] = ci.password
    if getattr(ci, "ssh_keys", None):
        user_account["keys"] = list(ci.ssh_keys)
    if user_account:
        init["user_account"] = user_account

    ip_mode = getattr(ci, "ip_mode", None)
    if ip_mode == "static":
        ipv4: dict[str, Any] = {"address": ci.ip_address_cidr}
        if getattr(ci, "ip_gateway", None):
            ipv4["gateway"] = ci.ip_gateway
        # bpg models ip_config as a list (one entry per NIC).
        init["ip_config"] = [{"ipv4": ipv4}]
        dns: dict[str, Any] = {}
        if getattr(ci, "dns_servers", None):
            dns["servers"] = list(ci.dns_servers)
        if getattr(ci, "dns_domain", None):
            dns["domain"] = ci.dns_domain
        if dns:
            init["dns"] = dns
    elif ip_mode == "dhcp":
        init["ip_config"] = [{"ipv4": {"address": "dhcp"}}]
    # ip_mode None → no ip_config (template/cloud-init default, AC-IP-2).

    return init


def _bridge_resource_block(net: BridgeNetwork) -> dict[str, Any]:
    """PROJ-87: build a single bpg ``…_network_linux_bridge`` resource block.

    Node-local (``node_name``), no global SDN apply. Optional ``mtu``/``comment``
    are omitted when unset (no empty keys). Created before the guests that
    reference it and torn down with the stack (depends_on, §C / AC-LC-1).
    """
    block: dict[str, Any] = {
        "node_name": net.node,
        "name": net.name,
        "vlan_aware": net.vlan_aware,
    }
    if net.mtu is not None:
        block["mtu"] = net.mtu
    if net.comment:
        block["comment"] = net.comment
    return block


# ── PROJ-89: SDN zone / vnet / subnet / applier blocks ────────────────────────


def _sdn_zone_block(zone_name: str, nodes: list[str]) -> dict[str, Any]:
    """Build a bpg ``…_sdn_zone_simple`` block (AC-ZONE-1).

    A Simple zone is an isolated VNet bridge (NAT/routed setups). ``id`` = the
    zone name, ``ipam = "pve"`` (the default IPAM), ``nodes`` = the distinct
    physical Proxmox nodes the zone+VNets are deployed on (AC-ZONE-2, derived
    from the guests that reference a VNet of this zone). Flat scalar attributes
    → a single dict is a valid framework value (unlike network_device).
    """
    return {"id": zone_name, "ipam": "pve", "nodes": sorted(set(nodes))}


def _sdn_vnet_block(net: VNetNetwork, zone_addr: str) -> dict[str, Any]:
    """Build a bpg ``…_sdn_vnet`` block (AC-VNET-1/2).

    ``id`` = the VNet name, ``zone`` = the zone name. The ``zone`` is a plain
    string attribute (not an interpolation) → tofu has no implicit dependency, so
    an explicit ``depends_on`` on the zone resource is required to create the zone
    BEFORE the VNet (AC-LC-1 "Provider-Graph depends_on"). No ``tag`` (Simple zone
    — VLAN/VXLAN tagging is a Non-Goal in the MVP).
    """
    return {"id": net.name, "zone": net.zone, "depends_on": [zone_addr]}


def _sdn_subnet_block(net: VNetNetwork, vnet_addr: str) -> dict[str, Any]:
    """Build a bpg ``…_sdn_subnet`` block (AC-SUBNET-1/2/3).

    Flat: ``vnet`` references the VNet, ``cidr``/``gateway`` define the segment,
    ``snat`` (opt-in, default off) enables Internet egress. The ``id`` is
    computed (``<zone>-<cidr>``) → never set. ``depends_on`` the VNet (string
    attribute, no implicit dependency) so the subnet is created AFTER the VNet.
    """
    return {
        "vnet": net.name,
        "cidr": net.subnet_cidr,
        "gateway": net.subnet_gateway,
        "snat": net.snat,
        "depends_on": [vnet_addr],
    }


def _sdn_applier_block(subnet_addrs: list[str]) -> dict[str, Any]:
    """Build the single per-stack ``…_sdn_applier`` block (Tech-Design B).

    ``on_create=true`` triggers the cluster-wide ``PUT /cluster/sdn`` when the
    applier is created; with ``depends_on=[<every subnet>]`` it lands in the
    provider graph between the SDN objects and the guests → the VNet bridge is
    live when the guests are attached (AC-LC-1). ``on_destroy=false`` avoids the
    #2212 destroy-order trap (OpenTofu tears the applier down first) — P3 commits
    the removal itself via ``apply_sdn`` after ``tofu destroy`` (runner).
    """
    return {
        "on_create": True,
        "on_destroy": False,
        "depends_on": list(subnet_addrs),
    }


def _vm_resource_block(
    r: VMResource, resolved_name: str, template_vmid: int, vmid: int | None = None,
    ci: Any = None, net_depends: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a single bpg ``proxmox_virtual_environment_vm`` resource block."""
    # PROJ-82: root disk (scsi0, cloned, inherits template datastore — only size
    # triggers a resize) plus optional extra disks. ``disk`` is always a *list* of
    # blocks — the canonical .tf.json form for the repeated bpg disk block. bpg's
    # framework migration is strict: a single object is rejected with "list of
    # object required" (S654, bpg-0.109 bump). The root block carries NO
    # datastore_id (it inherits the template, Entscheidung 3 / AC-TRANSPILE-3);
    # each extra disk carries its own datastore_id + size (AC-TRANSPILE-1).
    disk_value: list[dict[str, Any]] = [
        {"interface": _DEFAULT_DISK_INTERFACE, "size": r.disk}
    ] + [
        {"interface": d.interface, "size": d.size, "datastore_id": d.datastore}
        for d in r.extra_disks
    ]

    block: dict[str, Any] = {
        "node_name": r.node,
        "name": resolved_name,
        # vm_id omitted → Proxmox auto-assigns a free VMID (collision-safe,
        # AC-2B-ISO-3). Only set when the user explicitly pinned a VMID.
        "clone": {"vm_id": template_vmid},
        "cpu": {"cores": r.cores, "sockets": r.sockets, "type": r.cpu_type},
        "memory": {"dedicated": r.memory},
        "disk": disk_value,
        "started": r.start_after_create,
        # agent enabled (default) → full integration (IP display, graceful
        # shutdown); needs qemu-guest-agent in the guest. Disabled per-VM →
        # bpg does not wait for the agent, so apply finishes fast.
        "agent": {"enabled": r.agent},
    }

    # network_device: bpg 0.109 models this as a framework list-of-object
    # attribute (optional+computed), unlike the lenient SDK blocks
    # (cpu/memory/disk/…). In .tf.json the value must be a *list* AND each element
    # must carry *every* attribute key — a partial object is rejected with
    # "attributes … are required" (S654 bpg bump). Unset keys are null; the
    # provider applies its own defaults (model, enabled, mac_address, …).
    bridge = r.network.bridge if r.network else "vmbr0"
    vlan_id = r.network.tag if (r.network and r.network.tag) else None
    # PROJ-91: the NIC firewall flag (Pfad A, schema-verified). True only when the
    # guest has an active firewall block — the prerequisite for the Pfad-B rules to
    # take effect (AC-ENABLE-1). Otherwise None (unset) → byte-for-byte legacy.
    fw_enabled = bool(r.firewall and r.firewall.enabled)
    block["network_device"] = [{
        "bridge": bridge,
        "vlan_id": vlan_id,
        "disconnected": None,
        "enabled": None,
        "firewall": True if fw_enabled else None,
        "mac_address": None,
        "model": None,
        "mtu": None,
        "queues": None,
        "rate_limit": None,
        "trunks": None,
    }]

    if r.tags:
        block["tags"] = list(r.tags)
    if r.pool:
        block["pool_id"] = r.pool
    if vmid is not None:
        block["vm_id"] = vmid

    # PROJ-85: optional cloud-init login/IP. Only emitted when a resolved block
    # exists for this VM (active default or override); otherwise the VM inherits
    # everything from the template (Weg 1, byte-for-byte legacy).
    if ci is not None:
        init = _cloud_init_block(ci)
        if init:
            block["initialization"] = init

    # clone is a create-time-only relationship; after the VM exists the bpg
    # provider would otherwise report a perpetual diff on every plan/refresh
    # (phantom drift). Ignoring it makes drift detection report only real changes.
    block["lifecycle"] = {"ignore_changes": ["clone"]}

    # PROJ-87/89: when the referenced network is stack-owned, an explicit
    # depends_on creates it before this guest (and tears it down after — provider
    # graph). The guest references the network by string only, so tofu has no
    # implicit dependency → the depends_on is required (AC-MODEL-2 / AC-LC-1).
    # ``net_depends`` maps a stack network name → the tofu address the guest must
    # depend on: a stack bridge → the bridge resource; a stack VNet → the SDN
    # applier (so the cluster-wide apply has committed before the guest is
    # created and the VNet bridge is live, PROJ-89 AC-LC-1).
    if net_depends and bridge in net_depends:
        block["depends_on"] = [net_depends[bridge]]

    return block


def _lxc_resource_block(
    r: LXCResource, resolved_name: str, idx: int, ci: Any = None,
    net_depends: dict[str, str] | None = None, vmid: int | None = None,
) -> dict[str, Any]:
    """PROJ-86: build a single bpg ``proxmox_virtual_environment_container`` block.

    An LXC unpacks an ostemplate (``operating_system.template_file_id``) — it is
    NOT a clone (no VMID lookup). rootfs is a single ``disk`` (datastore + size);
    extra volumes are ``mount_point`` blocks; ``features``/``unprivileged`` are
    LXC-only. Login/IP come from the resolved cloud-init block (root, no username).
    """
    block: dict[str, Any] = {
        "node_name": r.node,
        "unprivileged": r.unprivileged,
        "started": r.start_after_create,
        "operating_system": {"template_file_id": r.template},
        "cpu": {"cores": r.cores},
        "memory": {"dedicated": r.memory, "swap": r.swap},
        # rootfs — a single managed disk; size in GiB (int), datastore explicit.
        "disk": {"datastore_id": r.rootfs_datastore, "size": r.rootfs_size},
    }

    # Optional explicit VMID (else Proxmox auto-assigns a free one).
    if vmid is not None:
        block["vm_id"] = vmid

    # Mountpoints (AC-MOUNT). bpg maps mount_point blocks positionally, so emit
    # them in numeric-index order. ``volume`` = the datastore id → bpg allocates
    # a fresh managed volume of ``size`` (bpg mount size is a unit string).
    if r.mounts:
        mps: list[dict[str, Any]] = []
        for m in sorted(r.mounts, key=_mp_sort_key):
            mp: dict[str, Any] = {
                "volume": m.datastore, "size": f"{m.size}G", "path": m.path,
            }
            if m.backup:
                mp["backup"] = True
            mps.append(mp)
        block["mount_point"] = mps

    # Container features (AC-FEAT). Default all-off → no features block emitted.
    feats: dict[str, Any] = {}
    if r.features:
        if r.features.nesting:
            feats["nesting"] = True
        if r.features.keyctl:
            feats["keyctl"] = True
        if r.features.fuse:
            feats["fuse"] = True
        if r.features.mount:
            feats["mount"] = r.features.mount
    if feats:
        block["features"] = feats

    # network_interface (list of NICs); eth0 by default.
    bridge = r.network.bridge if r.network else "vmbr0"
    nic: dict[str, Any] = {"name": "eth0", "bridge": bridge}
    if r.network and r.network.tag:
        nic["vlan_id"] = r.network.tag
    # PROJ-91: add the NIC firewall key only when the container has an active
    # firewall block (network_interface is a lenient SDK block — omit otherwise,
    # byte-for-byte legacy, AC-ENABLE-1/3).
    if r.firewall and r.firewall.enabled:
        nic["firewall"] = True
    block["network_interface"] = [nic]

    if r.tags:
        block["tags"] = list(r.tags)
    if r.pool:
        block["pool_id"] = r.pool

    # initialization: hostname is always set (suffixed per instance for count>1);
    # login/IP merged from the resolved cloud-init block (no username = root).
    init: dict[str, Any] = {}
    if ci is not None:
        init = _cloud_init_block(ci, for_lxc=True)
    hostname = r.hostname if r.count <= 1 else f"{r.hostname}-{idx + 1}"
    init["hostname"] = hostname
    block["initialization"] = init

    # operating_system (the ostemplate) is a create-time-only relationship —
    # like clone for a VM. Ignoring it prevents phantom/re-create drift on every
    # plan; initialization is NOT ignored → a cloud-init change is real drift.
    block["lifecycle"] = {"ignore_changes": ["operating_system"]}

    # PROJ-87/89: stack-owned network dependency (see _vm_resource_block, AC-LC-1).
    if net_depends and bridge in net_depends:
        block["depends_on"] = [net_depends[bridge]]

    return block


def stack_to_tfjson(
    spec: StackSpec,
    template_vmids: dict[tuple[str, str] | str, int],
    cloudinit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate the full ``main.tf.json`` dict for a stack.

    ``template_vmids`` maps each ``(target_node, template_name)`` → its resolved VMID
    (looked up against the cluster at plan time, see ``resolve_template_vmids``). This
    keys per node so a cluster with per-node template copies (same name, different
    VMIDs) clones the copy on each VM's target node. A plain-string ``template_name``
    key is accepted as a node-agnostic fallback (single-node / tests). A missing
    template raises ``KeyError`` so the caller can surface a clear plan error (Edge 2/5).

    ``cloudinit`` (PROJ-85, Tech-Design C) maps each *resolved* (count-expanded)
    VM name → a ``cloud_init.CloudInitResolved``. Default ``None`` ⇒ byte-for-byte
    identical to the legacy output (PROJ-82 tests stay green). A VM without an
    entry gets no ``initialization{}`` block (template inheritance, Weg 1).
    """
    ci_map = cloudinit or {}
    # PROJ-87/89: stack-owned networks. A guest referencing a stack network name
    # gets an explicit depends_on; any other name is an existing/shared
    # bridge/VNet (reference, AC-MODEL-2). ``net_depends`` maps each stack network
    # name → the tofu address the guest must depend on: a bridge → its bridge
    # resource; a VNet → the single SDN applier (so the cluster-wide apply has run
    # and the VNet bridge is live before the guest, PROJ-89 AC-LC-1).
    stack_bridges = {n.name: n for n in spec.networks if isinstance(n, BridgeNetwork)}
    stack_vnets = {n.name: n for n in spec.networks if isinstance(n, VNetNetwork)}
    applier_addr = f"{_SDN_APPLIER_RESOURCE_TYPE}.{_APPLIER_LABEL}"
    net_depends: dict[str, str] = {}
    for name in stack_bridges:
        net_depends[name] = f"{_BRIDGE_RESOURCE_TYPE}.{name}"
    for name in stack_vnets:
        net_depends[name] = applier_addr

    vm_resources: dict[str, dict[str, Any]] = {}
    lxc_resources: dict[str, dict[str, Any]] = {}
    for r in spec.resources:
        if getattr(r, "type", "vm") == "lxc":
            # LXC: ostemplate passes through directly — no VMID lookup (AC-TMPL-1).
            for idx, resolved_name in enumerate(_expanded_names(r)):
                # Explicit VMID (optional): base + offset so count>1 stays unique.
                lxc_vmid = (r.vmid + idx) if getattr(r, "vmid", None) is not None else None
                lxc_resources[resolved_name] = _lxc_resource_block(
                    r, resolved_name, idx, ci=ci_map.get(resolved_name),
                    net_depends=net_depends, vmid=lxc_vmid,
                )
            continue
        # VM: clone the template VMID of the copy on THIS resource's target node
        # (AC-2B-TRANS-2). Prod passes (node, template) keys so a cluster with
        # per-node template copies (same name, different VMIDs) clones the right one;
        # a plain-string key is a node-agnostic fallback (single-node / tests).
        node_key = (r.node, r.template)
        if node_key in template_vmids:
            tmpl_vmid = template_vmids[node_key]
        elif r.template in template_vmids:
            tmpl_vmid = template_vmids[r.template]
        else:
            raise KeyError(r.template)
        for idx, resolved_name in enumerate(_expanded_names(r)):
            # Tofu resource labels must be unique; resolved_name already is
            # (Phase-1 duplicate-name validation guarantees it).
            # Explicit VMID (optional): base + offset so count>1 stays unique.
            vmid = (r.vmid + idx) if r.vmid is not None else None
            vm_resources[resolved_name] = _vm_resource_block(
                r, resolved_name, tmpl_vmid, vmid=vmid,
                ci=ci_map.get(resolved_name), net_depends=net_depends,
            )

    # PROJ-87: stack-owned bridges → a bpg bridge resource per network.
    bridge_resources: dict[str, dict[str, Any]] = {
        net.name: _bridge_resource_block(net) for net in stack_bridges.values()
    }

    # PROJ-89: stack-owned SDN. Build the zones (deduped over the zone value),
    # VNets, subnets and one applier. Only when the stack actually declares VNets
    # → a pure VM/LXC/Bridge stack emits NO SDN resource (byte-for-byte legacy,
    # AC-MODEL-4 / AC-TRANS-2).
    zone_resources: dict[str, dict[str, Any]] = {}
    vnet_resources: dict[str, dict[str, Any]] = {}
    subnet_resources: dict[str, dict[str, Any]] = {}
    applier_resources: dict[str, dict[str, Any]] = {}
    if stack_vnets:
        # Map each guest's referenced bridge → its node, to derive the zone nodes.
        guest_nodes_for_vnet: dict[str, set[str]] = {n: set() for n in stack_vnets}
        all_guest_nodes: set[str] = set()
        for r in spec.resources:
            bridge = r.network.bridge if r.network else None
            all_guest_nodes.add(r.node)
            if bridge in guest_nodes_for_vnet:
                guest_nodes_for_vnet[bridge].add(r.node)
        # Zone dedup over the zone value (AC-ZONE-1 / EC-7): one zone resource per
        # distinct zone name, spanning the distinct guest nodes of the VNets in it.
        zone_nodes: dict[str, set[str]] = {}
        for vnet in stack_vnets.values():
            zone_nodes.setdefault(vnet.zone, set()).update(
                guest_nodes_for_vnet.get(vnet.name, set())
            )
        for zone_name, nodes in zone_nodes.items():
            # Fallback to all distinct guest nodes when no guest references the
            # zone's VNets directly (AC-ZONE-2).
            zone_resources[zone_name] = _sdn_zone_block(
                zone_name, sorted(nodes or all_guest_nodes)
            )
        subnet_addrs: list[str] = []
        for vnet in stack_vnets.values():
            zone_addr = f"{_SDN_ZONE_RESOURCE_TYPE}.{vnet.zone}"
            vnet_addr = f"{_SDN_VNET_RESOURCE_TYPE}.{vnet.name}"
            vnet_resources[vnet.name] = _sdn_vnet_block(vnet, zone_addr)
            subnet_resources[vnet.name] = _sdn_subnet_block(vnet, vnet_addr)
            subnet_addrs.append(f"{_SDN_SUBNET_RESOURCE_TYPE}.{vnet.name}")
        applier_resources[_APPLIER_LABEL] = _sdn_applier_block(sorted(subnet_addrs))

    # Only emit a resource-type map when it has members → a pure-VM stack
    # produces byte-for-byte the legacy output (no empty …_container/…_bridge/SDN
    # map, AC-TRANS-2 / EC-1). A mixed stack produces every map (AC-TRANS-1).
    resource_block: dict[str, Any] = {}
    if vm_resources:
        resource_block["proxmox_virtual_environment_vm"] = vm_resources
    if lxc_resources:
        resource_block["proxmox_virtual_environment_container"] = lxc_resources
    if bridge_resources:
        resource_block[_BRIDGE_RESOURCE_TYPE] = bridge_resources
    if zone_resources:
        resource_block[_SDN_ZONE_RESOURCE_TYPE] = zone_resources
    if vnet_resources:
        resource_block[_SDN_VNET_RESOURCE_TYPE] = vnet_resources
    if subnet_resources:
        resource_block[_SDN_SUBNET_RESOURCE_TYPE] = subnet_resources
    if applier_resources:
        resource_block[_SDN_APPLIER_RESOURCE_TYPE] = applier_resources

    return {
        "terraform": {
            "required_providers": {
                "proxmox": {
                    "source": _PROVIDER_SOURCE,
                    "version": _PROVIDER_VERSION,
                }
            }
        },
        # No inline credentials — token via env (AC-2B-TRANS-4).
        "provider": {"proxmox": {}},
        "resource": resource_block,
    }
