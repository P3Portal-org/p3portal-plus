# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-89: stack-owned SDN networks (VNet + Subnet + SNAT).

Pure/mocked — no real tofu/Proxmox. Covers: the unlocked VNetNetwork schema +
subnet/gateway/snat validators (AC-MODEL-1 / AC-SUBNET), the SDN transpile
(zone dedup / vnet / subnet / applier / guest depends_on, AC-ZONE/VNET/SUBNET/
TRANS), the byte-for-byte legacy output without a VNet (AC-MODEL-4), the
cluster-wide name-collision pre-check with own-exclusion (AC-MODEL-3), the
cluster-wide destroy-protection 409 (AC-DES), the pending-SDN vorab-check
(AC-PENDING), the _SDN_APPLY_LOCK serialization 409 (AC-APPLY-1), and the
runner's apply_sdn commit (AC-LC-1).
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from backend.plus.stacks import deploy_service as ds
from backend.plus.stacks import engine, network_usage, runner
from backend.plus.stacks.schemas import (
    NetworkConfig,
    PlanResource,
    PlanSummary,
    StackSpec,
    VMResource,
    VNetNetwork,
)
from backend.plus.stacks.transpile import (
    _APPLIER_LABEL,
    _SDN_APPLIER_RESOURCE_TYPE,
    _SDN_SUBNET_RESOURCE_TYPE,
    _SDN_VNET_RESOURCE_TYPE,
    _SDN_ZONE_RESOURCE_TYPE,
    stack_to_tfjson,
)

pytestmark = pytest.mark.plus_only


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


def _vm(name="web", node="pve", bridge=None, count=1):
    cfg = dict(name=name, node=node, template="deb12", count=count)
    if bridge is not None:
        cfg["network"] = NetworkConfig(bridge=bridge)
    return VMResource(**cfg)


def _vnet(name="v1", zone="z1", cidr="10.0.0.0/24", gw="10.0.0.1", snat=False):
    return {"kind": "vnet", "name": name, "zone": zone,
            "subnet_cidr": cidr, "subnet_gateway": gw, "snat": snat}


# ── Schema: subnet / gateway / snat / zone validators ─────────────────────────

def test_vnet_requires_subnet():
    with pytest.raises(ValidationError):
        VNetNetwork(kind="vnet", name="v1", zone="z1")   # no subnet → 422


def test_vnet_gateway_must_be_inside_subnet():
    with pytest.raises(ValidationError) as ei:
        VNetNetwork(kind="vnet", name="v1", zone="z1",
                    subnet_cidr="10.0.0.0/24", subnet_gateway="192.168.1.1")
    assert "not inside" in str(ei.value)


def test_vnet_invalid_cidr():
    with pytest.raises(ValidationError):
        VNetNetwork(kind="vnet", name="v1", zone="z1",
                    subnet_cidr="not-a-cidr", subnet_gateway="10.0.0.1")


def test_vnet_zone_regex():
    with pytest.raises(ValidationError):
        VNetNetwork(kind="vnet", name="v1", zone="this-is-too-long",
                    subnet_cidr="10.0.0.0/24", subnet_gateway="10.0.0.1")


def test_vnet_snat_default_off_and_settable():
    off = VNetNetwork(kind="vnet", name="v1", zone="z1",
                      subnet_cidr="10.0.0.0/24", subnet_gateway="10.0.0.1")
    assert off.snat is False
    on = VNetNetwork(kind="vnet", name="v1", zone="z1",
                     subnet_cidr="10.0.0.0/24", subnet_gateway="10.0.0.1", snat=True)
    assert on.snat is True


# ── Transpile: byte-for-byte without a VNet (AC-MODEL-4) ──────────────────────

def test_transpile_without_vnet_has_no_sdn_maps():
    spec = StackSpec(name="webstack", resources=[_vm()])
    out = stack_to_tfjson(spec, {"deb12": 9000})
    for rtype in (_SDN_ZONE_RESOURCE_TYPE, _SDN_VNET_RESOURCE_TYPE,
                  _SDN_SUBNET_RESOURCE_TYPE, _SDN_APPLIER_RESOURCE_TYPE):
        assert rtype not in out["resource"]


