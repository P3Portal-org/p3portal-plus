# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""Pydantic schemas for PROJ-76 Phase 1 Stacks."""
from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator


# ── Resource spec (strict validation model) ──────────────────────────────────

class NetworkConfig(BaseModel):
    model_config = {"extra": "ignore"}
    bridge: str = "vmbr0"
    tag: Optional[int] = Field(None, ge=1, le=4094)


# ── PROJ-91: declarative stack firewall (guest rules + stack-owned security groups) ──
# Defined before VMResource/LXCResource/StackSpec so the ``firewall``/
# ``security_groups`` fields resolve without forward-reference rebuild gymnastics.

# Stack-owned security-group local name. The deploy prefixes it ``p3s<id>-<name>``
# (the cluster-unique Proxmox name), so the local name must be short: Proxmox SG
# names have a ~18-char limit, ``p3s9999-`` eats up to 8 → cap the local name at
# 10 (Tech-Design C, ⚠️ exact PVE limit is a verification point). Same charset as
# the PROJ-90 firewall-object regex (start letter, then alnum/-/_).
_SG_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


class StackFirewallRule(BaseModel):
    """PROJ-91: one declarative firewall rule on a stack guest or stack SG.

    Mirrors the PROJ-90 ``FirewallRuleWriteRequest`` fields **without ``pos``** —
    the rule order is the YAML list order (deterministic, top-down, AC-MODEL-5).
    Reuses the shared PROJ-90 validators (``validate_rule_semantics`` for
    action-per-direction + macro-XOR-proto/port, ``_validate_addr_spec`` for
    IP/CIDR/range/alias/+ipset) and ``rule_to_proxmox_params`` for the param
    mapping — identical rule behaviour in the imperative (PROJ-90) and declarative
    (PROJ-91) paths.
    """
    model_config = {"extra": "ignore"}

    type: Literal["in", "out", "group"]
    action: str = Field(..., min_length=1, max_length=64)
    enable: bool = True
    macro: Optional[str] = Field(None, max_length=64)
    source: Optional[str] = Field(None, max_length=512)
    dest: Optional[str] = Field(None, max_length=512)
    proto: Optional[str] = Field(None, max_length=32)
    sport: Optional[str] = Field(None, max_length=64)
    dport: Optional[str] = Field(None, max_length=64)
    iface: Optional[str] = Field(None, max_length=32)
    log: Optional[str] = Field(None, max_length=16)
    comment: Optional[str] = Field(None, max_length=255)
    icmp_type: Optional[str] = Field(None, max_length=32)

    @field_validator("source")
    @classmethod
    def _valid_source(cls, v: Optional[str]) -> Optional[str]:
        from backend.models.firewall import _validate_addr_spec
        return _validate_addr_spec(v, "source")

    @field_validator("dest")
    @classmethod
    def _valid_dest(cls, v: Optional[str]) -> Optional[str]:
        from backend.models.firewall import _validate_addr_spec
        return _validate_addr_spec(v, "dest")

    @model_validator(mode="after")
    def _semantics(self) -> "StackFirewallRule":
        from backend.models.firewall import validate_rule_semantics
        validate_rule_semantics(
            self.type, self.action, self.macro, self.proto, self.sport, self.dport
        )
        return self

    def to_proxmox_params(self) -> dict:
        """Map to the Proxmox firewall rule param dict (no ``pos`` — order = list order)."""
        from backend.models.firewall import rule_to_proxmox_params
        return rule_to_proxmox_params(self, with_pos=False)


class GuestFirewall(BaseModel):
    """PROJ-91: a guest's stack-managed firewall (AC-MODEL-2).

    ``enabled`` toggles BOTH Proxmox switches at deploy: the NIC ``firewall=true``
    flag (transpile, Pfad A) and the guest firewall option ``enable=1`` (commit,
    Pfad B). ``policy_in``/``policy_out`` are the default policies (Pflicht for
    real whitelisting). ``rules`` is the declarative top-down rule list.
    """
    model_config = {"extra": "ignore"}

    enabled: bool = False
    policy_in: Optional[Literal["ACCEPT", "DROP", "REJECT"]] = None
    policy_out: Optional[Literal["ACCEPT", "DROP", "REJECT"]] = None
    rules: list[StackFirewallRule] = Field(default_factory=list, max_length=100)


