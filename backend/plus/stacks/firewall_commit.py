# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-91: the declarative stack-firewall commit (Pfad B, post-apply / pre-destroy).

The NIC ``firewall`` flag is set by the transpiler (Pfad A, part of the VM/
container resource in the tofu state). Everything else — the guest firewall
option (``enable``/policies), the guest rule list and the stack-owned security
groups — is applied imperatively over the deployed PROJ-90 firewall API AFTER a
successful ``tofu apply`` and torn down before/after ``tofu destroy``. bpg has no
schema-verified firewall resources in the pinned 0.109 (Tech-Design A), so this
P3-commit (the proven ``_commit_sdn`` pattern) is the path.

Split into pure plan builders (unit-testable, no Proxmox) + thin async executors
that run over a per-node tofu-token client (feedback_per_node_proxmox_client).

Idempotent deterministic replace (OP6): a stack OWNS the whole guest firewall
(the mutations-block forbids manual edits, AC-MUT-1), so the commit deletes all
existing guest rules and re-sets the stack rules in YAML order — an unchanged YAML
produces an identical rule list, no re-ordering drift. Stack security groups are
delete+recreate under the stack-prefixed name (the same idempotent replace).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from backend.services.nodes_service import NodeRow

from . import transpile
from .schemas import GuestFirewall, StackSecurityGroup, StackSpec

logger = logging.getLogger(__name__)

# Stack-owned security-group name prefix (Tech-Design C). ``p3s<id>-`` is the
# cluster-unique marker — the destroy uses it to find this stack's SGs without a
# tracking table (analog stack-bridge names PROJ-87).
_SG_PREFIX = "p3s"


def stack_sg_prefix(stack_id: int) -> str:
    return f"{_SG_PREFIX}{stack_id}-"


def stack_sg_name(stack_id: int, local_name: str) -> str:
    """Map a stack-local SG name → the cluster-unique Proxmox name (AC-SG-1/2)."""
    return f"{stack_sg_prefix(stack_id)}{local_name}"


def _rule_params(rule, stack_id: int, stack_sg_names: set[str]) -> dict[str, Any]:
    """A rule's Proxmox params with a ``group`` action resolved to the SG name.

    A ``group`` rule whose action names a stack-owned SG → the prefixed name
    (AC-SG-2); any other group name is an existing/shared SG → passed through
    unchanged (AC-SG-3, 1-engine reference).
    """
    params = rule.to_proxmox_params()
    if rule.type == "group" and rule.action in stack_sg_names:
        params["action"] = stack_sg_name(stack_id, rule.action)
    return params


# ── Pure plan builders ────────────────────────────────────────────────────────

@dataclass
class _SgCommit:
    name: str                       # the prefixed Proxmox SG name
    comment: str | None
    rules: list[dict[str, Any]]     # rule param dicts in YAML order


@dataclass
class _GuestCommit:
    node: str
    vmid: int
    kind: str                       # "qemu" | "lxc" (Proxmox firewall path segment)
    options: dict[str, Any]         # enable / policy_in / policy_out
    rules: list[dict[str, Any]]     # rule param dicts in YAML order


@dataclass
class FirewallPlan:
    security_groups: list[_SgCommit] = field(default_factory=list)
    guests: list[_GuestCommit] = field(default_factory=list)


def _guest_options(fw: GuestFirewall) -> dict[str, Any]:
    opts: dict[str, Any] = {"enable": 1 if fw.enabled else 0}
    if fw.policy_in is not None:
        opts["policy_in"] = fw.policy_in
    if fw.policy_out is not None:
        opts["policy_out"] = fw.policy_out
    return opts


def build_firewall_plan(
    stack_id: int, spec: StackSpec, deployed: list[dict[str, Any]]
) -> FirewallPlan:
    """Pure: what the commit must do, from the spec + the deployed resources.

    ``deployed`` is the ``stack_deployed_resources`` view
    (``[{resource_name, vmid, kind, node}]``). A guest gets a commit only when its
    spec resource has a ``firewall`` block (= stack-managed, AC-MUT-1). The
    resolved (count-expanded) resource name links the deployed VM to its spec.
    """
    stack_sg_names = {g.name for g in spec.security_groups}

    sg_commits: list[_SgCommit] = []
    for sg in spec.security_groups:
        sg_commits.append(_SgCommit(
            name=stack_sg_name(stack_id, sg.name),
            comment=sg.comment,
            rules=[_rule_params(r, stack_id, stack_sg_names) for r in sg.rules],
        ))

    # Map each resolved (count-expanded) resource name → its spec resource so the
    # deployed VMs (which carry the resolved name) find their firewall block.
    spec_by_name: dict[str, Any] = {}
    for r in spec.resources:
        for resolved in transpile._expanded_names(r):
            spec_by_name[resolved] = r

    guest_commits: list[_GuestCommit] = []
    for d in deployed:
        r = spec_by_name.get(d.get("resource_name", ""))
        fw = getattr(r, "firewall", None) if r is not None else None
        if fw is None:
            continue
        node = d.get("node") or getattr(r, "node", "")
        vmid = d.get("vmid")
        if vmid is None or not node:
            continue
        pve_kind = "lxc" if d.get("kind") == "lxc" else "qemu"
        guest_commits.append(_GuestCommit(
            node=node,
            vmid=int(vmid),
            kind=pve_kind,
            options=_guest_options(fw),
            rules=[_rule_params(rule, stack_id, stack_sg_names) for rule in fw.rules],
        ))

    return FirewallPlan(security_groups=sg_commits, guests=guest_commits)


