# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-91: declarative stack firewall — schema, transpile NIC-flag, validation
warning, commit plan + executors, SG-existence pre-check, mutations-block.

Pure/mocked — no real tofu/Proxmox. Covers AC-MODEL/ENABLE/RULE/SG/REF/LC/MUT/
TRANS. The cluster-wide commit is exercised over an AsyncMock ProxmoxClient.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from backend.plus.stacks import deploy_service as ds
from backend.plus.stacks import firewall_commit as fc
from backend.plus.stacks.schemas import (
    GuestFirewall,
    StackFirewallRule,
    StackSecurityGroup,
    StackSpec,
)
from backend.plus.stacks.transpile import stack_to_tfjson
from backend.plus.stacks.validation import semantic_warnings

pytestmark = pytest.mark.plus_only

_VM_TYPE = "proxmox_virtual_environment_vm"
_CT_TYPE = "proxmox_virtual_environment_container"


def _node(node_id=1):
    from backend.services.nodes_service import NodeRow
    return NodeRow(
        id=node_id, name="pve", url="https://pve:8006", proxmox_node="pve",
        verify_ssl=False, token_id="t", token_secret="s",
        viewer_token_id="v", viewer_token_secret="s",
        operator_token_id="", operator_token_secret="",
        admin_token_id="", admin_token_secret="",
        packer_token_id="", packer_token_secret="",
        tofu_token_id="root@pam!tofu", tofu_token_secret="secret",
        is_default=True, created_at="2026-01-01", created_by="admin",
    )


def _vm_spec(**fw):
    res = {"name": "web", "node": "pve", "template": "deb12"}
    if fw:
        res["firewall"] = fw
    return StackSpec(name="fw-stack", resources=[res])


# ── Schema (MODEL / RULE / SG) ────────────────────────────────────────────────

def test_rule_macro_xor_proto():
    """AC-RULE-2 / EC-4: macro + explicit proto/port mutually exclusive."""
    with pytest.raises(ValidationError):
        StackFirewallRule(type="in", action="ACCEPT", macro="HTTP", dport="80")


def test_rule_group_needs_action():
    """AC-RULE-1: a group rule needs a security-group name as action."""
    with pytest.raises(ValidationError):
        StackFirewallRule(type="group", action="")


def test_rule_inout_action_must_be_verb():
    """AC-RULE-1: in/out need ACCEPT/DROP/REJECT."""
    with pytest.raises(ValidationError):
        StackFirewallRule(type="out", action="notavalidaction")


def test_rule_addr_validation():
    """AC-RULE-3: source/dest accept IP/CIDR/range/alias/+ipset; junk → 422."""
    ok = StackFirewallRule(type="in", action="ACCEPT", source="10.0.0.0/24,+mgmt")
    assert ok.source == "10.0.0.0/24,+mgmt"
    with pytest.raises(ValidationError):
        StackFirewallRule(type="in", action="ACCEPT", source="not a valid token!!")


def test_rule_params_have_no_pos():
    """AC-MODEL-5: declarative rule maps to params without ``pos``."""
    p = StackFirewallRule(type="out", action="ACCEPT", proto="tcp", dport="443").to_proxmox_params()
    assert "pos" not in p
    assert p == {"type": "out", "action": "ACCEPT", "enable": 1, "proto": "tcp", "dport": "443"}


def test_sg_name_regex_and_length():
    """AC-MODEL-4 / Tech-Design C: SG name must match the regex + be ≤10 chars."""
    StackSecurityGroup(name="web-egress")  # 10 chars, ok
    with pytest.raises(ValidationError):
        StackSecurityGroup(name="waaaaytoolong")     # > 10
    with pytest.raises(ValidationError):
        StackSecurityGroup(name="1web")              # must start with a letter