class StackSecurityGroup(BaseModel):
    """PROJ-91: a stack-owned security group (AC-MODEL-4).

    A named, reusable rule set on the stack. Deployed as a cluster security group
    prefixed ``p3s<id>-<name>`` and torn down with the stack. A guest references it
    via a ``group`` rule whose ``action`` is the local ``name`` (AC-SG-2).
    """
    model_config = {"extra": "ignore"}

    name: str = Field(..., min_length=1, max_length=10)
    comment: Optional[str] = Field(None, max_length=255)
    rules: list[StackFirewallRule] = Field(default_factory=list, max_length=100)

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        if not _SG_NAME_RE.match(v):
            raise ValueError(
                "security group name must start with a letter and contain only "
                "letters, digits, '-' or '_'"
            )
        return v


# PROJ-82: per-bus max interface index (Proxmox limits). scsi0 is reserved for
# the cloned root disk, so an extra scsi disk uses scsi1..scsi30, virtio0..15,
# sata0..5. Mirrors PROJ-81 _BUS_MAX (max index, not count).
_BUS_MAX_INDEX = {"scsi": 30, "virtio": 15, "sata": 5}
_INTERFACE_RE = re.compile(r"^(scsi|virtio|sata)([0-9]+)$")
_ROOT_INTERFACE = "scsi0"


class ExtraDisk(BaseModel):
    """PROJ-82: an additional (non-root) disk attached to a stack VM.

    The persisted key is ``interface`` (encodes bus + index, e.g. ``scsi1``) —
    the stable identity for bpg disk mapping (Tech-Design C). The GUI offers a
    bus dropdown and computes the next free index; hand-written YAML must set
    ``interface`` explicitly.
    """
    model_config = {"extra": "ignore"}

    interface: str = Field(..., min_length=2, max_length=16)
    size: int = Field(..., ge=1, le=16384)
    datastore: str = Field(..., min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")

    @field_validator("interface")
    @classmethod
    def _validate_interface(cls, v: str) -> str:
        m = _INTERFACE_RE.match(v)
        if not m:
            raise ValueError(
                "interface must be like scsi1/virtio0/sata2 (bus + index)"
            )
        if v == _ROOT_INTERFACE:
            raise ValueError("scsi0 is reserved for the root disk")
        bus, idx = m.group(1), int(m.group(2))
        if idx > _BUS_MAX_INDEX[bus]:
            raise ValueError(
                f"{bus} index {idx} exceeds the Proxmox limit "
                f"(max {bus}{_BUS_MAX_INDEX[bus]})"
            )
        return v


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
    # QEMU guest agent. Default True = full Proxmox agent integration (IP display,
    # agent-based graceful shutdown). Requires qemu-guest-agent installed+running
    # in the template/guest (best practice). Trade-off: if a guest does NOT run the
    # agent, bpg waits up to its agent timeout (~15 min) for an IP on apply — set
    # this False per-VM for templates without the agent (fast deploy, ~1-2 min).
    agent: bool = True
    network: Optional[NetworkConfig] = None
    tags: list[str] = Field(default_factory=list, max_length=10)
    pool: Optional[str] = None
    start_after_create: bool = True
    # PROJ-82: additional (non-root) disks, each with its own size + datastore +
    # stable interface. Default empty → 100% backward-compatible (AC-MODEL-3):
    # a stack without extra_disks validates and deploys exactly as before.
    extra_disks: list[ExtraDisk] = Field(default_factory=list, max_length=50)
    # PROJ-91: optional stack-managed guest firewall. Default None → no firewall
    # block → transpile + deploy byte-for-byte as today (AC-MODEL-1 / AC-TRANS-2).
    firewall: Optional[GuestFirewall] = None

    @model_validator(mode="after")
    def _validate_extra_disks(self) -> "VMResource":
        if not self.extra_disks:
            return self
        # Interfaces must be unique within a VM (root scsi0 is implicit and the
        # ExtraDisk validator already forbids scsi0). A collision would make bpg
        # ambiguous and risks replacing the wrong disk (EC-2).
        seen: set[str] = set()
        for d in self.extra_disks:
            if d.interface in seen:
                raise ValueError(f"duplicate disk interface '{d.interface}'")
            seen.add(d.interface)
        return self


# ── PROJ-86: LXC container resource ──────────────────────────────────────────

# ostemplate file-ID form `storage:vztmpl/<name>.tar.{zst,gz,xz}` (AC-TMPL-1).
# An LXC unpacks this tarball — it is NOT a VM-template VMID (no clone lookup).
_OSTEMPLATE_RE = re.compile(r"^[A-Za-z0-9._-]+:vztmpl/\S+$")

# LXC mountpoint slot `mp0..mp255` (Proxmox CT limit). The numeric index is the
# stable identity for the destructive diff (Tech-Design I, Muster PROJ-82
# ``interface``); bpg maps mount_point blocks positionally, so the GUI keeps the
# indices contiguous and the transpile emits them in index order.
_MP_RE = re.compile(r"^mp([0-9]+)$")
_MP_MAX_INDEX = 255

# RFC-952/1123 subset: one or more dot-separated labels, each 1–63 chars of
# alnum/hyphen, no leading/trailing hyphen, total ≤253 (AC-RES-3 hostname).
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)"
    r"(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$"
)


