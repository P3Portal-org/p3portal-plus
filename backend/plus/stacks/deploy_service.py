# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-76 Phase 2b: deploy orchestration + gates (RBAC/Quota/Token/Installation/Lock).

Flow (Tech-Design E):

  POST /plan   → ``prepare_plan``    : gate → transpile → tofu init/validate/plan
                                       → in-memory plan-token (TTL, bound to etag)
  POST /deploy → ``start_stack_job`` : re-gate → consume plan-token (etag 409)
                                       → lock (409) → job-row → background runner
  POST /destroy: same with operation='destroy'
  GET/POST /drift: ``run_drift``     : read-only plan → drift over stack-VMs only

All gate failures (403/412/409/4xx) happen **before** any state-mutating tofu
run. The token is injected via env by the engine and never appears in the plan
or state (Phase 2a). ``count > 1`` resources are pre-expanded by the transpiler.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import text

from backend.core.plus_protocol import plus_behavior
from backend.db.database import get_db
from backend.services.audit_service import write_audit_log
from backend.services.nodes_service import NodeRow, get_node_for_proxmox_name

from . import engine, transpile
from .deployments import (
    create_deployment,
    list_deployed_resources,
    parse_state_disks,
    set_drift_state,
)
from .permissions import can_deploy_stack
from .preview import resolve_resources
from .schemas import DestructiveDiskChange, PlanResource, PlanResponse, PlanSummary
from .validation import validate_request
from .schemas import StackCreateRequest

logger = logging.getLogger(__name__)

# In-memory plan tokens (single-container reality, Muster Stack-Lock).
# token → {stack_id, etag, operation, summary, expires_at, node_id}
_PLAN_TOKENS: dict[str, dict] = {}
_PLAN_TTL = timedelta(minutes=15)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Spec / node resolution ────────────────────────────────────────────────────

async def _spec_of(stack_row):
    """Parse the stack's stored yaml_text into a validated StackSpec."""
    spec, _canonical, errors, _warnings = await validate_request(
        StackCreateRequest(yaml_text=stack_row["yaml_text"])
    )
    if spec is None:
        raise HTTPException(status_code=422, detail={"errors": errors})
    return spec


async def resolve_target_node(spec) -> NodeRow:
    """Resolve all referenced Proxmox nodes to exactly one Portal-Node (AC-2b-13).

    A stack deploys against one Proxmox installation = one provider endpoint +
    one tofu-token. Multiple physical cluster members (same endpoint) are fine;
    nodes spread across independent installations are a validation error.
    Raises 4xx **before** any plan when unresolvable or token missing.
    """
    if not spec.resources:
        raise HTTPException(status_code=422, detail="stack_has_no_resources")

    node_rows: dict[int, NodeRow] = {}
    # PROJ-87: a stack-owned bridge has its own ``node`` — fold it into the
    # one-installation constraint so a bridge on a different installation than the
    # guests is a clean 422 before any plan (Tech-Design E).
    proxmox_node_names = [r.node for r in spec.resources]
    proxmox_node_names += [
        n.node for n in spec.networks if getattr(n, "node", None)
    ]
    for proxmox_node in proxmox_node_names:
        node = await get_node_for_proxmox_name(proxmox_node)
        if node is None:
            raise HTTPException(
                status_code=422,
                detail=f"node_not_resolvable:{proxmox_node}",
            )
        node_rows[node.id] = node

    if len(node_rows) != 1:
        raise HTTPException(
            status_code=422,
            detail="multiple_installations_not_supported",
        )

    node = next(iter(node_rows.values()))
    if not node.tofu_token_id or not node.tofu_token_secret:
        raise HTTPException(
            status_code=400,
            detail=f"node_not_stack_deploy_capable:{node.name}",
        )
    return node


def _resource_totals(spec) -> tuple[int, int, int, int]:
    """Sum the resolved resources: (vm_count, cores, ram_mb, disk_gb).

    PROJ-86: typ-aware disk — a VM contributes its ``disk`` (root) GiB, an LXC
    its ``rootfs_size`` GiB (mountpoints are not counted in the quota, MVP).
    """
    vm_count = cores = ram = disk = 0
    for r in spec.resources:
        n = r.count
        vm_count += n
        cores += r.cores * n
        ram += r.memory * n
        disk += (r.rootfs_size if getattr(r, "type", "vm") == "lxc" else r.disk) * n
    return vm_count, cores, ram, disk


async def _resolve_pool_id(pool_name: str) -> Optional[int]:
    async with get_db() as db:
        result = await db.execute(
            text("SELECT id FROM pools WHERE name = :n"), {"n": pool_name}
        )
        row = result.mappings().fetchone()
    return int(row["id"]) if row else None


# ── Gates (RBAC 403 / Quota 412) ──────────────────────────────────────────────

async def assert_deploy_allowed(
    stack_row, spec, node: NodeRow, user_role: str, user_id: Optional[int], username: str,
) -> None:
    """RBAC (403) + pool-quota (412) gate before any plan (AC-2B-RBAC)."""
    allowed = await can_deploy_stack(user_role, user_id, stack_row["owner_user_id"], node.id)
    if not allowed:
        await write_audit_log(
            "stack_deploy_blocked_rbac", username=username,
            detail=f"stack_id={stack_row['id']} node_id={node.id}",
        )
        raise HTTPException(status_code=403, detail="stack_deploy_forbidden")

    # Pool-quota only when a pool is referenced (any resource).
    pool_name = next((r.pool for r in spec.resources if r.pool), None)
    if not pool_name:
        return
    pool_id = await _resolve_pool_id(pool_name)
    if pool_id is None:
        return  # unknown pool → already a validation warning; don't hard-block
    vm_count, cores, ram, disk = _resource_totals(spec)
    quota = await plus_behavior.check_pool_quota_bulk(
        user_id or 0, pool_id, vm_count, cores, ram, disk
    )
    if not quota.allowed:
        await write_audit_log(
            "stack_deploy_blocked_quota", username=username,
            detail=f"stack_id={stack_row['id']} pool_id={pool_id} exceeded={quota.exceeded}",
        )
        raise HTTPException(
            status_code=412,
            detail={"error": "pool_quota_exceeded", "quota": quota.model_dump()},
        )