def test_duplicate_sg_names_422():
    """AC-MODEL-3: stack security-group names must be unique."""
    with pytest.raises(ValidationError):
        StackSpec(
            name="dup-stack",
            resources=[{"name": "web", "node": "pve", "template": "deb12"}],
            security_groups=[{"name": "a"}, {"name": "a"}],
        )


def test_guest_firewall_defaults():
    """AC-MODEL-2: GuestFirewall defaults (disabled, no policies, no rules)."""
    fw = GuestFirewall()
    assert fw.enabled is False
    assert fw.policy_in is None and fw.policy_out is None and fw.rules == []


# ── Transpile NIC-flag (ENABLE) + byte-for-byte (TRANS-2) ─────────────────────

def test_transpile_byte_identical_without_firewall():
    """AC-TRANS-2 / AC-MODEL-6: no firewall block → byte-for-byte legacy output."""
    import json
    a = stack_to_tfjson(_vm_spec(), {"deb12": 9000})
    b = stack_to_tfjson(
        StackSpec(name="fw-stack", resources=[{"name": "web", "node": "pve", "template": "deb12"}]),
        {"deb12": 9000},
    )
    assert json.dumps(a) == json.dumps(b)
    # the NIC firewall flag stays None (unset, AC-ENABLE-3)
    assert a["resource"][_VM_TYPE]["web"]["network_device"][0]["firewall"] is None


def test_transpile_vm_nic_flag_on_when_enabled():
    """AC-ENABLE-1: firewall.enabled=True → VM NIC firewall flag True."""
    spec = _vm_spec(enabled=True, policy_out="DROP",
                    rules=[{"type": "out", "action": "ACCEPT", "proto": "tcp", "dport": "443"}])
    out = stack_to_tfjson(spec, {"deb12": 9000})
    assert out["resource"][_VM_TYPE]["web"]["network_device"][0]["firewall"] is True


def test_transpile_vm_nic_flag_off_when_block_disabled():
    """AC-ENABLE-3: firewall.enabled=False → NIC flag stays None."""
    spec = _vm_spec(enabled=False, rules=[{"type": "in", "action": "ACCEPT", "proto": "tcp", "dport": "22"}])
    out = stack_to_tfjson(spec, {"deb12": 9000})
    assert out["resource"][_VM_TYPE]["web"]["network_device"][0]["firewall"] is None


def test_transpile_lxc_nic_flag():
    """AC-ENABLE-1/3: LXC network_interface gets firewall key only when enabled."""
    base = {"type": "lxc", "name": "ct", "node": "pve",
            "template": "local:vztmpl/debian-12.tar.zst",
            "rootfs_datastore": "local", "hostname": "ct"}
    off = stack_to_tfjson(StackSpec(name="ct-stack", resources=[base]), {})
    assert "firewall" not in off["resource"][_CT_TYPE]["ct"]["network_interface"][0]
    on = stack_to_tfjson(
        StackSpec(name="ct-stack", resources=[{**base, "firewall": {"enabled": True}}]), {}
    )
    assert on["resource"][_CT_TYPE]["ct"]["network_interface"][0]["firewall"] is True


# ── Validation warning (AC-ENABLE-2) ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_warning_rules_without_enable():
    """AC-ENABLE-2: rules defined but firewall not enabled → warning (no block)."""
    spec = _vm_spec(enabled=False, rules=[{"type": "out", "action": "ACCEPT", "proto": "tcp", "dport": "443"}])
    from backend.plus.stacks import validation
    with patch.object(validation, "_node_exists", AsyncMock(return_value=True)):
        warnings = await semantic_warnings(spec)
    assert any("not enabled" in w for w in warnings)


@pytest.mark.asyncio
async def test_no_warning_when_enabled():
    """AC-ENABLE-2: enabled=True → no firewall-not-enabled warning."""
    spec = _vm_spec(enabled=True, rules=[{"type": "out", "action": "ACCEPT", "proto": "tcp", "dport": "443"}])
    from backend.plus.stacks import validation
    with patch.object(validation, "_node_exists", AsyncMock(return_value=True)):
        warnings = await semantic_warnings(spec)
    assert not any("not enabled" in w for w in warnings)