def test_provider_version_bumped_to_0109():
    out = stack_to_tfjson(StackSpec(name="webstack", resources=[_vm()]), {"deb12": 1})
    assert out["terraform"]["required_providers"]["proxmox"]["version"] == "~> 0.109"


# ── Transpile: zone / vnet / subnet / applier ─────────────────────────────────

def test_transpile_emits_zone_vnet_subnet_applier():
    spec = StackSpec(name="webstack", resources=[_vm(bridge="v1")],
                     networks=[_vnet(snat=True)])
    res = stack_to_tfjson(spec, {"deb12": 9000})["resource"]
    assert res[_SDN_ZONE_RESOURCE_TYPE]["z1"] == {
        "id": "z1", "ipam": "pve", "nodes": ["pve"],
    }
    assert res[_SDN_VNET_RESOURCE_TYPE]["v1"] == {
        "id": "v1", "zone": "z1", "depends_on": [f"{_SDN_ZONE_RESOURCE_TYPE}.z1"],
    }
    assert res[_SDN_SUBNET_RESOURCE_TYPE]["v1"] == {
        "vnet": "v1", "cidr": "10.0.0.0/24", "gateway": "10.0.0.1", "snat": True,
        "depends_on": [f"{_SDN_VNET_RESOURCE_TYPE}.v1"],
    }
    applier = res[_SDN_APPLIER_RESOURCE_TYPE][_APPLIER_LABEL]
    assert applier["on_create"] is True and applier["on_destroy"] is False
    assert applier["depends_on"] == [f"{_SDN_SUBNET_RESOURCE_TYPE}.v1"]


def test_transpile_sdn_create_order_chain():
    # Zone → VNet → Subnet → Applier → Guest: each link via explicit depends_on
    # (string attributes give tofu no implicit ordering, AC-LC-1).
    spec = StackSpec(name="webstack", resources=[_vm(bridge="v1")], networks=[_vnet()])
    res = stack_to_tfjson(spec, {"deb12": 9000})["resource"]
    assert res[_SDN_VNET_RESOURCE_TYPE]["v1"]["depends_on"] == [f"{_SDN_ZONE_RESOURCE_TYPE}.z1"]
    assert res[_SDN_SUBNET_RESOURCE_TYPE]["v1"]["depends_on"] == [f"{_SDN_VNET_RESOURCE_TYPE}.v1"]
    assert res[_SDN_APPLIER_RESOURCE_TYPE][_APPLIER_LABEL]["depends_on"] == [f"{_SDN_SUBNET_RESOURCE_TYPE}.v1"]
    assert res["proxmox_virtual_environment_vm"]["web"]["depends_on"] == [
        f"{_SDN_APPLIER_RESOURCE_TYPE}.{_APPLIER_LABEL}"]


def test_transpile_subnet_snat_default_off():
    spec = StackSpec(name="webstack", resources=[_vm(bridge="v1")],
                     networks=[_vnet(snat=False)])
    sub = stack_to_tfjson(spec, {"deb12": 9000})["resource"][_SDN_SUBNET_RESOURCE_TYPE]["v1"]
    assert sub["snat"] is False


def test_transpile_zone_dedup():
    # Two VNets in the same zone → ONE zone resource (AC-ZONE-1 / EC-7).
    spec = StackSpec(name="webstack", resources=[_vm(bridge="v1")], networks=[
        _vnet(name="v1", zone="z1"), _vnet(name="v2", zone="z1"),
    ])
    res = stack_to_tfjson(spec, {"deb12": 9000})["resource"]
    assert set(res[_SDN_ZONE_RESOURCE_TYPE]) == {"z1"}
    assert set(res[_SDN_VNET_RESOURCE_TYPE]) == {"v1", "v2"}
    # The applier depends on every subnet (sorted).
    applier = res[_SDN_APPLIER_RESOURCE_TYPE][_APPLIER_LABEL]
    assert applier["depends_on"] == sorted([
        f"{_SDN_SUBNET_RESOURCE_TYPE}.v1", f"{_SDN_SUBNET_RESOURCE_TYPE}.v2",
    ])