# ── Template VMID resolution (Proxmox; mockable seam) ─────────────────────────

async def resolve_template_vmids(node: NodeRow, spec) -> dict[tuple[str, str], int]:
    """Resolve each referenced template → the VMID of the copy on the VM's TARGET node.

    Keyed by ``(target_proxmox_node, template_name)``. In a cluster the same template
    NAME can exist on several members with different (cluster-unique) VMIDs — e.g.
    Packer builds one copy per node. A clone must use the copy that resides on the
    VM's target node, otherwise Proxmox reports ``unable to find configuration file
    for VM <id> on node <target>``. Keying by (node, name) stops same-name copies on
    different nodes from overwriting each other.

    Read-only lookup via the node's viewer token. A template missing on its target
    node raises HTTP 422 (Edge 2/5). Isolated so tests can mock it.
    """
    from backend.services.proxmox import ProxmoxAuth, ProxmoxClient

    auth = ProxmoxAuth(
        kind="token",
        value=node.viewer_token_id or node.token_id,
        secret=node.viewer_token_secret or node.token_secret,
    )
    client = ProxmoxClient(base_url=node.url, verify_ssl=node.verify_ssl)
    try:
        resources = await client.get_cluster_resources_v2(auth, "vm")
    except Exception as exc:  # pragma: no cover – network
        raise HTTPException(status_code=502, detail="cluster_unreachable") from exc

    # (proxmox_node, template_name) → VMID for every template copy in the cluster.
    by_node_name: dict[tuple[str, str], int] = {}
    for r in resources:
        if int(r.get("template", 0)) == 1:
            name = r.get("name")
            rnode = r.get("node")
            if name and rnode:
                by_node_name[(str(rnode), str(name))] = int(r.get("vmid"))

    # PROJ-86: only VM resources clone a VM-template VMID. LXC templates are
    # ostemplate file-IDs (no VMID lookup) and must NOT be searched here.
    wanted: dict[tuple[str, str], int] = {}
    missing: list[str] = []
    for r in spec.resources:
        if getattr(r, "type", "vm") != "vm":
            continue
        key = (r.node, r.template)
        if key in by_node_name:
            wanted[key] = by_node_name[key]
        else:
            missing.append(f"{r.template}@{r.node}")
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"template_not_found:{','.join(sorted(set(missing)))}",
        )
    return wanted


def _wanted_explicit_vmids(spec) -> dict[int, str]:
    """Collect explicitly pinned VMIDs → resource name (count → base+offset)."""
    wanted: dict[int, str] = {}
    for r in spec.resources:
        # PROJ-86: only VMs support an explicit VMID pin (LXC = auto-VMID, MVP).
        vmid = getattr(r, "vmid", None)
        if vmid is None:
            continue
        names = [r.name] if r.count <= 1 else [f"{r.name}-{i}" for i in range(1, r.count + 1)]
        for offset, nm in enumerate(names):
            wanted[vmid + offset] = nm
    return wanted


def suggest_free_vmids(spec, occupied: set[int]) -> list[dict]:
    """Propose the next free base VMID for every pinned resource whose range collides.

    ``occupied`` = VMIDs taken on the cluster (already excluding this stack's own).
    Walks the resources in order; a resource keeps its VMID range when free, else
    gets the next base ``B`` so that ``B..B+count-1`` is free and does not clash
    with ranges already assigned/kept in this same pass. Mirrors the Provisioning
    "+1 until free" behaviour, count-aware. Returns
    ``[{index, name, old_vmid, new_vmid}]`` only for the resources that moved.
    """
    reserved: set[int] = set()
    needs: list[tuple[int, object]] = []
    # Pass 1: keep every range that is free (and doesn't clash with one already kept).
    for idx, r in enumerate(spec.resources):
        rvmid = getattr(r, "vmid", None)  # explicit VMID pin (VM + LXC, optional).
        if rvmid is None:
            continue
        rng = set(range(rvmid, rvmid + r.count))
        if rng & occupied or rng & reserved:
            needs.append((idx, r))
        else:
            reserved |= rng
    # Pass 2: reassign only the colliding ones to the next free window.
    suggestions: list[dict] = []
    for idx, r in needs:
        b = r.vmid
        while (set(range(b, b + r.count)) & occupied) or (set(range(b, b + r.count)) & reserved):
            b += 1
        suggestions.append({"index": idx, "name": r.name, "old_vmid": r.vmid, "new_vmid": b})
        reserved |= set(range(b, b + r.count))
    return suggestions


