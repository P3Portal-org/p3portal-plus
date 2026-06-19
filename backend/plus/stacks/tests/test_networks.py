# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-87: stack-owned networks (Bridge MVP) — schema, transpile, gates, fan-out.

Pure/mocked — no real tofu/Proxmox. Covers: byte-for-byte transpile without a
``networks`` block (AC-TRANS-2), the bridge resource block + depends_on
(AC-TRANS-1/AC-LC-1), the vnet-422 MVP gate (AC-VN-3), the name-collision 422
(AC-MODEL-3), the destroy-protection 409 + foreign-vs-own fan-out (AC-DES), and
the one-installation node fold (Tech-Design E).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from backend.plus.stacks import deploy_service as ds
from backend.plus.stacks import network_usage
from backend.plus.stacks.schemas import (
    BridgeNetwork,
    NetworkConfig,
    PlanResource,
    PlanSummary,
    StackSpec,
    VMResource,
    VNetNetwork,
)
from backend.plus.stacks.transpile import stack_to_tfjson
from backend.plus.stacks.validation import validate_structure

pytestmark = pytest.mark.plus_only

_BRIDGE_TYPE = "proxmox_virtual_environment_network_linux_bridge"


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


def _vm(name="web", node="pve", bridge=None, count=1, type_="vm"):
    cfg = dict(name=name, node=node, template="deb12", count=count)
    if bridge is not None:
        cfg["network"] = NetworkConfig(bridge=bridge)
    return VMResource(**cfg)


# ── Schema: discriminated union + validators ──────────────────────────────────

def test_network_dict_without_kind_defaults_to_bridge():
    spec = StackSpec(name="webstack", resources=[_vm()],
                     networks=[{"name": "vmbr9", "node": "pve"}])
    assert isinstance(spec.networks[0], BridgeNetwork)
    assert spec.networks[0].name == "vmbr9"


def test_bridge_name_must_be_vmbr():
    with pytest.raises(ValidationError):
        BridgeNetwork(name="brX", node="pve")


def test_network_name_must_be_unique():
    with pytest.raises(ValidationError) as ei:
        StackSpec(name="webstack", resources=[_vm()], networks=[
            {"name": "vmbr9", "node": "pve"}, {"name": "vmbr9", "node": "pve"},
        ])
    assert "duplicate network names" in str(ei.value)


def test_network_name_must_not_clash_with_resource_name():
    # A resource named "vmbr9" + a bridge "vmbr9" → clash (after-validator).
    with pytest.raises(ValidationError) as ei:
        StackSpec(name="webstack",
                  resources=[_vm(name="vmbr9")],
                  networks=[{"name": "vmbr9", "node": "pve"}])
    assert "clash" in str(ei.value)


def test_vnet_dict_keeps_kind_via_discriminator():
    # PROJ-89: a VNet now requires a subnet (cidr + gateway).
    spec = StackSpec(name="webstack", resources=[_vm()], networks=[
        {"kind": "vnet", "name": "v1", "zone": "z1",
         "subnet_cidr": "10.0.0.0/24", "subnet_gateway": "10.0.0.1"},
    ])
    assert isinstance(spec.networks[0], VNetNetwork)


# ── Validation: vnet is now built (PROJ-89), bridge allowed ───────────────────

def test_validate_allows_vnet():
    # PROJ-89: the MVP gate is gone — kind="vnet" with a subnet validates.
    raw = {"name": "webstack",
           "resources": [{"name": "web", "node": "pve", "template": "deb12"}],
           "networks": [{"kind": "vnet", "name": "v1", "zone": "z1",
                         "subnet_cidr": "10.0.0.0/24", "subnet_gateway": "10.0.0.1"}]}
    spec, errors, _warnings = validate_structure(raw)
    assert spec is not None
    assert errors == []


def test_validate_allows_bridge():
    raw = {"name": "webstack", "resources": [{"name": "web", "node": "pve", "template": "deb12"}],
           "networks": [{"name": "vmbr9", "node": "pve"}]}
    spec, errors, _warnings = validate_structure(raw)
    assert spec is not None
    assert errors == []


# ── Transpile: byte-for-byte without networks + bridge block + depends_on ──────