def has_firewall(spec: StackSpec) -> bool:
    """True when the stack declares any guest firewall block or stack SG (AC-LC-1).

    Drives the runner's ``is_firewall`` flag — a pure VM/LXC/Bridge/SDN stack
    returns False → the commit never runs (byte-for-byte legacy, AC-TRANS-2).
    """
    if spec.security_groups:
        return True
    return any(getattr(r, "firewall", None) is not None for r in spec.resources)


def collect_group_rule_refs(spec: StackSpec) -> set[str]:
    """All security-group names referenced by ``group`` rules (guests + stack SGs).

    Used by the prepare_plan existence pre-check (AC-SG-4): a name that is neither
    a stack SG nor an existing cluster SG is a 422.
    """
    refs: set[str] = set()
    for r in spec.resources:
        fw = getattr(r, "firewall", None)
        if fw is None:
            continue
        for rule in fw.rules:
            if rule.type == "group" and rule.action:
                refs.add(rule.action)
    for sg in spec.security_groups:
        for rule in sg.rules:
            if rule.type == "group" and rule.action:
                refs.add(rule.action)
    return refs


# ── Thin async executors (per-node tofu-token client) ─────────────────────────

def _tofu_client_auth(node: NodeRow):
    """Per-node Proxmox client + tofu-token auth (feedback_per_node_proxmox_client).

    The tofu token carries VM.Config.Network (guest FW) + Sys.Modify (cluster SG)
    since PROJ-87/89 → no extra privilege needed (Tech-Design F / AC-RBAC-2).
    """
    from backend.services.proxmox import ProxmoxAuth, ProxmoxClient

    auth = ProxmoxAuth(
        kind="token", value=node.tofu_token_id, secret=node.tofu_token_secret,
    )
    client = ProxmoxClient(base_url=node.url, verify_ssl=node.verify_ssl)
    return client, auth


async def apply_firewall(node: NodeRow, stack_id: int, spec: StackSpec, deployed: list[dict[str, Any]]) -> None:
    """Apply the stack firewall after a successful ``tofu apply`` (AC-LC-1).

    Order: stack SGs first (so the guest group rules that reference them resolve),
    then per guest the option + a deterministic rule replace. Raises on failure so
    the runner can surface it in the job log (Edge 6 / AC-RBAC-2).
    """
    plan = build_firewall_plan(stack_id, spec, deployed)
    if not plan.security_groups and not plan.guests:
        return
    client, auth = _tofu_client_auth(node)

    # 1) Stack-owned security groups: delete+recreate (idempotent replace), then
    #    fill in YAML order — before the guest group rules that reference them.
    for sg in plan.security_groups:
        try:
            await client.delete_firewall_group(auth, sg.name)
        except Exception:  # not-found / first deploy → fine, we recreate next.
            pass
        params: dict[str, Any] = {"group": sg.name}
        if sg.comment:
            params["comment"] = sg.comment
        await client.create_firewall_group(auth, params)
        for rule_params in sg.rules:
            await client.create_firewall_group_rule(auth, sg.name, rule_params)

    # 2) Per guest with a stack firewall block: set the option, then replace the
    #    rule list (the stack owns the whole guest firewall, AC-MUT-1).
    for g in plan.guests:
        await client.update_guest_firewall_options(auth, g.node, g.vmid, g.kind, g.options)
        # Delete all existing rules high→low so positions don't shift mid-loop.
        existing = await client.get_guest_firewall_rules(auth, g.node, g.vmid, g.kind)
        for pos in sorted(
            (int(r.get("pos")) for r in existing if r.get("pos") is not None),
            reverse=True,
        ):
            await client.delete_guest_firewall_rule(auth, g.node, g.vmid, g.kind, pos)
        # Set the stack rules in YAML order (append → top-down position order).
        for rule_params in g.rules:
            await client.create_guest_firewall_rule(auth, g.node, g.vmid, g.kind, rule_params)


async def destroy_stack_security_groups(node: NodeRow, stack_id: int) -> None:
    """Delete every cluster SG with this stack's ``p3s<id>-`` prefix (AC-LC-2).

    The guests' own rules/options vanish with the guests on destroy; only the
    cluster SGs are datacenter objects that must be cleaned up. The prefix is the
    marker (no tracking table). Raises on failure so the runner can surface it
    (Edge 6: a foreign guest referencing the SG makes Proxmox refuse the delete).
    """
    client, auth = _tofu_client_auth(node)
    prefix = stack_sg_prefix(stack_id)
    groups = await client.get_firewall_groups(auth)
    for g in groups:
        name = g.get("group") if isinstance(g, dict) else None
        if name and str(name).startswith(prefix):
            await client.delete_firewall_group(auth, str(name))