async def assert_explicit_vmids_free(stack_id: int, node: NodeRow, spec) -> None:
    """Reject a deploy when an explicitly pinned VMID is already taken (Edge: VMID-Kollision).

    Only runs when the stack actually pins VMIDs (the auto-assign default skips
    the cluster call entirely). VMIDs this stack already manages are excluded so
    a re-deploy of an unchanged stack does not false-positive on its own VMs.
    On conflict raises HTTP 422 with a structured detail
    ``{error, taken, suggestions}`` so the UI can offer "pick next free VMID".
    """
    wanted = _wanted_explicit_vmids(spec)
    if not wanted:
        return

    from backend.services.proxmox import ProxmoxAuth, ProxmoxClient
    from . import deployments

    auth = ProxmoxAuth(
        kind="token",
        value=node.viewer_token_id or node.token_id,
        secret=node.viewer_token_secret or node.token_secret,
    )
    client = ProxmoxClient(base_url=node.url, verify_ssl=node.verify_ssl)
    try:
        resources = await client.get_cluster_resources_v2(auth, "vm")
    except Exception as exc:  # pragma: no cover – network
        raise HTTPException(status_code=502, detail="cluster_unreachable") from exc
    used_vmids = {int(r["vmid"]) for r in resources if r.get("vmid") is not None}

    # Exclude VMIDs this stack already owns (re-deploy must not collide with itself).
    own = {int(r["vmid"]) for r in await deployments.list_deployed_resources(stack_id)
           if r.get("vmid") is not None}
    occupied = used_vmids - own

    taken = sorted(v for v in wanted if v in occupied)
    if taken:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "vmid_taken",
                "taken": taken,
                "suggestions": suggest_free_vmids(spec, occupied),
            },
        )


# ── PROJ-87: stack-owned network gates (AC-MODEL-3 / AC-DES) ──────────────────

def _stack_bridges(spec) -> list:
    """Stack-owned Linux bridges (PROJ-87)."""
    from .schemas import BridgeNetwork
    return [n for n in spec.networks if isinstance(n, BridgeNetwork)]


def _stack_vnets(spec) -> list:
    """Stack-owned SDN VNets (PROJ-89)."""
    from .schemas import VNetNetwork
    return [n for n in spec.networks if isinstance(n, VNetNetwork)]


def _spec_has_vnet(spec) -> bool:
    """True when the spec declares at least one SDN VNet (PROJ-89, AC-APPLY-1).

    Drives the ``_SDN_APPLY_LOCK`` acquisition + the runner's cluster-wide
    ``apply_sdn`` commit. A pure VM/LXC/Bridge stack returns False → no SDN code
    runs (AC-MODEL-4).
    """
    return bool(_stack_vnets(spec))


async def _own_sdn_names(stack_id: int, node: NodeRow) -> Optional[set[str]]:
    """Names of SDN zones+VNets this stack manages, from ``tofu state list``.

    Lets ``assert_stack_networks_free`` distinguish a re-deploy of the stack's
    OWN zone/VNet (fine) from a collision with a FOREIGN existing SDN object
    (422). Returns None when the state can't be read (no ``.terraform``/first
    deploy/error) so the caller can decide (Tech-Design G). Best-effort, no raise.
    """
    try:
        rc, out, _err = await engine.run_tofu(["state", "list"], str(stack_id), node)
    except Exception as exc:  # pragma: no cover – defensive
        logger.warning("PROJ-89: state list failed for stack %s: %s", stack_id, exc)
        return None
    if rc != 0:
        return None
    names: set[str] = set()
    for line in out.splitlines():
        line = line.strip()
        for rtype in (transpile._SDN_ZONE_RESOURCE_TYPE, transpile._SDN_VNET_RESOURCE_TYPE):
            prefix = f"{rtype}."
            if line.startswith(prefix):
                names.add(line[len(prefix):])
    return names


async def assert_stack_networks_free(node: NodeRow, spec, stack_id: Optional[int] = None) -> None:
    """Reject an apply when a stack network name already exists unmanaged (AC-MODEL-3).

    A deterministic pre-check (Muster ``assert_explicit_vmids_free`` / BUG-79-2):
    creating a bridge/VNet/zone whose name is already taken would fail the apply,
    so surface a clean 422 ``network_name_taken`` before tofu runs.

    Bridges (PROJ-87): exact name collision with an existing node interface.
    SDN VNets/zones (PROJ-89): name collision with an existing FOREIGN SDN object.
    A stack re-deploy must NOT false-positive on its own zone/VNet, so the names
    this stack already manages (from ``tofu state list``) are excluded; if the
    state can't be read it's a first deploy (own nothing yet) → check against all,
    or a later deploy with unreadable state → skip the SDN check (tofu reconciles).
    """
    bridges = _stack_bridges(spec)
    vnets = _stack_vnets(spec)
    if not bridges and not vnets:
        return

    from backend.services.proxmox import ProxmoxAuth, ProxmoxClient

    viewer_auth = ProxmoxAuth(
        kind="token",
        value=node.viewer_token_id or node.token_id,
        secret=node.viewer_token_secret or node.token_secret,
    )
    client = ProxmoxClient(base_url=node.url, verify_ssl=node.verify_ssl)
    taken: list[str] = []

    # ── Bridges: exact name collision with an existing node interface ──────────
    if bridges:
        existing_by_node: dict[str, set[str]] = {}
        for net in bridges:
            if net.node not in existing_by_node:
                try:
                    ifaces = await client.get_node_network_interfaces(viewer_auth, net.node)
                except Exception as exc:  # pragma: no cover – network
                    raise HTTPException(status_code=502, detail="cluster_unreachable") from exc
                existing_by_node[net.node] = {
                    str(i.get("iface", "")) for i in ifaces if i.get("iface")
                }
            if net.name in existing_by_node[net.node]:
                taken.append(net.name)

    # ── SDN VNets/zones: collision with a FOREIGN existing SDN object ──────────
    if vnets:
        own = await _own_sdn_names(stack_id, node) if stack_id is not None else None
        run_sdn_check = True
        if own is None:
            # State unreadable → only run on the first deploy (nothing owned yet);
            # a later deploy with unreadable state → skip (tofu reconciles its own).
            from . import deployments as _deployments
            prior = (
                await _deployments.list_deployments(stack_id)
                if stack_id is not None else []
            )
            if prior:
                run_sdn_check = False
            else:
                own = set()
        if run_sdn_check:
            # SDN read needs SDN.Allocate → the tofu token (the viewer usually
            # can't audit SDN). SDN is cluster-wide → one read covers all VNets.
            tofu_auth = ProxmoxAuth(
                kind="token", value=node.tofu_token_id, secret=node.tofu_token_secret,
            )
            try:
                zones_raw = await client.get_sdn_zones(tofu_auth)
                vnets_raw = await client.get_sdn_vnets(tofu_auth)
            except Exception as exc:  # pragma: no cover – network
                raise HTTPException(status_code=502, detail="cluster_unreachable") from exc
            existing_zones = {
                str(z.get("zone") or z.get("id")) for z in zones_raw
                if z.get("zone") or z.get("id")
            }
            existing_vnets = {
                str(v.get("vnet") or v.get("id")) for v in vnets_raw
                if v.get("vnet") or v.get("id")
            }
            for net in vnets:
                if net.zone in existing_zones and net.zone not in own:
                    taken.append(net.zone)
                if net.name in existing_vnets and net.name not in own:
                    taken.append(net.name)

    if taken:
        raise HTTPException(
            status_code=422,
            detail={"error": "network_name_taken", "taken": sorted(set(taken))},
        )