# ── firewall_commit plan builders (pure) ──────────────────────────────────────

def test_has_firewall():
    assert fc.has_firewall(_vm_spec(enabled=True)) is True
    assert fc.has_firewall(StackSpec(
        name="sg-only", resources=[{"name": "web", "node": "pve", "template": "deb12"}],
        security_groups=[{"name": "a"}],
    )) is True
    assert fc.has_firewall(_vm_spec()) is False  # no firewall, no SG


def test_collect_group_rule_refs():
    spec = StackSpec(
        name="ref-stack",
        resources=[{"name": "web", "node": "pve", "template": "deb12",
                    "firewall": {"enabled": True, "rules": [{"type": "group", "action": "webfw"}]}}],
        security_groups=[{"name": "base", "rules": [{"type": "group", "action": "shared"}]}],
    )
    assert fc.collect_group_rule_refs(spec) == {"webfw", "shared"}


def test_sg_naming():
    assert fc.stack_sg_name(12, "web") == "p3s12-web"
    assert fc.stack_sg_prefix(12) == "p3s12-"


def test_build_plan_resolves_stack_sg_and_kind():
    """AC-SG-2/3: stack-owned group action → prefixed; existing group passes through.
    LXC deployed kind → qemu/lxc Proxmox path segment."""
    spec = StackSpec(
        name="plan-stack",
        resources=[
            {"name": "web", "node": "pve", "template": "deb12",
             "firewall": {"enabled": True, "policy_out": "DROP", "rules": [
                 {"type": "out", "action": "ACCEPT", "proto": "tcp", "dport": "443"},
                 {"type": "group", "action": "webfw"},      # stack-owned → prefixed
                 {"type": "group", "action": "mgmt-ext"},   # existing → passthrough
             ]}},
            {"type": "lxc", "name": "ct", "node": "pve",
             "template": "local:vztmpl/debian-12.tar.zst", "rootfs_datastore": "local",
             "hostname": "ct", "firewall": {"enabled": True}},
        ],
        security_groups=[{"name": "webfw", "rules": [{"type": "in", "action": "ACCEPT", "proto": "tcp", "dport": "80"}]}],
    )
    plan = fc.build_firewall_plan(7, spec, [
        {"resource_name": "web", "vmid": 101, "kind": "vm", "node": "pve"},
        {"resource_name": "ct", "vmid": 102, "kind": "lxc", "node": "pve"},
    ])
    assert [s.name for s in plan.security_groups] == ["p3s7-webfw"]
    web = next(g for g in plan.guests if g.vmid == 101)
    assert web.kind == "qemu"
    assert web.options == {"enable": 1, "policy_out": "DROP"}
    actions = [r["action"] for r in web.rules]
    assert actions == ["ACCEPT", "p3s7-webfw", "mgmt-ext"]  # stack SG resolved, existing kept
    ct = next(g for g in plan.guests if g.vmid == 102)
    assert ct.kind == "lxc"


def test_build_plan_skips_guest_without_firewall():
    """AC-MUT-2: a deployed guest whose spec has no firewall block gets no commit."""
    spec = StackSpec(name="mix-stack", resources=[
        {"name": "web", "node": "pve", "template": "deb12",
         "firewall": {"enabled": True}},
        {"name": "db", "node": "pve", "template": "deb12"},  # no firewall
    ])
    plan = fc.build_firewall_plan(1, spec, [
        {"resource_name": "web", "vmid": 101, "kind": "vm", "node": "pve"},
        {"resource_name": "db", "vmid": 102, "kind": "vm", "node": "pve"},
    ])
    assert [g.vmid for g in plan.guests] == [101]


# ── firewall_commit executors (mocked ProxmoxClient) ──────────────────────────