def test_transpile_zone_nodes_from_guests():
    # The zone spans the distinct nodes of the guests referencing its VNet (AC-ZONE-2).
    spec = StackSpec(name="webstack", resources=[
        _vm(name="a", node="pve1", bridge="v1"),
        _vm(name="b", node="pve2", bridge="v1"),
    ], networks=[_vnet()])
    zone = stack_to_tfjson(spec, {"deb12": 9000})["resource"][_SDN_ZONE_RESOURCE_TYPE]["z1"]
    assert zone["nodes"] == ["pve1", "pve2"]


def test_transpile_zone_nodes_fallback_all_guests():
    # No guest references the VNet → zone spans all distinct guest nodes (fallback).
    spec = StackSpec(name="webstack", resources=[_vm(node="pve3")], networks=[_vnet()])
    zone = stack_to_tfjson(spec, {"deb12": 9000})["resource"][_SDN_ZONE_RESOURCE_TYPE]["z1"]
    assert zone["nodes"] == ["pve3"]


def test_guest_referencing_vnet_depends_on_applier():
    spec = StackSpec(name="webstack", resources=[_vm(bridge="v1")], networks=[_vnet()])
    block = stack_to_tfjson(spec, {"deb12": 9000})["resource"]["proxmox_virtual_environment_vm"]["web"]
    assert block["depends_on"] == [f"{_SDN_APPLIER_RESOURCE_TYPE}.{_APPLIER_LABEL}"]


def test_guest_referencing_existing_sdn_has_no_depends_on():
    # vmbr0 is neither a stack bridge nor a stack VNet → existing reference.
    spec = StackSpec(name="webstack", resources=[_vm(bridge="vmbr0")], networks=[_vnet()])
    block = stack_to_tfjson(spec, {"deb12": 9000})["resource"]["proxmox_virtual_environment_vm"]["web"]
    assert "depends_on" not in block


def test_mixed_bridge_and_vnet_stack():
    spec = StackSpec(name="webstack", resources=[_vm(bridge="v1")], networks=[
        {"name": "vmbr9", "node": "pve"}, _vnet(),
    ])
    res = stack_to_tfjson(spec, {"deb12": 9000})["resource"]
    assert "proxmox_virtual_environment_network_linux_bridge" in res
    assert _SDN_VNET_RESOURCE_TYPE in res


# ── deploy_service: _spec_has_vnet ────────────────────────────────────────────

def test_spec_has_vnet():
    assert ds._spec_has_vnet(StackSpec(name="stk", resources=[_vm()], networks=[_vnet()]))
    assert not ds._spec_has_vnet(StackSpec(name="stk", resources=[_vm()]))
    assert not ds._spec_has_vnet(StackSpec(
        name="stk", resources=[_vm()], networks=[{"name": "vmbr9", "node": "pve"}]))


# ── _own_sdn_names (state list parse) ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_own_sdn_names_parses_state_list():
    out = (
        f"{_SDN_ZONE_RESOURCE_TYPE}.z1\n"
        f"{_SDN_VNET_RESOURCE_TYPE}.v1\n"
        f"{_SDN_SUBNET_RESOURCE_TYPE}.v1\n"
        "proxmox_virtual_environment_vm.web\n"
    )
    with patch.object(ds.engine, "run_tofu", AsyncMock(return_value=(0, out, ""))):
        names = await ds._own_sdn_names(1, _node())
    assert names == {"z1", "v1"}   # zone + vnet only (subnet/vm ignored)


@pytest.mark.asyncio
async def test_own_sdn_names_none_when_state_unreadable():
    with patch.object(ds.engine, "run_tofu", AsyncMock(return_value=(1, "", "no state"))):
        assert await ds._own_sdn_names(1, _node()) is None


# ── assert_stack_networks_free (SDN collision 422 + own exclusion) ────────────