def _networks_being_destroyed(spec, operation: str, summary: PlanSummary) -> list:
    """Which stack-owned networks (bridge + VNet) this run would tear down (AC-DES / EC-3).

    destroy → every stack bridge + VNet. apply → only networks whose tofu resource
    address appears in the plan with a delete/replace action (= an apply that
    removes/recreates a network).
    """
    from .schemas import BridgeNetwork

    nets = _stack_bridges(spec) + _stack_vnets(spec)
    if not nets:
        return []
    if operation == "destroy":
        return nets
    destroyed_addrs = {
        r.name for r in summary.resources if r.action in ("delete", "replace")
    }
    out = []
    for net in nets:
        rtype = (
            transpile._BRIDGE_RESOURCE_TYPE if isinstance(net, BridgeNetwork)
            else transpile._SDN_VNET_RESOURCE_TYPE
        )
        addr = f"{rtype}.{net.name}"
        if addr in destroyed_addrs or net.name in destroyed_addrs:
            out.append(net)
    return out


async def assert_network_destroy_allowed(
    stack_id: int, spec, node: NodeRow, operation: str, summary: PlanSummary,
    username: str,
) -> None:
    """Block a run that tears down a network with FOREIGN guests attached (AC-DES-2).

    For every stack-owned bridge/VNet this run would destroy, fan out for foreign
    users (segment-match, stack-owned guests excluded). Any foreign user → HTTP
    409 ``network_in_use`` with the offending guests, no plan token issued.
    Stack-own guests at the network are fine (same destroy). A bridge is
    node-local (fan-out scoped to its node); a VNet is cluster-wide
    (``bridge_node=None`` = no node filter, PROJ-89 AC-DES-1). Covers EC-3 +
    "apply removes a network" uniformly.
    """
    from .schemas import BridgeNetwork

    destroying = _networks_being_destroyed(spec, operation, summary)
    if not destroying:
        return

    from . import network_usage

    blocked: dict[str, list[dict]] = {}
    for net in destroying:
        # Bridge: node-local fan-out. VNet: cluster-wide (bridge_node=None).
        bridge_node = net.node if isinstance(net, BridgeNetwork) else None
        users = await network_usage.find_foreign_network_users(
            node, net.name, stack_id, bridge_node=bridge_node,
        )
        if users:
            blocked[net.name] = users

    if blocked:
        await write_audit_log(
            "stack_network_destroy_blocked", username=username,
            detail=f"stack_id={stack_id} networks={','.join(sorted(blocked))}",
        )
        raise HTTPException(
            status_code=409,
            detail={"error": "network_in_use", "networks": blocked},
        )


async def assert_stack_firewall_groups_exist(node: NodeRow, spec) -> None:
    """Reject a deploy whose ``group`` rule references an unknown SG (AC-SG-4).

    A ``group`` rule may reference a stack-owned SG (a local ``security_groups``
    name — resolved+created at commit) OR an existing cluster SG (passed through,
    AC-SG-3). A name that is neither → HTTP 422 before any plan (Muster PROJ-90
    SG-existence pre-check). Best-effort on the Proxmox read: if the cluster-SG
    list can't be read we don't block (the commit/Proxmox would still reject it).
    """
    from . import firewall_commit

    refs = firewall_commit.collect_group_rule_refs(spec)
    if not refs:
        return
    stack_sg_names = {g.name for g in spec.security_groups}
    foreign_refs = refs - stack_sg_names
    if not foreign_refs:
        return  # all references are stack-owned SGs (created at commit)

    from backend.services.proxmox import ProxmoxAuth, ProxmoxClient

    # The tofu token can read cluster firewall objects (Sys.Modify, since PROJ-87).
    auth = ProxmoxAuth(
        kind="token", value=node.tofu_token_id, secret=node.tofu_token_secret,
    )
    client = ProxmoxClient(base_url=node.url, verify_ssl=node.verify_ssl)
    try:
        groups = await client.get_firewall_groups(auth)
    except Exception as exc:  # pragma: no cover – network/permission, best-effort
        logger.warning("PROJ-91: SG existence pre-check read failed: %r", exc)
        return
    existing = {str(g.get("group")) for g in groups if isinstance(g, dict) and g.get("group")}
    missing = sorted(foreign_refs - existing)
    if missing:
        raise HTTPException(
            status_code=422,
            detail={"error": "security_group_not_found", "groups": missing},
        )