class LXCFeatures(BaseModel):
    """PROJ-86: optional container feature flags (AC-FEAT).

    All off (default) → the transpiler emits **no** ``features`` block (AC-FEAT-1).
    ``mount`` is a Proxmox mount-type list string (e.g. ``"nfs;cifs"``).
    """
    model_config = {"extra": "ignore"}

    nesting: bool = False
    keyctl: bool = False
    fuse: bool = False
    mount: Optional[str] = Field(None, max_length=128)


class LXCMount(BaseModel):
    """PROJ-86: an additional mountpoint on a stack LXC (AC-MOUNT).

    LXC pendant to PROJ-82's ExtraDisk. ``id`` (``mp0..mp255``) is the stable
    identity for the destructive diff + GUI next-free-index. bpg has no explicit
    mp-index attribute (mountpoints are positional), so the transpile sorts by
    the numeric index and emits them in order; the diff is positional.
    """
    model_config = {"extra": "ignore"}

    id: str = Field(..., min_length=3, max_length=8)
    datastore: str = Field(..., min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    size: int = Field(..., ge=1, le=16384)
    path: str = Field(..., min_length=1, max_length=255)
    backup: bool = False

    @field_validator("id")
    @classmethod
    def _validate_id(cls, v: str) -> str:
        m = _MP_RE.match(v)
        if not m:
            raise ValueError("mount id must be like mp0/mp1 (mp + index)")
        if int(m.group(1)) > _MP_MAX_INDEX:
            raise ValueError(f"mount index exceeds the Proxmox limit (max mp{_MP_MAX_INDEX})")
        return v

    @field_validator("path")
    @classmethod
    def _validate_path(cls, v: str) -> str:
        if not v.startswith("/"):
            raise ValueError("mount path must be absolute (start with /)")
        if "\n" in v or "\r" in v or "\x00" in v:
            raise ValueError("mount path must be a single line")
        return v


class LXCResource(BaseModel):
    """PROJ-86: strict validation model for a single LXC container resource.

    Discriminator ``type="lxc"``. Common fields mirror VMResource (AC-RES-2);
    LXC-specific fields cover the ostemplate, rootfs, mountpoints, features and
    the unprivileged flag (AC-RES-3). Login/IP (root password / SSH keys / IP)
    live in the PROJ-85 cloud-init store, NOT here (AC-GUEST-1).
    """
    model_config = {"extra": "ignore"}

    type: Literal["lxc"]
    # Common (identical to VMResource, AC-RES-2)
    name: str = Field(..., min_length=1, max_length=64)
    node: str = Field(..., min_length=1)
    count: int = Field(1, ge=1, le=50)
    tags: list[str] = Field(default_factory=list, max_length=10)
    pool: Optional[str] = None
    start_after_create: bool = True
    network: Optional[NetworkConfig] = None
    # Optional explicit VMID (identical semantics to VMResource): omitted →
    # Proxmox auto-assigns a free VMID; set + count>1 → vmid, vmid+1, … (base +
    # offset). A taken VMID makes Proxmox reject the apply.
    vmid: Optional[int] = Field(None, ge=100, le=999999999)
    # LXC-specific (AC-RES-3)
    template: str = Field(..., min_length=1)
    cores: int = Field(1, ge=1, le=128)
    memory: int = Field(512, ge=16, le=1048576)
    swap: int = Field(512, ge=0, le=1048576)
    rootfs_size: int = Field(8, ge=1, le=16384)
    rootfs_datastore: str = Field(
        ..., min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$"
    )
    hostname: str = Field(..., min_length=1, max_length=253)
    # unprivileged is the secure default (AC-SEC-1). privileged (False) is allowed
    # with a UI warning + audit (AC-SEC-2/3); no RBAC gate (Tech-Design J).
    unprivileged: bool = True
    features: Optional[LXCFeatures] = None
    mounts: list[LXCMount] = Field(default_factory=list, max_length=24)
    # PROJ-91: optional stack-managed guest firewall (same as VMResource, AC-MODEL-1).
    firewall: Optional[GuestFirewall] = None

    @field_validator("template")
    @classmethod
    def _validate_template(cls, v: str) -> str:
        if not _OSTEMPLATE_RE.match(v):
            raise ValueError(
                "template must be an ostemplate file-id like "
                "'local:vztmpl/debian-12-standard.tar.zst'"
            )
        return v

    @field_validator("hostname")
    @classmethod
    def _validate_hostname(cls, v: str) -> str:
        if not _HOSTNAME_RE.match(v):
            raise ValueError("hostname is not a valid RFC-1123 hostname")
        return v

    @model_validator(mode="after")
    def _validate_mounts(self) -> "LXCResource":
        if not self.mounts:
            return self
        # mp indices must be unique within a container (422, AC-MOUNT-2).
        seen: set[str] = set()
        for m in self.mounts:
            if m.id in seen:
                raise ValueError(f"duplicate mount id '{m.id}'")
            seen.add(m.id)
        return self


# Discriminated union over ``type``: a resource without a ``type`` key is
# normalized to "vm" by StackSpec's before-validator (AC-RES-1, Tech-Design D).
StackResource = Annotated[
    Union[VMResource, LXCResource], Field(discriminator="type")
]


# ── PROJ-87: stack-owned network resources (Bridge / SDN-VNet) ────────────────

# Node-bridge name (Proxmox), identical to PROJ-79 (`vmbrN`, 1–4 digits).
_BRIDGE_NAME_RE = re.compile(r"^vmbr\d{1,4}$")
# SDN object id (zone/vnet), identical to PROJ-80 (≤8 chars, alnum, leading alpha).
_SDN_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,7}$")