@pytest.mark.asyncio
async def test_apply_firewall_full_sequence():
    """AC-LC-1: SGs created+filled, guest option set, rules replaced (delete-all + set)."""
    client = AsyncMock()
    client.get_guest_firewall_rules = AsyncMock(return_value=[{"pos": 0}, {"pos": 1}])
    spec = StackSpec(
        name="seq-stack",
        resources=[{"name": "web", "node": "pve", "template": "deb12",
                    "firewall": {"enabled": True, "policy_out": "DROP", "rules": [
                        {"type": "out", "action": "ACCEPT", "proto": "tcp", "dport": "443"},
                    ]}}],
        security_groups=[{"name": "webfw", "rules": [{"type": "in", "action": "ACCEPT", "proto": "tcp", "dport": "80"}]}],
    )
    with patch("backend.services.proxmox.ProxmoxClient", return_value=client), \
         patch("backend.services.proxmox.ProxmoxAuth", side_effect=lambda **kw: kw):
        await fc.apply_firewall(_node(), 7, spec, [{"resource_name": "web", "vmid": 101, "kind": "vm", "node": "pve"}])
    # SG delete (idempotent replace) + create + rule, under the prefixed name
    deleted_sgs = {c.args[1] for c in client.delete_firewall_group.await_args_list}
    assert "p3s7-webfw" in deleted_sgs
    created_sg = client.create_firewall_group.await_args.args[1]
    assert created_sg["group"] == "p3s7-webfw"
    client.create_firewall_group_rule.assert_awaited()
    # guest option set
    client.update_guest_firewall_options.assert_awaited_once()
    # delete-all (2 existing rules, high→low) then create the stack rule
    assert client.delete_guest_firewall_rule.await_count == 2
    client.create_guest_firewall_rule.assert_awaited_once()


@pytest.mark.asyncio
async def test_apply_firewall_uses_tofu_token():
    """AC-RBAC-2: the firewall commit runs over the tofu-token identity."""
    client = AsyncMock()
    client.get_guest_firewall_rules = AsyncMock(return_value=[])
    captured = {}
    spec = _vm_spec(enabled=True, rules=[{"type": "out", "action": "ACCEPT", "proto": "tcp", "dport": "443"}])
    with patch("backend.services.proxmox.ProxmoxClient", return_value=client), \
         patch("backend.services.proxmox.ProxmoxAuth", side_effect=lambda **kw: captured.update(kw) or kw):
        await fc.apply_firewall(_node(), 1, spec, [{"resource_name": "web", "vmid": 101, "kind": "vm", "node": "pve"}])
    assert captured["value"] == "root@pam!tofu"
    assert captured["secret"] == "secret"


@pytest.mark.asyncio
async def test_destroy_only_stack_prefixed_sgs():
    """AC-LC-2: destroy deletes only the stack's p3s<id>- security groups."""
    client = AsyncMock()
    client.get_firewall_groups = AsyncMock(return_value=[
        {"group": "p3s7-webfw"}, {"group": "p3s7-base"},
        {"group": "mgmt-ext"}, {"group": "p3s99-other"},  # foreign / other stack
    ])
    with patch("backend.services.proxmox.ProxmoxClient", return_value=client), \
         patch("backend.services.proxmox.ProxmoxAuth", side_effect=lambda **kw: kw):
        await fc.destroy_stack_security_groups(_node(), 7)
    deleted = {c.args[1] for c in client.delete_firewall_group.await_args_list}
    assert deleted == {"p3s7-webfw", "p3s7-base"}


# ── deploy_service SG-existence pre-check (AC-SG-4) ────────────────────────────