async def foreign_pending_sdn(node: NodeRow, spec) -> list:
    """FOREIGN staged SDN objects the cluster-wide apply would also commit (AC-PENDING).

    The cluster-wide ``PUT /cluster/sdn`` (triggered by this stack's SDN deploy)
    commits ALL pending SDN objects, including manual ones staged by an admin. We
    read the pending zones+VNets (the cluster-scoped objects) and report the ones
    NOT owned by this stack so the user can decide (no hard block, AC-PENDING-1).
    "Own" = the stack's zone/VNet names from its spec. Best-effort: any read error
    → empty (no hint). Returns ``[ForeignPendingSdn]``.
    """
    from .schemas import ForeignPendingSdn

    vnets = _stack_vnets(spec)
    if not vnets:
        return []
    own_names = {n.zone for n in vnets} | {n.name for n in vnets}

    from backend.services.proxmox import ProxmoxAuth, ProxmoxClient

    auth = ProxmoxAuth(
        kind="token", value=node.tofu_token_id, secret=node.tofu_token_secret,
    )
    client = ProxmoxClient(base_url=node.url, verify_ssl=node.verify_ssl)
    out: list = []
    try:
        zones_raw = await client.get_sdn_zones(auth)
        vnets_raw = await client.get_sdn_vnets(auth)
    except Exception as exc:  # pragma: no cover – network/permission
        logger.warning("PROJ-89: pending SDN read failed: %r", exc)
        return []

    _PENDING = {"new", "changed", "deleted"}
    for z in zones_raw:
        state = str(z.get("state") or "")
        name = str(z.get("zone") or z.get("id") or "")
        if state in _PENDING and name and name not in own_names:
            out.append(ForeignPendingSdn(kind="zone", name=name, state=state))
    for v in vnets_raw:
        state = str(v.get("state") or "")
        name = str(v.get("vnet") or v.get("id") or "")
        if state in _PENDING and name and name not in own_names:
            out.append(ForeignPendingSdn(kind="vnet", name=name, state=state))
    return out


# ── Plan parsing ──────────────────────────────────────────────────────────────

def parse_plan_json(stdout: str) -> PlanSummary:
    """Parse ``tofu plan -json`` line-stream into a PlanSummary.

    Best-effort: reads ``change_summary`` for counts and ``planned_change`` /
    ``resource_drift`` for the per-resource list. Robust against unknown lines.
    """
    create = change = destroy = replace = 0
    resources: list[PlanResource] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        mtype = obj.get("type")
        if mtype == "change_summary":
            ch = obj.get("changes", {}) or {}
            create = int(ch.get("add", 0))
            change = int(ch.get("change", 0))
            destroy = int(ch.get("remove", 0))
        elif mtype == "planned_change":
            ch = obj.get("change", {}) or {}
            action = ch.get("action", "")
            res = ch.get("resource", {}) or {}
            name = res.get("addr") or res.get("resource_name") or ""
            if action in ("create", "update", "delete", "replace"):
                resources.append(PlanResource(name=name, action=action))
                if action == "replace":
                    replace += 1
    return PlanSummary(
        create=create, change=change, destroy=destroy, replace=replace, resources=resources
    )


def extract_tofu_json_errors(stdout: str) -> str:
    """Pull human-readable error diagnostics out of a ``tofu … -json`` stream.

    With ``-json`` tofu emits its diagnostics as JSON lines on **stdout**, not
    stderr — so a failed ``plan`` leaves stderr empty. This collects every
    ``@level == "error"`` line's message + diagnostic summary/detail so the API
    can surface the real cause instead of an empty ``stderr``.
    """
    msgs: list[str] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("@level") != "error":
            continue
        diag = obj.get("diagnostic") or {}
        summary = diag.get("summary") or obj.get("@message") or ""
        detail = diag.get("detail") or ""
        piece = summary if not detail else f"{summary}: {detail}"
        if piece and piece not in msgs:
            msgs.append(piece)
    return "\n".join(msgs)


# ── PROJ-82: destructive disk-change diff (AC-REMOVE) ─────────────────────────

# Root disk interface — never user-managed as an extra, so it can only "shrink",
# never be "removed". Compared like the others to catch a root-disk shrink.
_ROOT_DISK_INTERFACE = "scsi0"


def _spec_disks_by_resource(spec) -> dict[str, dict[str, int]]:
    """Map each resolved resource name → {interface: size_gib} for the new spec.

    VM: root disk (scsi0 = ``disk``) plus every extra disk, keyed by interface.
    PROJ-86 LXC: rootfs (key ``rootfs`` = ``rootfs_size``) plus mountpoints keyed
    positionally (``mp0``, ``mp1`` …, sorted by the declared mp index) — bpg maps
    mount_point blocks positionally, and ``parse_state_disks`` keys them the same
    way, so the diff aligns. ``count`` is expanded so per-instance names match the
    deployed-state names.
    """
    out: dict[str, dict[str, int]] = {}
    for r in spec.resources:
        if getattr(r, "type", "vm") == "lxc":
            disk_map: dict[str, int] = {"rootfs": r.rootfs_size}
            for i, m in enumerate(sorted(r.mounts, key=transpile._mp_sort_key)):
                disk_map[f"mp{i}"] = m.size
        else:
            disk_map = {_ROOT_DISK_INTERFACE: r.disk}
            for ed in r.extra_disks:
                disk_map[ed.interface] = ed.size
        for name in transpile._expanded_names(r):
            out[name] = dict(disk_map)
    return out