class BridgeNetwork(BaseModel):
    """PROJ-87: a stack-owned Linux bridge on a node (AC-BR-1).

    Transpiles to bpg ``proxmox_virtual_environment_network_linux_bridge`` — a
    node-local change (no global SDN apply). The bridge lives in the stack state,
    is created before the guests that reference it (``depends_on``) and torn down
    with the stack (AC-ISO-1 / AC-LC-1).
    """
    model_config = {"extra": "ignore"}

    kind: Literal["bridge"] = "bridge"
    name: str = Field(..., min_length=4, max_length=11)
    node: str = Field(..., min_length=1)
    vlan_aware: bool = False
    # Soft MTU range (PROJ-79); a bridge inherits the port MTU when unset.
    mtu: Optional[int] = Field(None, ge=1280, le=65520)
    comment: Optional[str] = Field(None, max_length=255)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        if not _BRIDGE_NAME_RE.match(v):
            raise ValueError("bridge name must match vmbrN (e.g. vmbr10)")
        return v


class VNetNetwork(BaseModel):
    """PROJ-89: a stack-owned SDN VNet (Simple zone + VNet + Subnet, optional SNAT).

    Created in the stack state, owned by the stack, torn down with it (AC-ISO-1).
    Transpiles to a bpg ``…_sdn_zone_simple`` + ``…_sdn_vnet`` + ``…_sdn_subnet``
    (+ a per-stack applier). The MVP creates its own Simple zone (``zone`` is the
    seam for the follow-up "reference an existing zone" phase, AC-ZONE-4).

    Subnet (CIDR + gateway) is mandatory in the MVP — every VNet gets one
    (AC-SUBNET-1). ``snat`` is opt-in (default OFF) → an isolated L2 segment by
    default, controlled Internet egress only when explicitly enabled (AC-SUBNET-2).
    ``tag`` stays forward-compat-optional (VLAN/VXLAN zone = Non-Goal, ignored by
    the Simple-zone transpile).
    """
    model_config = {"extra": "ignore"}

    kind: Literal["vnet"]
    name: str = Field(..., min_length=1, max_length=8)
    zone: str = Field(..., min_length=1, max_length=8)
    tag: Optional[int] = Field(None, ge=1, le=4094)
    # Mandatory subnet in the MVP (AC-SUBNET-1). An isolated subnet still has a
    # gateway — ``snat`` only toggles the NAT. A missing gateway therefore makes
    # ``snat=true`` impossible to mis-configure (EC-1, structurally enforced).
    subnet_cidr: str = Field(..., max_length=64)
    subnet_gateway: str = Field(..., max_length=64)
    snat: bool = False

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        if not _SDN_ID_RE.match(v):
            raise ValueError("vnet name must be ≤8 alnum chars starting with a letter")
        return v

    @field_validator("zone")
    @classmethod
    def _validate_zone(cls, v: str) -> str:
        if not _SDN_ID_RE.match(v):
            raise ValueError("zone name must be ≤8 alnum chars starting with a letter")
        return v

    @model_validator(mode="after")
    def _check_subnet(self) -> "VNetNetwork":
        """Validate the subnet CIDR + that the gateway lies inside it (AC-SUBNET-1).

        ipaddress-stdlib (Muster CloudInitBlock / PROJ-80). A gateway outside the
        subnet, or a malformed CIDR/gateway → 422 before any plan (EC-10).
        """
        import ipaddress
        try:
            net = ipaddress.IPv4Network(self.subnet_cidr, strict=False)
        except (ipaddress.AddressValueError, ipaddress.NetmaskValueError, ValueError) as exc:
            raise ValueError(
                f"subnet_cidr is not a valid IPv4 CIDR: {self.subnet_cidr}"
            ) from exc
        try:
            gw = ipaddress.IPv4Address(self.subnet_gateway)
        except (ipaddress.AddressValueError, ValueError) as exc:
            raise ValueError(
                f"subnet_gateway is not a valid IPv4 address: {self.subnet_gateway}"
            ) from exc
        if gw not in net:
            raise ValueError(
                f"subnet_gateway {self.subnet_gateway} is not inside {self.subnet_cidr}"
            )
        return self


