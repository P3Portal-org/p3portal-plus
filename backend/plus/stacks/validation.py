# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-76: 3-stufige Validierungs-Pipeline (Tech-Design F).

1. Struktur  – Pydantic StackSpec/VMResource: Pflichtfelder, Ranges, Regex → Error (blockt Save).
2. Semantik  – Node-/Template-/Pool-Existenz → Warning (blockt Save NIE).
3. Forward   – unbekannte YAML-Keys → Warning (AC-YAML-7).

Eingabe-Normalisierung: yaml_text ist Wahrheit wenn gesetzt; sonst strukturierte
Felder → kanonisches YAML. Kein Strict-YAML-Loader (Forward-Compat).
"""
from __future__ import annotations

from typing import Any, Optional

import yaml
from pydantic import ValidationError

from backend.core.plus_protocol import plus_behavior

from .schemas import (
    BridgeNetwork,
    LXCFeatures,
    LXCMount,
    LXCResource,
    StackCreateRequest,
    StackSpec,
    VMResource,
    VNetNetwork,
)

# Bekannte Felder für Unknown-Field-Warnings (Forward-Compat)
_STACK_KNOWN = {"name", "description", "version", "resources", "networks"}
_VM_KNOWN = set(VMResource.model_fields.keys())
# PROJ-86: typ-aware unknown-field sets (Tech-Design D).
_LXC_KNOWN = set(LXCResource.model_fields.keys())
_LXC_FEATURES_KNOWN = set(LXCFeatures.model_fields.keys())
_LXC_MOUNT_KNOWN = set(LXCMount.model_fields.keys())
_NETWORK_KNOWN = {"bridge", "tag"}
# PROJ-87: typ-aware network field sets (Tech-Design B/D).
_BRIDGE_KNOWN = set(BridgeNetwork.model_fields.keys())
_VNET_KNOWN = set(VNetNetwork.model_fields.keys())


class StackInputError(ValueError):
    """Raised when input cannot be parsed into a raw stack dict (e.g. broken YAML)."""


def parse_input(req: StackCreateRequest) -> tuple[dict[str, Any], str]:
    """Return (raw_dict, canonical_yaml_text).

    yaml_text mode  → stored verbatim, parsed for validation.
    structured mode → serialized to canonical YAML.
    Raises StackInputError on broken/empty input.
    """
    if req.yaml_text is not None and req.yaml_text.strip():
        try:
            raw = yaml.safe_load(req.yaml_text)
        except yaml.YAMLError as exc:
            raise StackInputError(f"yaml_parse_error: {exc}") from exc
        if not isinstance(raw, dict):
            raise StackInputError("yaml_root_not_mapping")
        return raw, req.yaml_text

    # structured mode
    raw = {}
    if req.name is not None:
        raw["name"] = req.name
    if req.description is not None:
        raw["description"] = req.description
    if req.version is not None:
        raw["version"] = req.version
    if req.resources is not None:
        raw["resources"] = req.resources
    if not raw:
        raise StackInputError("empty_input")
    canonical = yaml.safe_dump(raw, sort_keys=False, default_flow_style=False, allow_unicode=True)
    return raw, canonical


def _collect_unknown_field_warnings(raw: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    for k in raw:
        if k not in _STACK_KNOWN:
            warnings.append(f"unknown stack field '{k}' ignored")
    resources = raw.get("resources")
    if isinstance(resources, list):
        for i, res in enumerate(resources):
            if not isinstance(res, dict):
                continue
            # PROJ-86: typ-aware — LXC resources use a different field set.
            is_lxc = res.get("type") == "lxc"
            known = _LXC_KNOWN if is_lxc else _VM_KNOWN
            for k in res:
                if k not in known:
                    warnings.append(f"unknown field '{k}' in resource #{i + 1} ignored")
            net = res.get("network")
            if isinstance(net, dict):
                for k in net:
                    if k not in _NETWORK_KNOWN:
                        warnings.append(f"unknown network field '{k}' in resource #{i + 1} ignored")
            if is_lxc:
                feats = res.get("features")
                if isinstance(feats, dict):
                    for k in feats:
                        if k not in _LXC_FEATURES_KNOWN:
                            warnings.append(
                                f"unknown feature field '{k}' in resource #{i + 1} ignored"
                            )
                mounts = res.get("mounts")
                if isinstance(mounts, list):
                    for m in mounts:
                        if not isinstance(m, dict):
                            continue
                        for k in m:
                            if k not in _LXC_MOUNT_KNOWN:
                                warnings.append(
                                    f"unknown mount field '{k}' in resource #{i + 1} ignored"
                                )
    # PROJ-87: unknown network fields (typ-aware bridge vs. vnet).
    networks = raw.get("networks")
    if isinstance(networks, list):
        for i, net in enumerate(networks):
            if not isinstance(net, dict):
                continue
            known = _VNET_KNOWN if net.get("kind") == "vnet" else _BRIDGE_KNOWN
            for k in net:
                if k not in known:
                    warnings.append(f"unknown field '{k}' in network #{i + 1} ignored")
    return warnings


def _format_pydantic_errors(exc: ValidationError) -> list[str]:
    out: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"])
        out.append(f"{loc}: {err['msg']}")
    return out


def validate_structure(raw: dict[str, Any]) -> tuple[Optional[StackSpec], list[str], list[str]]:
    """Stage 1 (Pydantic) + Stage 3 (unknown fields).

    Returns (spec_or_none, errors, warnings). spec is None when errors exist.
    """
    warnings = _collect_unknown_field_warnings(raw)
    try:
        spec = StackSpec(**raw)
    except ValidationError as exc:
        return None, _format_pydantic_errors(exc), warnings

    # Eindeutigkeit der Resource-Namen im Stack (AC-YAML-4)
    names = [r.name for r in spec.resources]
    dupes = {n for n in names if names.count(n) > 1}
    errors: list[str] = []
    if dupes:
        errors.append(f"duplicate resource names: {', '.join(sorted(dupes))}")

    # PROJ-89: SDN/VNet networks are now built (the MVP gate that rejected
    # kind="vnet" with vnet_not_supported_yet is removed). They transpile to bpg
    # SDN resources (zone/vnet/subnet/applier) and the cluster-wide global apply
    # is serialized by the _SDN_APPLY_LOCK (Tech-Design B/C). Pure structural
    # validation already happened (StackSpec); the cluster-wide name-collision
    # check is a Proxmox read → runs as the prepare_plan pre-check (Tech-Design G).

    if errors:
        return None, errors, warnings
    return spec, [], warnings


async def semantic_warnings(spec: StackSpec) -> list[str]:
    """Stage 2 – best-effort semantic checks. Never raises, only warns."""
    warnings: list[str] = []
    if not spec.resources:
        return warnings

    pools_active = False
    try:
        pools_active = bool(plus_behavior.can_use_pools_quotas())
    except Exception:
        pools_active = False

    # Distinct node existence (real check against nodes table)
    distinct_nodes = {r.node for r in spec.resources}
    node_known: dict[str, bool] = {}
    for node_name in distinct_nodes:
        node_known[node_name] = await _node_exists(node_name)
        if not node_known[node_name]:
            warnings.append(f"node '{node_name}' not found")

    # Pool capability warnings (AC-YAML-9 / Edge 11)
    for i, r in enumerate(spec.resources):
        if r.pool and not pools_active:
            warnings.append(
                f"resource #{i + 1}: pool field ignored (no pools capability)"
            )

    # PROJ-82: extra-disk datastore warnings (AC-VAL-2, never blocks save). Only
    # touches Proxmox when a resource actually declares extra disks, and only
    # warns about nodes that DO exist (a missing node already warned above).
    # Best-effort: any failure (offline/permission) → no warning.
    if any(getattr(r, "extra_disks", None) for r in spec.resources):
        storage_cache: dict[str, Optional[set[str]]] = {}
        for i, r in enumerate(spec.resources):
            if not getattr(r, "extra_disks", None) or not node_known.get(r.node, True):
                continue
            if r.node not in storage_cache:
                storage_cache[r.node] = await _image_storages_on_node(r.node)
            known_storages = storage_cache[r.node]
            if known_storages is None:
                continue  # couldn't verify → don't warn
            for d in r.extra_disks:
                if d.datastore not in known_storages:
                    warnings.append(
                        f"resource #{i + 1}: datastore '{d.datastore}' not found "
                        f"on node '{r.node}' (or doesn't hold disk images)"
                    )

    # PROJ-86: LXC ostemplate existence warning (AC-TMPL-3, never blocks save).
    # Lists the installed vztmpl tarballs on the target node and warns when an
    # LXC's template_file_id isn't found — surfaced as a Preview/Plan warning so
    # the user isn't surprised by a silent apply failure (EC-2). Best-effort: any
    # failure (offline/permission/no token) → no warning.
    if any(getattr(r, "type", "vm") == "lxc" for r in spec.resources):
        tmpl_cache: dict[str, Optional[set[str]]] = {}
        for i, r in enumerate(spec.resources):
            if getattr(r, "type", "vm") != "lxc" or not node_known.get(r.node, True):
                continue
            if r.node not in tmpl_cache:
                tmpl_cache[r.node] = await _lxc_templates_on_node(r.node)
            known_templates = tmpl_cache[r.node]
            if known_templates is None:
                continue  # couldn't verify → don't warn
            if r.template not in known_templates:
                warnings.append(
                    f"resource #{i + 1}: LXC template '{r.template}' not found "
                    f"on node '{r.node}'"
                )

    # PROJ-87: stack-owned network checks (AC-MODEL-3 best-effort, never blocks).
    stack_bridges = {n.name: n for n in spec.networks if isinstance(n, BridgeNetwork)}
    if stack_bridges:
        bridge_cache: dict[str, Optional[set[str]]] = {}
        for net in stack_bridges.values():
            # Bridge node existence (a missing node would fail the apply).
            if not await _node_exists(net.node):
                warnings.append(f"network '{net.name}': node '{net.node}' not found")
                continue
            # Name collides with an existing (unmanaged) bridge on that node →
            # the hard 422 comes from the prepare_plan pre-check (which has the
            # Proxmox read safely); here it's a soft heads-up at save time.
            if net.node not in bridge_cache:
                bridge_cache[net.node] = await _bridges_on_node(net.node)
            existing = bridge_cache[net.node]
            if existing is not None and net.name in existing:
                warnings.append(
                    f"network '{net.name}': a bridge with this name already "
                    f"exists on node '{net.node}' (deploy will fail)"
                )
        # Guest referencing a stack bridge but running on a different node →
        # the bridge is created on net.node only (no auto multi-node spread, §C).
        for i, r in enumerate(spec.resources):
            bridge = r.network.bridge if r.network else None
            if bridge and bridge in stack_bridges:
                net = stack_bridges[bridge]
                if r.node != net.node:
                    warnings.append(
                        f"resource #{i + 1} on node '{r.node}' references stack "
                        f"bridge '{bridge}' which is created on node '{net.node}'"
                    )

    # PROJ-91: firewall-rules-without-enable warning (AC-ENABLE-2, EC-1). A guest
    # with rules/policies but firewall.enabled false/missing → the rules are
    # silently ineffective (the NIC firewall flag stays off). Pure spec check, no
    # Proxmox read; never blocks save (Entscheidung #3).
    for i, r in enumerate(spec.resources):
        fw = getattr(r, "firewall", None)
        if fw is None:
            continue
        has_intent = bool(fw.rules) or fw.policy_in is not None or fw.policy_out is not None
        if has_intent and not fw.enabled:
            warnings.append(
                f"resource #{i + 1}: firewall rules/policies defined but the guest "
                f"firewall is not enabled (firewall.enabled) → they will not take effect"
            )

    # PROJ-89: stack-owned SDN VNet checks (best-effort, never blocks). A VNet/
    # zone name colliding with an existing (foreign) SDN object is a soft heads-up
    # here; the hard 422 (network_name_taken) comes from the prepare_plan pre-check
    # which can safely distinguish own-vs-foreign via the tofu state. SDN is
    # cluster-wide, so we resolve any one referenced node to read the cluster SDN.
    stack_vnets = [n for n in spec.networks if isinstance(n, VNetNetwork)]
    if stack_vnets:
        any_node = next(iter(distinct_nodes), None)
        existing = await _sdn_existing_names(any_node) if any_node else None
        if existing is not None:
            existing_zones, existing_vnets = existing
            for vnet in stack_vnets:
                if vnet.zone in existing_zones:
                    warnings.append(
                        f"network '{vnet.name}': zone '{vnet.zone}' already exists "
                        f"in the cluster SDN (will be referenced/collide at deploy)"
                    )
                if vnet.name in existing_vnets:
                    warnings.append(
                        f"network '{vnet.name}': a VNet with this name already "
                        f"exists in the cluster SDN (deploy may fail)"
                    )

    return warnings


async def _image_storages_on_node(proxmox_node: str) -> Optional[set[str]]:
    """Best-effort set of image-capable datastore names on a node (PROJ-82).

    Returns None when it can't be verified (node not resolvable, no token,
    offline, permission) so the caller skips the warning. Never raises.
    """
    try:
        from backend.services.nodes_service import get_node_for_proxmox_name
        from backend.services.proxmox import ProxmoxAuth, ProxmoxClient

        node = await get_node_for_proxmox_name(proxmox_node)
        if node is None:
            return None
        token_id = node.viewer_token_id or node.token_id
        token_secret = node.viewer_token_secret or node.token_secret
        if not token_id or not token_secret:
            return None
        auth = ProxmoxAuth(kind="token", value=token_id, secret=token_secret)
        client = ProxmoxClient(base_url=node.url, verify_ssl=node.verify_ssl)
        raw = await client.get_node_image_storages(auth, proxmox_node)
        return {str(s.get("storage", "")) for s in raw if s.get("storage")}
    except Exception:
        return None


async def _lxc_templates_on_node(proxmox_node: str) -> Optional[set[str]]:
    """Best-effort set of installed vztmpl file-IDs on a node (PROJ-86, AC-TMPL-3).

    Returns the set of ``volid`` strings (``storage:vztmpl/...``) so the caller
    can compare against an LXC's ``template_file_id``. Returns None when it can't
    be verified (node not resolvable, no token, offline, permission) so the
    caller skips the warning. Reuses the PROJ-38 listing logic via the node's
    viewer token. Never raises.
    """
    try:
        from backend.services.nodes_service import get_node_for_proxmox_name
        from backend.services.proxmox import ProxmoxAuth, ProxmoxClient

        node = await get_node_for_proxmox_name(proxmox_node)
        if node is None:
            return None
        token_id = node.viewer_token_id or node.token_id
        token_secret = node.viewer_token_secret or node.token_secret
        if not token_id or not token_secret:
            return None
        auth = ProxmoxAuth(kind="token", value=token_id, secret=token_secret)
        client = ProxmoxClient(base_url=node.url, verify_ssl=node.verify_ssl)
        storages = await client._get_node_storages(auth, proxmox_node, "vztmpl")
        volids: set[str] = set()
        for s in storages:
            st = s.get("storage")
            if not st:
                continue
            try:
                items = await client.get_storage_contents(auth, proxmox_node, st, "vztmpl")
            except Exception:
                continue
            for it in items:
                vid = it.get("volid")
                if vid:
                    volids.add(str(vid))
        return volids
    except Exception:
        return None


async def _bridges_on_node(proxmox_node: str) -> Optional[set[str]]:
    """Best-effort set of existing bridge names on a node (PROJ-87, AC-MODEL-3).

    Returns None when it can't be verified (node not resolvable, no token,
    offline, permission) so the caller skips the warning. Reuses the PROJ-79
    interface listing via the node's viewer token. Never raises.
    """
    try:
        from backend.services.nodes_service import get_node_for_proxmox_name
        from backend.services.proxmox import ProxmoxAuth, ProxmoxClient

        node = await get_node_for_proxmox_name(proxmox_node)
        if node is None:
            return None
        token_id = node.viewer_token_id or node.token_id
        token_secret = node.viewer_token_secret or node.token_secret
        if not token_id or not token_secret:
            return None
        auth = ProxmoxAuth(kind="token", value=token_id, secret=token_secret)
        client = ProxmoxClient(base_url=node.url, verify_ssl=node.verify_ssl)
        ifaces = await client.get_node_network_interfaces(auth, proxmox_node)
        return {str(i.get("iface", "")) for i in ifaces if i.get("iface")}
    except Exception:
        return None


async def _sdn_existing_names(proxmox_node: str) -> Optional[tuple[set[str], set[str]]]:
    """Best-effort (existing zone names, existing vnet names) in the cluster SDN.

    SDN is cluster-wide — any resolvable node of the installation can read it.
    Uses the node's tofu token (it carries ``SDN.Allocate`` since `4fd4bed`, which
    permits the SDN read); the viewer token usually lacks SDN audit. Returns None
    when it can't be verified (node not resolvable, no tofu token, offline,
    permission) so the caller skips the warning. Never raises (PROJ-89).
    """
    try:
        from backend.services.nodes_service import get_node_for_proxmox_name
        from backend.services.proxmox import ProxmoxAuth, ProxmoxClient

        node = await get_node_for_proxmox_name(proxmox_node)
        if node is None or not node.tofu_token_id or not node.tofu_token_secret:
            return None
        auth = ProxmoxAuth(
            kind="token", value=node.tofu_token_id, secret=node.tofu_token_secret
        )
        client = ProxmoxClient(base_url=node.url, verify_ssl=node.verify_ssl)
        zones = await client.get_sdn_zones(auth)
        vnets = await client.get_sdn_vnets(auth)
        zone_names = {
            str(z.get("zone") or z.get("id")) for z in zones
            if z.get("zone") or z.get("id")
        }
        vnet_names = {
            str(v.get("vnet") or v.get("id")) for v in vnets
            if v.get("vnet") or v.get("id")
        }
        return zone_names, vnet_names
    except Exception:
        return None


async def _node_exists(proxmox_node: str) -> bool:
    try:
        from backend.services.nodes_service import get_node_for_proxmox_name
        node = await get_node_for_proxmox_name(proxmox_node)
        return node is not None
    except Exception:
        # Can't verify (DB error / offline) → don't warn
        return True


async def validate_request(req: StackCreateRequest) -> tuple[Optional[StackSpec], str, list[str], list[str]]:
    """Full pipeline for the /validate endpoint and pre-save validation.

    Returns (spec_or_none, canonical_yaml, errors, warnings).
    On input parse error: spec=None, canonical='', errors set.
    """
    try:
        raw, canonical = parse_input(req)
    except StackInputError as exc:
        return None, "", [str(exc)], []

    spec, errors, warnings = validate_structure(raw)
    if spec is None:
        return None, canonical, errors, warnings

    warnings += await semantic_warnings(spec)
    return spec, canonical, [], warnings