def diff_disks(
    state_disks: dict[str, list[dict]],
    spec_disks: dict[str, dict[str, int]],
) -> list[DestructiveDiskChange]:
    """Pure diff: deployed disks (state) vs. new disks (spec) → destructive changes.

    A change is destructive when an existing disk would be **removed** (interface
    in the state but not in the new spec) or **shrunk** (same interface, smaller
    new size — Proxmox can't shrink → replace = data loss). Pure additions and
    grows are NOT returned (non-destructive, AC-REMOVE-3). A VM that vanishes
    entirely from the spec is a VM-level destroy surfaced by the plan, not here.
    """
    changes: list[DestructiveDiskChange] = []
    for res_name, deployed_list in state_disks.items():
        new_map = spec_disks.get(res_name)
        if new_map is None:
            # Whole VM removed from the spec → handled at the resource level.
            continue
        for d in deployed_list:
            iface = d.get("interface")
            old_size = d.get("size")
            if not iface or old_size is None:
                continue
            if iface not in new_map:
                changes.append(DestructiveDiskChange(
                    vm=res_name, interface=iface, reason="removed", old_size=old_size,
                ))
            else:
                new_size = new_map[iface]
                if new_size < old_size:
                    changes.append(DestructiveDiskChange(
                        vm=res_name, interface=iface, reason="shrunk",
                        old_size=old_size, new_size=new_size,
                    ))
    return changes


async def _compute_destructive_disk_changes(stack_id: int, spec, node) -> list[DestructiveDiskChange]:
    """Pull the deployed state + diff its disks against the new spec (AC-REMOVE).

    Only meaningful when the stack already has deployed resources (otherwise
    everything is a create = non-destructive). Best-effort: a failed state pull
    yields no destructive changes (the plan + per-disk add/grow still proceed).
    Must run while holding the per-stack lock (it shells out to tofu).
    """
    deployed = await list_deployed_resources(stack_id)
    if not deployed:
        return []
    try:
        rc, out, _err = await engine.run_tofu(["state", "pull"], str(stack_id), node)
    except Exception as exc:  # pragma: no cover – defensive
        logger.warning("PROJ-82: state pull failed for stack %s: %s", stack_id, exc)
        return []
    if rc != 0:
        return []
    state_disks = parse_state_disks(out)
    if not state_disks:
        return []
    return diff_disks(state_disks, _spec_disks_by_resource(spec))


# ── Plan token registry ───────────────────────────────────────────────────────

def _make_plan_token(stack_id: int, etag: str, operation: str, summary: PlanSummary, node_id: int) -> str:
    token = uuid.uuid4().hex
    _PLAN_TOKENS[token] = {
        "stack_id": stack_id,
        "etag": etag,
        "operation": operation,
        "summary": summary,
        "node_id": node_id,
        "expires_at": datetime.now(timezone.utc) + _PLAN_TTL,
    }
    return token


def consume_plan_token(token: str, stack_id: int, current_etag: str, operation: str) -> dict:
    """Validate + pop a plan token. Raises 409 on etag mismatch, 400 otherwise."""
    entry = _PLAN_TOKENS.get(token)
    if entry is None:
        raise HTTPException(status_code=400, detail="invalid_plan_token")
    if entry["expires_at"] < datetime.now(timezone.utc):
        _PLAN_TOKENS.pop(token, None)
        raise HTTPException(status_code=409, detail="plan_token_expired")
    if entry["stack_id"] != stack_id or entry["operation"] != operation:
        raise HTTPException(status_code=400, detail="invalid_plan_token")
    if entry["etag"] != current_etag:
        _PLAN_TOKENS.pop(token, None)
        raise HTTPException(status_code=409, detail="stack_definition_changed")
    # Verify the planfile still exists.
    planfile = engine.stack_working_dir(str(stack_id)) / "plan.tfplan"
    if not planfile.exists():
        _PLAN_TOKENS.pop(token, None)
        raise HTTPException(status_code=409, detail="planfile_missing")
    return _PLAN_TOKENS.pop(token)


# ── Plan ──────────────────────────────────────────────────────────────────────