def test_transpile_without_networks_has_no_bridge_map():
    spec = StackSpec(name="webstack", resources=[_vm()])
    out = stack_to_tfjson(spec, {"deb12": 9000})
    assert _BRIDGE_TYPE not in out["resource"]
    # And the VM block carries no depends_on (legacy form, AC-TRANS-2).
    assert "depends_on" not in out["resource"]["proxmox_virtual_environment_vm"]["web"]


def test_transpile_emits_bridge_block():
    spec = StackSpec(name="webstack", resources=[_vm()], networks=[
        {"name": "vmbr9", "node": "pve", "vlan_aware": True, "mtu": 9000, "comment": "stack net"},
    ])
    out = stack_to_tfjson(spec, {"deb12": 9000})
    br = out["resource"][_BRIDGE_TYPE]["vmbr9"]
    assert br == {
        "node_name": "pve", "name": "vmbr9", "vlan_aware": True,
        "mtu": 9000, "comment": "stack net",
    }


def test_transpile_bridge_omits_optional_unset():
    spec = StackSpec(name="webstack", resources=[_vm()],
                     networks=[{"name": "vmbr9", "node": "pve"}])
    br = stack_to_tfjson(spec, {"deb12": 9000})["resource"][_BRIDGE_TYPE]["vmbr9"]
    assert "mtu" not in br and "comment" not in br
    assert br["vlan_aware"] is False


def test_vm_referencing_stack_bridge_gets_depends_on():
    spec = StackSpec(name="webstack",
                     resources=[_vm(bridge="vmbr9")],
                     networks=[{"name": "vmbr9", "node": "pve"}])
    block = stack_to_tfjson(spec, {"deb12": 9000})["resource"]["proxmox_virtual_environment_vm"]["web"]
    assert block["depends_on"] == [f"{_BRIDGE_TYPE}.vmbr9"]


def test_vm_referencing_existing_bridge_has_no_depends_on():
    # vmbr0 is NOT in networks → it's an existing/shared bridge → no depends_on.
    spec = StackSpec(name="webstack",
                     resources=[_vm(bridge="vmbr0")],
                     networks=[{"name": "vmbr9", "node": "pve"}])
    block = stack_to_tfjson(spec, {"deb12": 9000})["resource"]["proxmox_virtual_environment_vm"]["web"]
    assert "depends_on" not in block


def test_lxc_referencing_stack_bridge_gets_depends_on():
    lxc = {
        "type": "lxc", "name": "ct", "node": "pve",
        "template": "local:vztmpl/debian-12-standard.tar.zst",
        "rootfs_datastore": "local-lvm", "hostname": "ct1",
        "network": {"bridge": "vmbr9"},
    }
    spec = StackSpec(name="webstack", resources=[lxc],
                     networks=[{"name": "vmbr9", "node": "pve"}])
    block = stack_to_tfjson(spec, {})["resource"]["proxmox_virtual_environment_container"]["ct"]
    assert block["depends_on"] == [f"{_BRIDGE_TYPE}.vmbr9"]


def test_mixed_stack_emits_both_maps():
    lxc = {
        "type": "lxc", "name": "ct", "node": "pve",
        "template": "local:vztmpl/x.tar.zst", "rootfs_datastore": "local-lvm",
        "hostname": "ct1",
    }
    spec = StackSpec(name="webstack", resources=[_vm(), lxc],
                     networks=[{"name": "vmbr9", "node": "pve"}])
    res = stack_to_tfjson(spec, {"deb12": 9000})["resource"]
    assert "proxmox_virtual_environment_vm" in res
    assert "proxmox_virtual_environment_container" in res
    assert _BRIDGE_TYPE in res


# ── resolve_target_node folds the bridge node into the one-installation check ──

@pytest.mark.asyncio
async def test_resolve_target_node_includes_network_node():
    spec = StackSpec(name="webstack", resources=[_vm(node="pve")],
                     networks=[{"name": "vmbr9", "node": "pve"}])
    with patch.object(ds, "get_node_for_proxmox_name", AsyncMock(return_value=_node())):
        node = await ds.resolve_target_node(spec)
    assert node.id == 1