# Discriminated union over ``kind``: a network dict without a ``kind`` key is
# normalized to "bridge" by StackSpec's before-validator (Tech-Design B).
NetworkResource = Annotated[
    Union[BridgeNetwork, VNetNetwork], Field(discriminator="kind")
]


# ── PROJ-85: Cloud-Init login/IP blocks (stored separately, not in YAML) ──────

# Grobe SSH-Public-Key-Form (AC-KEY-2): ssh-…/ecdsa-…/sk-…@openssh.com + base64.
# Strukturierte .tf.json-Werte ⇒ kein Shell-/HCL-Injection (AC-SEC-2); die Regex
# wehrt nur offensichtlichen Müll/Mehrzeiler ab.
_SSH_KEY_RE = re.compile(r"^(ssh-[A-Za-z0-9-]+|ecdsa-[A-Za-z0-9-]+|sk-[A-Za-z0-9@.-]+)\s+\S+")


# Großzügiger Per-Key-Längen-Cap (OBS-3, /qa S629): ein OpenSSH-RSA-4096-Public-Key
# ist ~720 Zeichen, ed25519 ~80 — 8192 deckt jeden realen Key + Kommentar ab und
# wehrt einen authentifizierten Self-DoS via überlanger Keys ab (das DB-JSON-Array
# ist sonst nur durch die Anzahl 20 begrenzt).
_SSH_KEY_MAX_LEN = 8192


def _validate_ssh_keys(keys: list[str]) -> list[str]:
    out: list[str] = []
    for raw in keys:
        k = raw.strip()
        if not k:
            continue
        if "\n" in k or "\r" in k:
            raise ValueError("ssh key must be a single line")
        if len(k) > _SSH_KEY_MAX_LEN:
            raise ValueError(
                f"ssh key too long (max {_SSH_KEY_MAX_LEN} characters)"
            )
        if not _SSH_KEY_RE.match(k):
            raise ValueError(
                "invalid SSH public key form (expected ssh-…/ecdsa-…/sk-…)"
            )
        out.append(k)
    return out


