# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-76 Phase 2b: transpile + plan/state parsing (pure, no tofu/Proxmox)."""
from __future__ import annotations

import json

import pytest

from backend.plus.stacks.schemas import NetworkConfig, StackSpec, VMResource
from backend.plus.stacks.transpile import stack_to_tfjson
from backend.plus.stacks.deploy_service import parse_plan_json
from backend.plus.stacks.deployments import parse_state_resources

pytestmark = pytest.mark.plus_only


def _spec(**res) -> StackSpec:
    base = dict(name="web", node="pve", template="deb12")
    base.update(res)
    return StackSpec(name="webstack", resources=[VMResource(**base)])


# ── transpile mapping ─────────────────────────────────────────────────────────

def test_transpile_count_expands_to_named_resources():
    spec = _spec(name="web", count=3)
    out = stack_to_tfjson(spec, {"deb12": 9000})
    vms = out["resource"]["proxmox_virtual_environment_vm"]
    assert set(vms) == {"web-1", "web-2", "web-3"}


def test_transpile_count_one_keeps_name():
    spec = _spec(name="web", count=1)
    vms = stack_to_tfjson(spec, {"deb12": 9000})["resource"]["proxmox_virtual_environment_vm"]
    assert set(vms) == {"web"}


def test_transpile_no_vm_id_in_block():
    spec = _spec()
    block = stack_to_tfjson(spec, {"deb12": 9000})["resource"]["proxmox_virtual_environment_vm"]["web"]
    assert "vm_id" not in block               # Proxmox auto-assigns (AC-2B-ISO-3)
    assert block["clone"]["vm_id"] == 9000    # template VMID only in clone


def test_transpile_explicit_vmid_single():
    spec = _spec(name="web", count=1, vmid=250)
    block = stack_to_tfjson(spec, {"deb12": 9000})["resource"]["proxmox_virtual_environment_vm"]["web"]
    assert block["vm_id"] == 250              # honored when explicitly set
    assert block["clone"]["vm_id"] == 9000    # template VMID unchanged


def test_transpile_explicit_vmid_count_offset():
    # count>1 with a pinned vmid → base + offset keeps each instance unique
    spec = _spec(name="web", count=3, vmid=250)
    vms = stack_to_tfjson(spec, {"deb12": 9000})["resource"]["proxmox_virtual_environment_vm"]
    assert vms["web-1"]["vm_id"] == 250
    assert vms["web-2"]["vm_id"] == 251
    assert vms["web-3"]["vm_id"] == 252


def test_transpile_field_mapping():
    spec = _spec(
        cores=4, sockets=2, memory=4096, disk=50, cpu_type="x86-64-v2",
        network=NetworkConfig(bridge="vmbr1", tag=42), tags=["web", "prod"],
        pool="mypool", start_after_create=False,
    )
    block = stack_to_tfjson(spec, {"deb12": 100})["resource"]["proxmox_virtual_environment_vm"]["web"]
    assert block["node_name"] == "pve"
    assert block["cpu"] == {"cores": 4, "sockets": 2, "type": "x86-64-v2"}
    assert block["memory"]["dedicated"] == 4096
    assert block["disk"][0]["size"] == 50
    assert block["network_device"][0]["bridge"] == "vmbr1"
    assert block["network_device"][0]["vlan_id"] == 42
    assert block["tags"] == ["web", "prod"]
    assert block["pool_id"] == "mypool"
    assert block["started"] is False


def test_transpile_agent_default_enabled():
    # Default agent=True → full Proxmox agent integration (IP display, graceful shutdown)
    block = stack_to_tfjson(_spec(), {"deb12": 9000})["resource"]["proxmox_virtual_environment_vm"]["web"]
    assert block["agent"] == {"enabled": True}


def test_transpile_agent_disabled_when_opted_out():
    block = stack_to_tfjson(_spec(agent=False), {"deb12": 9000})["resource"]["proxmox_virtual_environment_vm"]["web"]
    assert block["agent"] == {"enabled": False}


def test_transpile_provider_has_no_inline_creds():
    out = stack_to_tfjson(_spec(), {"deb12": 1})
    assert out["provider"]["proxmox"] == {}          # token via env (AC-2B-TRANS-4)
    assert out["terraform"]["required_providers"]["proxmox"]["source"] == "bpg/proxmox"


def test_transpile_only_resource_blocks_no_import_or_data():
    out = stack_to_tfjson(_spec(), {"deb12": 1})
    assert set(out) == {"terraform", "provider", "resource"}  # no data/import (AC-2B-ISO-2)


def test_transpile_missing_template_raises_keyerror():
    with pytest.raises(KeyError):
        stack_to_tfjson(_spec(), {})  # template not resolved


# ── plan JSON parsing ─────────────────────────────────────────────────────────

def test_parse_plan_json_counts_and_resources():
    lines = [
        json.dumps({"type": "planned_change", "change": {
            "action": "create", "resource": {"addr": "proxmox_virtual_environment_vm.web-1"}}}),
        json.dumps({"type": "planned_change", "change": {
            "action": "replace", "resource": {"addr": "proxmox_virtual_environment_vm.web-2"}}}),
        json.dumps({"type": "change_summary", "changes": {"add": 1, "change": 0, "remove": 1}}),
        "not json at all",
    ]
    summary = parse_plan_json("\n".join(lines))
    assert summary.create == 1 and summary.destroy == 1
    assert summary.replace == 1
    assert {r.name for r in summary.resources} == {
        "proxmox_virtual_environment_vm.web-1", "proxmox_virtual_environment_vm.web-2"}


def test_parse_plan_json_empty():
    assert parse_plan_json("").create == 0


def test_transpile_emits_clone_ignore_changes():
    # clone is create-time only → lifecycle.ignore_changes=[clone] prevents phantom drift
    block = stack_to_tfjson(_spec(), {"deb12": 9000})["resource"]["proxmox_virtual_environment_vm"]["web"]
    assert block["lifecycle"] == {"ignore_changes": ["clone"]}


# ── state JSON parsing ────────────────────────────────────────────────────────

def test_parse_state_resources_extracts_vms():
    state = json.dumps({"resources": [
        {"type": "proxmox_virtual_environment_vm", "name": "web-1",
         "instances": [{"attributes": {"vm_id": 123, "node_name": "pve"}}]},
        {"type": "proxmox_virtual_environment_vm", "name": "web-2",
         "instances": [{"attributes": {"vm_id": 124, "node_name": "pve2"}}]},
        {"type": "some_other_thing", "name": "x", "instances": [{"attributes": {"vm_id": 999}}]},
    ]})
    res = parse_state_resources(state)
    assert {(r["resource_name"], r["vmid"]) for r in res} == {("web-1", 123), ("web-2", 124)}


def test_parse_state_resources_tolerates_garbage():
    assert parse_state_resources("{bad json") == []
    assert parse_state_resources(json.dumps({})) == []