@pytest.mark.asyncio
async def test_resolve_target_node_bridge_on_other_installation_422():
    # Resources on node "pve" (id 1), bridge on node "other" (id 2) → 2 installs.
    spec = StackSpec(name="webstack", resources=[_vm(node="pve")],
                     networks=[{"name": "vmbr9", "node": "other"}])

    async def _lookup(name):
        return _node(node_id=1) if name == "pve" else _node(node_id=2)

    with patch.object(ds, "get_node_for_proxmox_name", AsyncMock(side_effect=_lookup)):
        with pytest.raises(HTTPException) as ei:
            await ds.resolve_target_node(spec)
    assert ei.value.status_code == 422
    assert ei.value.detail == "multiple_installations_not_supported"


# ── assert_stack_networks_free (name collision 422) ───────────────────────────

@pytest.mark.asyncio
async def test_assert_stack_networks_free_collision_422():
    spec = StackSpec(name="webstack", resources=[_vm()],
                     networks=[{"name": "vmbr9", "node": "pve"}])
    fake_client = AsyncMock()
    fake_client.get_node_network_interfaces = AsyncMock(
        return_value=[{"iface": "vmbr0"}, {"iface": "vmbr9"}]
    )
    with patch("backend.services.proxmox.ProxmoxClient", return_value=fake_client):
        with pytest.raises(HTTPException) as ei:
            await ds.assert_stack_networks_free(_node(), spec)
    assert ei.value.status_code == 422
    assert ei.value.detail["error"] == "network_name_taken"
    assert ei.value.detail["taken"] == ["vmbr9"]


@pytest.mark.asyncio
async def test_assert_stack_networks_free_no_collision_ok():
    spec = StackSpec(name="webstack", resources=[_vm()],
                     networks=[{"name": "vmbr9", "node": "pve"}])
    fake_client = AsyncMock()
    fake_client.get_node_network_interfaces = AsyncMock(return_value=[{"iface": "vmbr0"}])
    with patch("backend.services.proxmox.ProxmoxClient", return_value=fake_client):
        await ds.assert_stack_networks_free(_node(), spec)  # no raise


@pytest.mark.asyncio
async def test_assert_stack_networks_free_no_networks_skips_proxmox():
    spec = StackSpec(name="webstack", resources=[_vm()])
    # No ProxmoxClient patch → if it touched Proxmox the test would error.
    await ds.assert_stack_networks_free(_node(), spec)


# ── _networks_being_destroyed ─────────────────────────────────────────────────

def test_networks_being_destroyed_on_destroy_returns_all():
    spec = StackSpec(name="webstack", resources=[_vm()], networks=[
        {"name": "vmbr9", "node": "pve"}, {"name": "vmbr8", "node": "pve"},
    ])
    out = ds._networks_being_destroyed(spec, "destroy", PlanSummary())
    assert {n.name for n in out} == {"vmbr9", "vmbr8"}


def test_networks_being_destroyed_on_apply_only_deleted():
    spec = StackSpec(name="webstack", resources=[_vm()], networks=[
        {"name": "vmbr9", "node": "pve"}, {"name": "vmbr8", "node": "pve"},
    ])
    summary = PlanSummary(resources=[
        PlanResource(name=f"{_BRIDGE_TYPE}.vmbr9", action="delete"),
        PlanResource(name="proxmox_virtual_environment_vm.web", action="update"),
    ])
    out = ds._networks_being_destroyed(spec, "apply", summary)
    assert {n.name for n in out} == {"vmbr9"}


def test_networks_being_destroyed_on_apply_pure_create_empty():
    spec = StackSpec(name="webstack", resources=[_vm()],
                     networks=[{"name": "vmbr9", "node": "pve"}])
    summary = PlanSummary(resources=[
        PlanResource(name=f"{_BRIDGE_TYPE}.vmbr9", action="create"),
    ])
    assert ds._networks_being_destroyed(spec, "apply", summary) == []


# ── assert_network_destroy_allowed (409 with foreign guests) ──────────────────