class CloudInitBlock(BaseModel):
    """Input block for one cloud-init target (default or per-VM override).

    Passwort ist write-only: leer/weggelassen = unverändert (Merge, EC-6). Die
    kontextabhängigen Gates (Lockout AC-ACT-4, static+count>1 AC-IP-3) laufen in
    der Service-Schicht (brauchen das gespeicherte Passwort bzw. die Spec). Hier
    nur die *reinen* Form-Checks (SSH-Key-Form, IPv4-CIDR/Gateway).
    """
    model_config = {"extra": "ignore"}

    vm_name: str = Field("", max_length=64)   # '' = Stack-Default, sonst Override
    enabled: bool = False
    username: Optional[str] = Field(None, max_length=64)
    password: Optional[str] = Field(None, max_length=512)
    ssh_keys: list[str] = Field(default_factory=list, max_length=20)
    ip_mode: Optional[Literal["dhcp", "static"]] = None
    ip_address_cidr: Optional[str] = Field(None, max_length=64)
    ip_gateway: Optional[str] = Field(None, max_length=64)
    dns_servers: Optional[str] = Field(None, max_length=255)
    dns_domain: Optional[str] = Field(None, max_length=255)

    @field_validator("ssh_keys")
    @classmethod
    def _check_keys(cls, v: list[str]) -> list[str]:
        return _validate_ssh_keys(v)

    @model_validator(mode="after")
    def _check_ip(self) -> "CloudInitBlock":
        import ipaddress
        if self.ip_mode == "static":
            if not self.ip_address_cidr:
                raise ValueError("static IP requires ip_address_cidr (e.g. 10.0.0.5/24)")
            if not self.ip_gateway:
                raise ValueError("static IP requires ip_gateway")
            try:
                ipaddress.IPv4Interface(self.ip_address_cidr)
            except (ipaddress.AddressValueError, ipaddress.NetmaskValueError, ValueError) as exc:
                raise ValueError(f"ip_address_cidr is not a valid IPv4 CIDR: {self.ip_address_cidr}") from exc
            try:
                ipaddress.IPv4Address(self.ip_gateway)
            except (ipaddress.AddressValueError, ValueError) as exc:
                raise ValueError(f"ip_gateway is not a valid IPv4 address: {self.ip_gateway}") from exc
        return self


class CloudInitConfigRequest(BaseModel):
    """PUT /api/stacks/{id}/cloud-init – full replace (default + overrides)."""
    model_config = {"extra": "ignore"}

    default: CloudInitBlock = Field(default_factory=CloudInitBlock)
    overrides: list[CloudInitBlock] = Field(default_factory=list, max_length=200)


class CloudInitBlockOut(BaseModel):
    """Output block – Passwort NIE im Klartext, nur password_set (AC-STORE-4/UI-4)."""
    vm_name: str
    enabled: bool
    username: Optional[str] = None
    password_set: bool = False
    ssh_keys: list[str] = Field(default_factory=list)
    ip_mode: Optional[str] = None
    ip_address_cidr: Optional[str] = None
    ip_gateway: Optional[str] = None
    dns_servers: Optional[str] = None
    dns_domain: Optional[str] = None
    # Override-Name nicht (mehr) im aktuellen Spec → "verwaist" (EC-4); nur Anzeige.
    orphan: bool = False


class CloudInitConfigResponse(BaseModel):
    default: CloudInitBlockOut
    overrides: list[CloudInitBlockOut] = Field(default_factory=list)