@pytest.mark.asyncio
async def test_sdn_name_collision_422_foreign():
    spec = StackSpec(name="webstack", resources=[_vm(bridge="v1")], networks=[_vnet()])
    fake_client = AsyncMock()
    fake_client.get_sdn_zones = AsyncMock(return_value=[{"zone": "z1"}])   # foreign z1
    fake_client.get_sdn_vnets = AsyncMock(return_value=[])
    with patch.object(ds, "_own_sdn_names", AsyncMock(return_value=set())), \
         patch("backend.services.proxmox.ProxmoxClient", return_value=fake_client):
        with pytest.raises(HTTPException) as ei:
            await ds.assert_stack_networks_free(_node(), spec, stack_id=1)
    assert ei.value.status_code == 422
    assert ei.value.detail["error"] == "network_name_taken"
    assert "z1" in ei.value.detail["taken"]


@pytest.mark.asyncio
async def test_sdn_collision_own_excluded_ok():
    # z1 + v1 exist but are OWNED by this stack (re-deploy) → no raise.
    spec = StackSpec(name="webstack", resources=[_vm(bridge="v1")], networks=[_vnet()])
    fake_client = AsyncMock()
    fake_client.get_sdn_zones = AsyncMock(return_value=[{"zone": "z1"}])
    fake_client.get_sdn_vnets = AsyncMock(return_value=[{"vnet": "v1"}])
    with patch.object(ds, "_own_sdn_names", AsyncMock(return_value={"z1", "v1"})), \
         patch("backend.services.proxmox.ProxmoxClient", return_value=fake_client):
        await ds.assert_stack_networks_free(_node(), spec, stack_id=1)  # no raise


@pytest.mark.asyncio
async def test_sdn_collision_skipped_on_prior_deploy_unreadable_state():
    # State unreadable + a prior deployment exists → skip the SDN check (tofu
    # reconciles its own); the SDN read must NOT be touched.
    spec = StackSpec(name="webstack", resources=[_vm(bridge="v1")], networks=[_vnet()])
    fake_client = AsyncMock()
    fake_client.get_sdn_zones = AsyncMock(return_value=[{"zone": "z1"}])
    fake_client.get_sdn_vnets = AsyncMock(return_value=[])
    with patch.object(ds, "_own_sdn_names", AsyncMock(return_value=None)), \
         patch("backend.plus.stacks.deployments.list_deployments",
               AsyncMock(return_value=[{"id": 1}])), \
         patch("backend.services.proxmox.ProxmoxClient", return_value=fake_client):
        await ds.assert_stack_networks_free(_node(), spec, stack_id=1)  # no raise
    fake_client.get_sdn_zones.assert_not_awaited()


# ── _networks_being_destroyed includes VNets ──────────────────────────────────

def test_networks_being_destroyed_vnet_on_destroy():
    spec = StackSpec(name="webstack", resources=[_vm(bridge="v1")], networks=[_vnet()])
    out = ds._networks_being_destroyed(spec, "destroy", PlanSummary())
    assert {n.name for n in out} == {"v1"}


def test_networks_being_destroyed_vnet_on_apply_only_deleted():
    spec = StackSpec(name="webstack", resources=[_vm(bridge="v1")], networks=[
        _vnet(name="v1"), _vnet(name="v2", cidr="10.1.0.0/24", gw="10.1.0.1"),
    ])
    summary = PlanSummary(resources=[
        PlanResource(name=f"{_SDN_VNET_RESOURCE_TYPE}.v1", action="delete"),
    ])
    out = ds._networks_being_destroyed(spec, "apply", summary)
    assert {n.name for n in out} == {"v1"}


# ── assert_network_destroy_allowed (VNet cluster-wide 409) ────────────────────