async def prepare_plan(
    stack_row, user_role: str, user_id: Optional[int], username: str, operation: str,
) -> PlanResponse:
    """Gate → transpile → tofu init/validate/plan → plan-token (AC-2B-PLAN-1)."""
    stack_id = stack_row["id"]
    spec = await _spec_of(stack_row)
    node = await resolve_target_node(spec)
    await assert_deploy_allowed(stack_row, spec, node, user_role, user_id, username)

    # Reject pinned-but-taken VMIDs before tofu runs (destroy needs no free VMID).
    if operation != "destroy":
        await assert_explicit_vmids_free(stack_id, node, spec)
        # PROJ-87/89: reject a stack bridge/VNet/zone whose name already exists
        # unmanaged (own SDN objects excluded via tofu state, AC-MODEL-3).
        await assert_stack_networks_free(node, spec, stack_id)
        # PROJ-91: reject a group-rule reference to an SG that is neither stack-
        # owned nor an existing cluster SG (AC-SG-4).
        await assert_stack_firewall_groups_exist(node, spec)

    # PROJ-85: resolve the (encrypted) cloud-init store → decrypted per-VM blocks.
    # Re-runs the lockout/static+count>1 gates (422 before tofu) for apply; for
    # destroy the gates are skipped (IP irrelevant; valid-at-save config must not
    # block teardown) but the blocks are still injected so main.tf.json matches
    # the deployed state.
    from . import cloud_init
    cloudinit = await cloud_init.resolve_for_transpile(
        stack_id, spec, gate=(operation != "destroy"),
    )

    template_vmids = await resolve_template_vmids(node, spec)
    tfjson = transpile.stack_to_tfjson(spec, template_vmids, cloudinit=cloudinit)

    workdir = engine.stack_working_dir(str(stack_id))
    main_file = workdir / "main.tf.json"
    main_file.write_text(json.dumps(tfjson, indent=2), encoding="utf-8")
    # The cloud-init password lives here in the clear (Tech-Design E): same trust
    # boundary as tofu_state.key in the same data dir. Tighten to owner-only.
    try:
        main_file.chmod(0o600)
    except OSError:  # pragma: no cover – non-POSIX / permission
        pass

    lock = engine.get_stack_lock(str(stack_id))
    if lock.locked():
        raise HTTPException(status_code=409, detail="stack_busy")
    async with lock:
        rc_i, out_i, err_i = await engine.tofu_init_if_needed(str(stack_id), node)
        if rc_i != 0:
            raise HTTPException(
                status_code=422,
                detail={"error": "tofu_init_failed", "stderr": (err_i or out_i)[:2000]},
            )
        rc_v, _out_v, err_v = await engine.run_tofu(
            ["validate", "-no-color"], str(stack_id), node
        )
        if rc_v != 0:
            raise HTTPException(status_code=422, detail={"error": "tofu_validate_failed", "stderr": err_v[:2000]})

        plan_args = ["plan", "-out=plan.tfplan", "-json", "-input=false", "-no-color"]
        if operation == "destroy":
            plan_args.insert(1, "-destroy")
        rc_p, out_p, err_p = await engine.run_tofu(plan_args, str(stack_id), node)
        # tofu plan exit code 0 = no changes, 2 = changes (with -detailed-exitcode);
        # without it, 0 = success. Non-zero(!=0) without detailed-exitcode = error.
        if rc_p not in (0,):
            # With -json the diagnostics land on stdout, not stderr → extract them
            # so the API surfaces the real cause instead of an empty stderr.
            err_detail = err_p.strip() or extract_tofu_json_errors(out_p) or "(keine Fehlerausgabe von tofu)"
            raise HTTPException(status_code=422, detail={"error": "tofu_plan_failed", "stderr": err_detail[:2000]})

        # PROJ-82: state-based disk diff (AC-REMOVE). Done inside the lock (shells
        # out to tofu state pull). Destroy removes everything anyway → skip.
        destructive: list[DestructiveDiskChange] = []
        if operation != "destroy":
            destructive = await _compute_destructive_disk_changes(stack_id, spec, node)

    summary = parse_plan_json(out_p)
    # PROJ-87/89: block tearing down a stack bridge/VNet that still has foreign
    # guests attached (AC-DES-2 / EC-3). Runs after the plan (which tells us, for
    # an apply, which networks would be removed) and before the plan token → a
    # blocked destroy/apply issues no token (HTTP 409 network_in_use).
    if spec.networks:
        await assert_network_destroy_allowed(
            stack_id, spec, node, operation, summary, username,
        )
    # PROJ-89: surface foreign staged SDN objects the cluster-wide apply would
    # also commit (AC-PENDING-1, no hard block). Best-effort, only for SDN deploys.
    pending_sdn: list = []
    if operation != "destroy" and _spec_has_vnet(spec):
        pending_sdn = await foreign_pending_sdn(node, spec)
    token = _make_plan_token(stack_id, stack_row["current_etag"], operation, summary, node.id)
    await write_audit_log(
        "stack_plan_created", username=username,
        detail=(
            f"stack_id={stack_id} op={operation} "
            f"create={summary.create} change={summary.change} destroy={summary.destroy} "
            f"disk_loss={len(destructive)}"
        ),
    )
    # PROJ-86: audit a privileged LXC at deploy time (AC-SEC-3). No RBAC gate
    # (Tech-Design J) — the stack owner controls the node's compute layer anyway;
    # the audit + editor warning are the guardrails. No secrets in the event.
    if operation != "destroy":
        priv_lxc = [
            r.name for r in spec.resources
            if getattr(r, "type", "vm") == "lxc" and not r.unprivileged
        ]
        if priv_lxc:
            await write_audit_log(
                "stack_lxc_privileged_deployed", username=username,
                detail=f"stack_id={stack_id} resources={','.join(priv_lxc)}",
            )
    return PlanResponse(
        plan_token=token, operation=operation, summary=summary,
        destructive_disk_changes=destructive,
        foreign_pending_sdn=pending_sdn,
    )


# ── Start deploy/destroy job ──────────────────────────────────────────────────