class StackSpec(BaseModel):
    """Strict validation model for a whole stack definition (AC-YAML-1/2/3)."""
    model_config = {"extra": "ignore"}

    name: str = Field(..., min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    description: Optional[str] = Field(None, max_length=500)
    version: str = "1.0.0"
    # PROJ-86: discriminated union over ``type`` (vm → VMResource, lxc →
    # LXCResource). The before-validator normalizes every legacy VM dict (no
    # ``type`` key) to ``type="vm"`` so existing VM-only specs validate
    # byte-for-byte unchanged (AC-RES-1 / AC-TRANS-2, Tech-Design D).
    resources: list[StackResource] = Field(default_factory=list)
    # PROJ-87: optional stack-owned networks (Bridge / SDN-VNet). Default empty ⇒
    # byte-for-byte transpile as today (AC-MODEL-1 / AC-TRANS-2 / EC-1).
    networks: list[NetworkResource] = Field(default_factory=list)
    # PROJ-91: optional stack-owned security groups (reusable rule sets). Default
    # empty ⇒ byte-for-byte transpile as today (AC-MODEL-3 / AC-TRANS-2).
    security_groups: list[StackSecurityGroup] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _default_discriminators(cls, data: Any) -> Any:
        """Inject the discriminator default for resources (vm) and networks (bridge).

        Pydantic-v2 needs the discriminator value present in the *input* — a
        ``Literal[...]=default`` does NOT rescue a missing key for a discriminated
        union (S631/632 gotcha). So a resource dict without ``type`` → ``vm`` and a
        network dict without ``kind`` → ``bridge``. Instance form (a real
        ``VMResource(...)``/``BridgeNetwork(...)``) is left untouched via the
        ``isinstance(.,dict)`` guard.
        """
        if isinstance(data, dict):
            res = data.get("resources")
            if isinstance(res, list):
                normalized: list[Any] = []
                for r in res:
                    if isinstance(r, dict) and "type" not in r:
                        r = {**r, "type": "vm"}
                    normalized.append(r)
                data = {**data, "resources": normalized}
            nets = data.get("networks")
            if isinstance(nets, list):
                norm_nets: list[Any] = []
                for n in nets:
                    if isinstance(n, dict) and "kind" not in n:
                        n = {**n, "kind": "bridge"}
                    norm_nets.append(n)
                data = {**data, "networks": norm_nets}
        return data

    @model_validator(mode="after")
    def _validate_networks(self) -> "StackSpec":
        """Cross-checks (422): network names stack-unique and ≠ any resource name.

        A name collision with a *foreign* (existing) bridge/VNet is NOT a schema
        check — it needs a Proxmox read and runs as the ``prepare_plan`` pre-check
        (Tech-Design G / AC-MODEL-3).
        """
        if not self.networks:
            return self
        net_names = [n.name for n in self.networks]
        dupes = {n for n in net_names if net_names.count(n) > 1}
        if dupes:
            raise ValueError(f"duplicate network names: {', '.join(sorted(dupes))}")
        resource_names = {r.name for r in self.resources}
        clash = set(net_names) & resource_names
        if clash:
            raise ValueError(
                f"network name(s) clash with resource name(s): {', '.join(sorted(clash))}"
            )
        return self

    @model_validator(mode="after")
    def _validate_security_groups(self) -> "StackSpec":
        """PROJ-91: stack security-group names must be unique (422 on duplicate).

        A ``group``-rule reference to a name that is neither a stack SG nor an
        existing cluster SG is NOT checked here — it needs a Proxmox read and runs
        as the ``prepare_plan`` pre-check (Tech-Design G / AC-SG-4).
        """
        if not self.security_groups:
            return self
        names = [g.name for g in self.security_groups]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            raise ValueError(f"duplicate security group names: {', '.join(sorted(dupes))}")
        return self


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


class DestructiveDiskChange(BaseModel):
    """PROJ-82: a disk change in the plan that would destroy data (AC-REMOVE).

    Computed by a state-vs-spec disk diff in ``prepare_plan`` (not from the plan,
    which is resource-level). Surfaced so the Plan-Modal can require the extra
    stack-name confirmation before apply.
    """
    vm: str
    interface: str
    reason: str             # "removed" | "shrunk"
    old_size: int
    new_size: Optional[int] = None


class ForeignPendingSdn(BaseModel):
    """PROJ-89: a FOREIGN pending SDN object the cluster-wide apply would commit.

    "Foreign" = not part of this stack's own zone/VNet names. Surfaced (not
    blocked) so the user knows their SDN deploy's ``PUT /cluster/sdn`` will also
    commit these staged manual changes (AC-PENDING-1). Read-only, best-effort.
    """
    kind: str   # "zone" | "vnet"
    name: str
    state: str  # "new" | "changed" | "deleted"


class PlanResponse(BaseModel):
    """POST /api/stacks/{id}/plan – Plan-Übersicht + Token (AC-2B-PLAN-1)."""
    plan_token: str
    operation: str          # "apply" | "destroy"
    summary: PlanSummary
    # PROJ-82: disks that the apply would remove/shrink (= data loss). Empty for
    # pure additions/grows. Drives the extra Plan-Modal confirmation (AC-REMOVE).
    destructive_disk_changes: list[DestructiveDiskChange] = Field(default_factory=list)
    # PROJ-89: foreign staged SDN objects the cluster-wide apply would also commit
    # (AC-PENDING-1). Empty when no VNet is involved or no foreign pending exists.
    # Additive → the /plan endpoint renders it generically (no endpoint change).
    foreign_pending_sdn: list[ForeignPendingSdn] = Field(default_factory=list)


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