@pytest.mark.asyncio
async def test_sg_precheck_unknown_group_422():
    """AC-SG-4: a group ref that is neither stack-owned nor existing → 422."""
    spec = _vm_spec(enabled=True, rules=[{"type": "group", "action": "ghost"}])
    client = AsyncMock()
    client.get_firewall_groups = AsyncMock(return_value=[{"group": "other"}])
    with patch("backend.services.proxmox.ProxmoxClient", return_value=client), \
         patch("backend.services.proxmox.ProxmoxAuth", side_effect=lambda **kw: kw):
        with pytest.raises(HTTPException) as ei:
            await ds.assert_stack_firewall_groups_exist(_node(), spec)
    assert ei.value.status_code == 422
    assert ei.value.detail["error"] == "security_group_not_found"
    assert ei.value.detail["groups"] == ["ghost"]


@pytest.mark.asyncio
async def test_sg_precheck_stack_owned_ok():
    """AC-SG-4: a group ref to a stack-owned SG → no Proxmox read, no 422."""
    spec = StackSpec(
        name="ok-stack",
        resources=[{"name": "web", "node": "pve", "template": "deb12",
                    "firewall": {"enabled": True, "rules": [{"type": "group", "action": "webfw"}]}}],
        security_groups=[{"name": "webfw"}],
    )
    # no ProxmoxClient patch needed — stack-owned refs short-circuit before the read
    await ds.assert_stack_firewall_groups_exist(_node(), spec)


@pytest.mark.asyncio
async def test_sg_precheck_existing_cluster_sg_ok():
    """AC-SG-3: a group ref to an existing (non-stack) cluster SG passes."""
    spec = _vm_spec(enabled=True, rules=[{"type": "group", "action": "mgmt-ext"}])
    client = AsyncMock()
    client.get_firewall_groups = AsyncMock(return_value=[{"group": "mgmt-ext"}])
    with patch("backend.services.proxmox.ProxmoxClient", return_value=client), \
         patch("backend.services.proxmox.ProxmoxAuth", side_effect=lambda **kw: kw):
        await ds.assert_stack_firewall_groups_exist(_node(), spec)  # no raise


# ── Mutations-block: router guard (AC-MUT-1/2/3) ──────────────────────────────

@pytest.mark.asyncio
async def test_guard_blocks_stack_managed_firewall():
    """AC-MUT-1: a guest with a stack firewall block → 409 on manual FW mutation."""
    from backend.routers import firewall as fw
    node = SimpleNamespace(id=3)
    with patch("backend.services.nodes_service.get_node_for_proxmox_name", AsyncMock(return_value=node)), \
         patch("backend.core.plus_protocol.plus_behavior") as pb, \
         patch.object(fw, "write_audit_log", AsyncMock()) as audit:
        pb.get_stack_firewall_for_vm = AsyncMock(return_value={"stack_id": 9, "stack_name": "web"})
        with pytest.raises(HTTPException) as ei:
            await fw._assert_guest_firewall_not_stack_managed("pve", 101, "alice", "local")
    assert ei.value.status_code == 409
    assert ei.value.detail["error"] == "guest_firewall_managed_by_stack"
    audit.assert_awaited_once()


@pytest.mark.asyncio
async def test_guard_allows_when_no_firewall_block():
    """AC-MUT-2: a stack guest without a firewall block → editable (no raise)."""
    from backend.routers import firewall as fw
    node = SimpleNamespace(id=3)
    with patch("backend.services.nodes_service.get_node_for_proxmox_name", AsyncMock(return_value=node)), \
         patch("backend.core.plus_protocol.plus_behavior") as pb:
        pb.get_stack_firewall_for_vm = AsyncMock(return_value=None)
        await fw._assert_guest_firewall_not_stack_managed("pve", 101, "alice", "local")


@pytest.mark.asyncio
async def test_guard_core_mode_no_op():
    """AC-MUT / AC-RBAC-3: Core get_stack_firewall_for_vm → None → never blocks."""
    from backend.core.plus_protocol import CorePlusBehavior
    assert await CorePlusBehavior().get_stack_firewall_for_vm(1, 101) is None