async def start_stack_job(
    stack_row, operation: str, summary: PlanSummary, node: NodeRow,
    triggered_by_user_id: Optional[int], username: str,
) -> dict:
    """Acquire the lock(s) (409 if busy), create job + deployment rows, launch runner.

    Locks are acquired here and released by the runner in its finally block
    (asyncio.Lock is not owner-bound). Returns {job_id, deployment_id}.

    PROJ-89: an SDN-touching deploy/destroy (spec has a VNet) additionally
    acquires the global ``_SDN_APPLY_LOCK`` — **before** the per-stack lock
    (deadlock-free: the broader lock first). This serializes the cluster-wide
    ``PUT /cluster/sdn`` so no two SDN deploys cross-commit each other's pending
    objects (AC-APPLY-1 / EC-2). A second concurrent SDN deploy → 409
    ``sdn_apply_busy`` (fail-fast, the user retries — like the per-stack 409).
    """
    from .runner import run_stack_job

    stack_id = stack_row["id"]

    # PROJ-89: determine whether this run touches SDN (only then take the SDN lock).
    spec = await _spec_of(stack_row)
    is_sdn = _spec_has_vnet(spec)
    # PROJ-91: whether this run must run the post-apply / pre-destroy firewall
    # commit (any guest firewall block or stack SG). No extra lock — the firewall
    # is per-guest/live and the SG names are stack-prefixed (Tech-Design E).
    from . import firewall_commit
    is_firewall = firewall_commit.has_firewall(spec)
    sdn_lock = None
    if is_sdn:
        sdn_lock = engine.get_sdn_apply_lock()
        if sdn_lock.locked():
            raise HTTPException(status_code=409, detail="sdn_apply_busy")
        await sdn_lock.acquire()

    try:
        lock = engine.get_stack_lock(str(stack_id))
        if lock.locked():
            raise HTTPException(status_code=409, detail="stack_busy")
        await lock.acquire()
        try:
            job_id = str(uuid.uuid4())
            now = _now()
            async with get_db() as db:
                await db.execute(
                    text(
                        "INSERT INTO jobs (id, type, playbook, status, created_at, username, params) "
                        "VALUES (:id, :jtype, :pb, 'pending', :now, :user, :params)"
                    ),
                    {
                        "id": job_id,
                        "jtype": f"stack_{operation}",
                        "pb": f"stack:{stack_row['name']}",
                        "now": now,
                        "user": username,
                        "params": json.dumps({"stack_id": stack_id, "operation": operation}),
                    },
                )
                await db.commit()

            deployment_id = await create_deployment(
                stack_id=stack_id,
                operation=operation,
                job_id=job_id,
                plan_summary_json=json.dumps(summary.model_dump()),
                triggered_by_user_id=triggered_by_user_id,
            )

            import asyncio
            asyncio.create_task(
                run_stack_job(
                    job_id=job_id,
                    stack_id=stack_id,
                    deployment_id=deployment_id,
                    operation=operation,
                    node=node,
                    triggered_by=username,
                    lock=lock,
                    sdn_lock=sdn_lock,
                    is_sdn=is_sdn,
                    is_firewall=is_firewall,
                )
            )
        except Exception:
            lock.release()
            raise
    except Exception:
        # Release the SDN lock if we acquired it but failed before handing both
        # locks to the runner (the runner owns the release once the task starts).
        if sdn_lock is not None and sdn_lock.locked():
            sdn_lock.release()
        raise

    return {"job_id": job_id, "deployment_id": deployment_id}


# ── Drift (read-only) ─────────────────────────────────────────────────────────

async def run_drift(stack_row, username: str):
    """On-demand drift: read-only ``tofu plan`` over the stack's own VMs only.

    Never touches foreign VMs (state isolation, AC-2B-DRIFT-5). Writes
    ``last_drift_state``. Returns a DriftReport.
    """
    from .deployments import list_deployed_resources
    from .schemas import DriftItem, DriftReport

    stack_id = stack_row["id"]
    spec = await _spec_of(stack_row)
    node = await resolve_target_node(spec)

    lock = engine.get_stack_lock(str(stack_id))
    if lock.locked():
        raise HTTPException(status_code=409, detail="stack_busy")

    deployed = await list_deployed_resources(stack_id)
    if not deployed:
        # Nothing deployed → nothing to drift.
        await set_drift_state(stack_id, "in_sync")
        return DriftReport(drift_state="in_sync")

    async with lock:
        # tofu needs an up-to-date provider cache, so init if the throwaway
        # .terraform/ is missing (e.g. fresh container) before planning.
        await engine.tofu_init_if_needed(str(stack_id), node)
        # A normal plan (NOT -refresh-only) answers "does reality differ from the
        # definition" and honours lifecycle.ignore_changes=[clone] → no phantom
        # drift from the create-time clone block. refresh-only would show clone
        # drift regardless (ignore_changes only affects the planned changes).
        rc, out, err = await engine.run_tofu(
            ["plan", "-json", "-input=false", "-no-color"],
            str(stack_id), node,
        )
    if rc != 0:
        # A failed plan must NOT be reported as "in_sync" (would hide drift).
        err_detail = err.strip() or extract_tofu_json_errors(out) or "(keine Fehlerausgabe von tofu)"
        raise HTTPException(status_code=422, detail={"error": "tofu_drift_failed", "stderr": err_detail[:2000]})
    summary = parse_plan_json(out)

    # Drift = what tofu would change to re-reach the definition:
    # update/replace = changed in place; create = the tracked VM vanished (missing).
    changed_names = {r.name for r in summary.resources if r.action in ("update", "replace")}
    missing_names = {r.name for r in summary.resources if r.action in ("create", "delete")}
    items: list[DriftItem] = []
    n_sync = n_changed = n_missing = 0
    for d in deployed:
        name = d["resource_name"]
        # tofu resource addr looks like proxmox_virtual_environment_vm.<name>
        addr_match = any(name == cn.split(".")[-1] or name == cn for cn in changed_names)
        miss_match = any(name == cn.split(".")[-1] or name == cn for cn in missing_names)
        if miss_match:
            state = "missing"
            n_missing += 1
        elif addr_match:
            state = "changed"
            n_changed += 1
        else:
            state = "in_sync"
            n_sync += 1
        items.append(DriftItem(resource_name=name, vmid=d.get("vmid"), state=state))

    drift_state = "out_of_sync" if (n_changed or n_missing) else "in_sync"
    await set_drift_state(stack_id, drift_state)
    await write_audit_log(
        "stack_drift_checked", username=username,
        detail=f"stack_id={stack_id} state={drift_state} changed={n_changed} missing={n_missing}",
    )
    return DriftReport(
        drift_state=drift_state, in_sync=n_sync, changed=n_changed,
        missing=n_missing, items=items,
    )