@pytest.mark.asyncio
async def test_destroy_blocked_by_foreign_guest_409():
    spec = StackSpec(name="webstack", resources=[_vm()],
                     networks=[{"name": "vmbr9", "node": "pve"}])
    foreign = [{"vmid": 200, "name": "foreign-vm", "node": "pve", "kind": "qemu"}]
    with patch.object(network_usage, "find_foreign_network_users",
                      AsyncMock(return_value=foreign)):
        with pytest.raises(HTTPException) as ei:
            await ds.assert_network_destroy_allowed(
                1, spec, _node(), "destroy", PlanSummary(), "alice",
            )
    assert ei.value.status_code == 409
    assert ei.value.detail["error"] == "network_in_use"
    assert ei.value.detail["networks"]["vmbr9"] == foreign


@pytest.mark.asyncio
async def test_destroy_allowed_when_only_own_guests():
    spec = StackSpec(name="webstack", resources=[_vm()],
                     networks=[{"name": "vmbr9", "node": "pve"}])
    # find_foreign_network_users already excludes own guests → empty = no block.
    with patch.object(network_usage, "find_foreign_network_users",
                      AsyncMock(return_value=[])):
        await ds.assert_network_destroy_allowed(
            1, spec, _node(), "destroy", PlanSummary(), "alice",
        )  # no raise


# ── network_usage fan-out: segment match + own exclusion ──────────────────────

@pytest.mark.asyncio
async def test_find_foreign_users_segment_match_excludes_own():
    fake_client = AsyncMock()
    fake_client.get_cluster_resources_v2 = AsyncMock(return_value=[
        {"vmid": 100, "name": "own-vm", "node": "pve", "type": "qemu"},
        {"vmid": 200, "name": "foreign-vm", "node": "pve", "type": "qemu"},
        {"vmid": 300, "name": "other-bridge", "node": "pve", "type": "qemu"},
    ])

    async def _cfg(auth, node, vmid, kind):
        return {
            100: {"net0": "virtio=AA,bridge=vmbr9"},   # own → excluded
            200: {"net0": "virtio=BB,bridge=vmbr9"},   # foreign → reported
            300: {"net0": "virtio=CC,bridge=vmbr90"},  # different bridge → no match
        }[vmid]

    fake_client.get_vm_config = AsyncMock(side_effect=_cfg)

    with patch("backend.plus.stacks.network_usage.ProxmoxClient", return_value=fake_client), \
         patch.object(network_usage.deployments, "list_deployed_resources",
                      AsyncMock(return_value=[{"vmid": 100, "portal_node_id": 1}])):
        users = await network_usage.find_foreign_network_users(
            _node(), "vmbr9", stack_id=1, bridge_node="pve",
        )

    assert [u["vmid"] for u in users] == [200]


@pytest.mark.asyncio
async def test_find_foreign_users_scopes_to_bridge_node():
    # A guest on a DIFFERENT node referencing the same bridge name is ignored
    # (node-local bridge — different physical bridge).
    fake_client = AsyncMock()
    fake_client.get_cluster_resources_v2 = AsyncMock(return_value=[
        {"vmid": 200, "name": "other-node-vm", "node": "pve2", "type": "qemu"},
    ])
    fake_client.get_vm_config = AsyncMock(return_value={"net0": "virtio=BB,bridge=vmbr9"})

    with patch("backend.plus.stacks.network_usage.ProxmoxClient", return_value=fake_client), \
         patch.object(network_usage.deployments, "list_deployed_resources",
                      AsyncMock(return_value=[])):
        users = await network_usage.find_foreign_network_users(
            _node(), "vmbr9", stack_id=1, bridge_node="pve",
        )

    assert users == []
    fake_client.get_vm_config.assert_not_awaited()


def test_bridge_in_config_exact_segment():
    # vmbr1 must NOT match vmbr10 (substring trap).
    assert network_usage._bridge_in_config({"net0": "virtio=AA,bridge=vmbr1"}, "vmbr1")
    assert not network_usage._bridge_in_config({"net0": "virtio=AA,bridge=vmbr10"}, "vmbr1")


# ── engine SDN lock (dormant) ─────────────────────────────────────────────────

def test_sdn_apply_lock_is_singleton():
    from backend.plus.stacks import engine
    assert engine.get_sdn_apply_lock() is engine.get_sdn_apply_lock()