@pytest.mark.asyncio
async def test_vnet_destroy_blocked_by_foreign_guest_409_cluster_wide():
    spec = StackSpec(name="webstack", resources=[_vm(bridge="v1")], networks=[_vnet()])
    foreign = [{"vmid": 200, "name": "foreign", "node": "pve2", "kind": "qemu"}]
    find = AsyncMock(return_value=foreign)
    with patch.object(network_usage, "find_foreign_network_users", find), \
         patch.object(ds, "write_audit_log", AsyncMock()):
        with pytest.raises(HTTPException) as ei:
            await ds.assert_network_destroy_allowed(
                1, spec, _node(), "destroy", PlanSummary(), "alice",
            )
    assert ei.value.status_code == 409
    assert ei.value.detail["networks"]["v1"] == foreign
    # VNet is cluster-wide → bridge_node=None (no node filter, AC-DES-1).
    assert find.await_args.kwargs["bridge_node"] is None


# ── foreign_pending_sdn (AC-PENDING) ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_foreign_pending_sdn_surfaces_foreign_only():
    spec = StackSpec(name="webstack", resources=[_vm(bridge="v1")], networks=[_vnet()])
    fake_client = AsyncMock()
    fake_client.get_sdn_zones = AsyncMock(return_value=[
        {"zone": "z1", "state": "new"},          # own → excluded
        {"zone": "fz", "state": "changed"},       # foreign → reported
    ])
    fake_client.get_sdn_vnets = AsyncMock(return_value=[
        {"vnet": "v1", "state": "new"},           # own → excluded
        {"vnet": "fv", "state": "new"},           # foreign → reported
        {"vnet": "stable", "state": ""},          # not pending → ignored
    ])
    with patch("backend.services.proxmox.ProxmoxClient", return_value=fake_client):
        out = await ds.foreign_pending_sdn(_node(), spec)
    got = {(o.kind, o.name, o.state) for o in out}
    assert got == {("zone", "fz", "changed"), ("vnet", "fv", "new")}


@pytest.mark.asyncio
async def test_foreign_pending_sdn_empty_without_vnet():
    spec = StackSpec(name="webstack", resources=[_vm()])
    out = await ds.foreign_pending_sdn(_node(), spec)   # no Proxmox read
    assert out == []


@pytest.mark.asyncio
async def test_foreign_pending_sdn_best_effort_on_error():
    spec = StackSpec(name="webstack", resources=[_vm(bridge="v1")], networks=[_vnet()])
    fake_client = AsyncMock()
    fake_client.get_sdn_zones = AsyncMock(side_effect=RuntimeError("boom"))
    with patch("backend.services.proxmox.ProxmoxClient", return_value=fake_client):
        assert await ds.foreign_pending_sdn(_node(), spec) == []


# ── _SDN_APPLY_LOCK serialization (AC-APPLY-1 / EC-2) ─────────────────────────

@pytest.mark.asyncio
async def test_second_sdn_deploy_409_sdn_apply_busy():
    spec = StackSpec(name="webstack", resources=[_vm(bridge="v1")], networks=[_vnet()])
    row = {"id": 1, "name": "webstack"}
    sdn_lock = engine.get_sdn_apply_lock()
    await sdn_lock.acquire()   # simulate a parallel SDN deploy holding the lock
    try:
        with patch.object(ds, "_spec_of", AsyncMock(return_value=spec)):
            with pytest.raises(HTTPException) as ei:
                await ds.start_stack_job(row, "apply", PlanSummary(), _node(), 5, "alice")
        assert ei.value.status_code == 409
        assert ei.value.detail == "sdn_apply_busy"
    finally:
        sdn_lock.release()


# ── runner: _commit_sdn uses the tofu token (AC-LC-1) ─────────────────────────

@pytest.mark.asyncio
async def test_commit_sdn_calls_apply_sdn_with_tofu_token():
    fake_client = AsyncMock()
    fake_client.apply_sdn = AsyncMock()
    captured = {}

    def _make(*a, **kw):
        return fake_client

    with patch("backend.services.proxmox.ProxmoxClient", side_effect=_make), \
         patch("backend.services.proxmox.ProxmoxAuth",
               side_effect=lambda **kw: captured.update(kw) or kw):
        await runner._commit_sdn(_node())
    fake_client.apply_sdn.assert_awaited_once()
    assert captured["value"] == "root@pam!tofu"      # tofu token id
    assert captured["secret"] == "secret"
