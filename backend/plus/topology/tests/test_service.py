# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-75: topology service tests — compute build, RBAC single-source,
network aggregation, multi-installation unreachable."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.deps import CurrentUser
from backend.models.cluster import NodeInfo, VmInfo
from backend.plus.topology import service


def _user(role="admin"):
    return CurrentUser(username="admin", auth_type="local", role=role, user_id=1)


def _node(node, pnid=1, status="online", maxcpu=8, maxmem=16_000_000_000, maxdisk=500_000_000_000):
    n = NodeInfo(node=node, status=status, maxcpu=maxcpu, maxmem=maxmem, maxdisk=maxdisk)
    n.portal_node_id = pnid
    return n


def _vm(vmid, node="pve1", pnid=1, vm_type="qemu", status="running",
        name=None, template=0, cpu=0.4, maxcpu=4, mem=2_000_000_000,
        maxmem=4_000_000_000, disk=0, maxdisk=0):
    v = VmInfo(
        vmid=vmid, name=name or f"guest-{vmid}", type=vm_type, status=status,
        node=node, cpu=cpu, maxcpu=maxcpu, mem=mem, maxmem=maxmem,
        disk=disk, maxdisk=maxdisk, template=template,
    )
    v.portal_node_id = pnid
    return v


def _patch_compute(monkeypatch, nodes, guests, inst_names,
                   stack_map=None, stack_names=None, ansible_map=None):
    monkeypatch.setattr(service, "fetch_nodes", AsyncMock(return_value=nodes))
    monkeypatch.setattr(
        service, "fetch_visible_vm_resources", AsyncMock(return_value=guests)
    )
    monkeypatch.setattr(service, "_installation_meta", AsyncMock(return_value=inst_names))
    monkeypatch.setattr(
        service, "_bulk_stack_map",
        AsyncMock(return_value=(stack_map or {}, stack_names or [])),
    )
    monkeypatch.setattr(
        service, "_bulk_ansible_states", AsyncMock(return_value=ansible_map or {})
    )


# ── Compute view ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_compute_groups_by_installation_and_ids(monkeypatch):
    nodes = [_node("pve1", pnid=1), _node("pveB", pnid=2)]
    guests = [
        _vm(101, node="pve1", pnid=1),
        _vm(201, node="pve1", pnid=1, vm_type="lxc", status="stopped"),
        _vm(101, node="pveB", pnid=2),  # same VMID, different installation
    ]
    _patch_compute(monkeypatch, nodes, guests, {1: "prod", 2: "lab"})

    resp = await service.build_cluster_topology(_user())

    assert {i.id for i in resp.installations} == {"inst1", "inst2"}
    assert {i.name for i in resp.installations} == {"prod", "lab"}
    inst1 = next(i for i in resp.installations if i.id == "inst1")
    assert inst1.nodes[0].id == "inst1-node-pve1"
    assert inst1.nodes[0].node == "pve1"
    gids = {g.id for g in inst1.guests}
    assert gids == {"inst1-vm-101", "inst1-lxc-201"}
    # Same VMID 101 in inst2 must not collide (EC-10).
    inst2 = next(i for i in resp.installations if i.id == "inst2")
    assert inst2.guests[0].id == "inst2-vm-101"


@pytest.mark.asyncio
async def test_compute_stats_and_type_mapping(monkeypatch):
    nodes = [_node("pve1", pnid=1)]
    guests = [
        _vm(101, status="running"),
        _vm(102, status="stopped"),
        _vm(201, vm_type="lxc", status="running"),
    ]
    _patch_compute(monkeypatch, nodes, guests, {1: "prod"},
                   stack_map={(1, 101): "web"}, stack_names=["web", "db"])

    resp = await service.build_cluster_topology(_user())

    assert resp.stats.installations == 1
    assert resp.stats.nodes == 1
    assert resp.stats.vms == 2  # qemu → vm
    assert resp.stats.lxcs == 1
    assert resp.stats.running == 2
    assert resp.stats.stack_managed == 1
    assert resp.stacks == ["web", "db"]
    g101 = next(g for i in resp.installations for g in i.guests if g.vmid == 101 and g.type == "vm")
    assert g101.managed_by_stack == "web"
    g201 = next(g for i in resp.installations for g in i.guests if g.type == "lxc")
    assert g201.managed_by_stack is None


@pytest.mark.asyncio
async def test_compute_badges_ansible_and_template(monkeypatch):
    nodes = [_node("pve1", pnid=1)]
    guests = [_vm(101), _vm(900, template=1, name="ubuntu-tmpl", status="stopped")]
    _patch_compute(monkeypatch, nodes, guests, {1: "prod"},
                   ansible_map={(1, 101, "qemu"): True})

    resp = await service.build_cluster_topology(_user())
    g101 = next(g for i in resp.installations for g in i.guests if g.vmid == 101)
    tmpl = next(g for i in resp.installations for g in i.guests if g.vmid == 900)
    assert g101.ssh_managed is True
    assert g101.is_template is False
    assert tmpl.is_template is True
    assert tmpl.ssh_managed is False


@pytest.mark.asyncio
async def test_compute_rbac_single_source(monkeypatch):
    """Topology shows exactly what fetch_visible_vm_resources returns — a guest
    filtered out by RBAC never appears (AC-RBAC-4)."""
    nodes = [_node("pve1", pnid=1)]
    visible = [_vm(101)]  # 102 hidden by RBAC → not in this list
    _patch_compute(monkeypatch, nodes, visible, {1: "prod"})

    resp = await service.build_cluster_topology(_user(role="viewer"))
    all_vmids = {g.vmid for i in resp.installations for g in i.guests}
    assert all_vmids == {101}
    # with_ip=True: the compute view shows guest IPs (single IP source).
    service.fetch_visible_vm_resources.assert_awaited_once()
    _, kwargs = service.fetch_visible_vm_resources.await_args
    assert kwargs.get("with_ip") is True


@pytest.mark.asyncio
async def test_compute_unreachable_installation(monkeypatch):
    # inst2 is configured but returned no nodes → unreachable (EC-16).
    nodes = [_node("pve1", pnid=1)]
    guests = [_vm(101, pnid=1)]
    _patch_compute(monkeypatch, nodes, guests, {1: "prod", 2: "lab"})

    resp = await service.build_cluster_topology(_user())
    inst2 = next(i for i in resp.installations if i.id == "inst2")
    assert inst2.unreachable is True
    assert inst2.nodes == []
    inst1 = next(i for i in resp.installations if i.id == "inst1")
    assert inst1.unreachable is False


@pytest.mark.asyncio
async def test_compute_node_with_zero_guests(monkeypatch):
    # EC-9: a node with no guests still shows up.
    nodes = [_node("pve1", pnid=1)]
    _patch_compute(monkeypatch, nodes, [], {1: "prod"})
    resp = await service.build_cluster_topology(_user())
    inst1 = next(i for i in resp.installations if i.id == "inst1")
    assert len(inst1.nodes) == 1
    assert inst1.guests == []
    assert inst1.unreachable is False


# ── Network view ──────────────────────────────────────────────────────────────

def _mock_client(vnets=None, ifaces=None, configs=None):
    client = SimpleNamespace()
    client.get_sdn_vnets = AsyncMock(return_value=vnets or [])
    client.get_node_network_interfaces = AsyncMock(return_value=ifaces or [])

    async def _bulk(auth, items, concurrency=10):
        # {(node, vmid): (config, None)} — config from the configs map, else {}.
        return {
            (node, vmid): ((configs or {}).get(vmid, {}), None)
            for (node, vmid, _vm_type) in items
        }

    client.get_vm_configs_bulk = AsyncMock(side_effect=_bulk)
    return client


@pytest.mark.asyncio
async def test_network_bridges_vnets_stack_and_connectivity(monkeypatch):
    nodes = [_node("pve1", pnid=1)]
    guests = [
        _vm(101, node="pve1", pnid=1),
        _vm(201, node="pve1", pnid=1, vm_type="lxc"),
    ]
    monkeypatch.setattr(service, "fetch_nodes", AsyncMock(return_value=nodes))
    monkeypatch.setattr(
        service, "fetch_visible_vm_resources", AsyncMock(return_value=guests)
    )
    monkeypatch.setattr(
        service, "_collect_stack_bridges",
        AsyncMock(return_value={("pve1", "vmbr1"): "web"}),
    )
    monkeypatch.setattr(
        "backend.services.nodes_service.list_nodes",
        AsyncMock(return_value=[SimpleNamespace(id=1, name="prod")]),
    )
    client = _mock_client(
        vnets=[{"vnet": "vnet5", "tag": 100}],
        ifaces=[
            {"iface": "vmbr0", "type": "bridge"},
            {"iface": "vmbr1", "type": "bridge"},
            {"iface": "eth0", "type": "eth"},          # not a bridge
            {"iface": "vmbr0.100", "type": "vlan"},    # VLAN sub-iface, not a bridge
        ],
        configs={
            101: {"net0": "virtio=AA:BB,bridge=vmbr0", "net1": "virtio=CC:DD,bridge=vnet5"},
            201: {"net0": "name=eth0,bridge=vmbr9"},   # unknown bridge (EC-18)
        },
    )
    monkeypatch.setattr(
        service, "_resolve_installation_auth", lambda row: (client, object())
    )

    resp = await service.build_network_topology(_user())

    nets = {n.id: n for n in resp.networks}
    # SDN VNet (cluster-wide, vlan tag)
    assert "inst1-sdn-vnet5" in nets
    assert nets["inst1-sdn-vnet5"].kind == "sdn_vnet"
    assert nets["inst1-sdn-vnet5"].scope == "cluster"
    assert nets["inst1-sdn-vnet5"].vlan_tag == 100
    # Node bridge + stack bridge
    assert nets["inst1-pve1-vmbr0"].kind == "node_bridge"
    assert nets["inst1-pve1-vmbr1"].kind == "stack_bridge"
    assert nets["inst1-pve1-vmbr1"].owning_stack == "web"
    # eth0 / VLAN sub-iface are NOT network nodes
    assert not any(n.label == "eth0" for n in resp.networks)
    assert not any(n.label == "vmbr0.100" for n in resp.networks)
    # Unknown placeholder for vmbr9 (EC-18)
    assert nets["inst1-pve1-vmbr9"].kind == "unknown"

    edges = {(e.guest_id, e.network_id) for e in resp.edges_conn}
    assert ("inst1-vm-101", "inst1-pve1-vmbr0") in edges
    assert ("inst1-vm-101", "inst1-sdn-vnet5") in edges  # VNet match priority
    assert ("inst1-lxc-201", "inst1-pve1-vmbr9") in edges


@pytest.mark.asyncio
async def test_network_unreachable_when_no_token(monkeypatch):
    nodes = [_node("pve1", pnid=2)]
    guests = [_vm(101, node="pve1", pnid=2)]
    monkeypatch.setattr(service, "fetch_nodes", AsyncMock(return_value=nodes))
    monkeypatch.setattr(
        service, "fetch_visible_vm_resources", AsyncMock(return_value=guests)
    )
    monkeypatch.setattr(service, "_collect_stack_bridges", AsyncMock(return_value={}))
    monkeypatch.setattr(
        "backend.services.nodes_service.list_nodes",
        AsyncMock(return_value=[SimpleNamespace(id=2, name="lab")]),
    )
    # No token available → resolver returns None.
    monkeypatch.setattr(service, "_resolve_installation_auth", lambda row: None)

    resp = await service.build_network_topology(_user())
    assert resp.networks == []
    assert resp.edges_conn == []
    assert resp.unreachable_installations == ["inst2"]


@pytest.mark.asyncio
async def test_network_sdn_unavailable_is_silent(monkeypatch):
    # EC-17: SDN not configured → vnet call raises → silently skipped, bridges OK.
    nodes = [_node("pve1", pnid=1)]
    guests = [_vm(101, node="pve1", pnid=1)]
    monkeypatch.setattr(service, "fetch_nodes", AsyncMock(return_value=nodes))
    monkeypatch.setattr(
        service, "fetch_visible_vm_resources", AsyncMock(return_value=guests)
    )
    monkeypatch.setattr(service, "_collect_stack_bridges", AsyncMock(return_value={}))
    monkeypatch.setattr(
        "backend.services.nodes_service.list_nodes",
        AsyncMock(return_value=[SimpleNamespace(id=1, name="prod")]),
    )
    client = _mock_client(
        ifaces=[{"iface": "vmbr0", "type": "bridge"}],
        configs={101: {"net0": "virtio=AA,bridge=vmbr0"}},
    )
    client.get_sdn_vnets = AsyncMock(side_effect=RuntimeError("no sdn"))
    monkeypatch.setattr(
        service, "_resolve_installation_auth", lambda row: (client, object())
    )

    resp = await service.build_network_topology(_user())
    assert {n.id for n in resp.networks} == {"inst1-pve1-vmbr0"}
    assert ("inst1-vm-101", "inst1-pve1-vmbr0") in {
        (e.guest_id, e.network_id) for e in resp.edges_conn
    }


@pytest.mark.asyncio
async def test_network_diag_config_failure_reports_reason(monkeypatch):
    """PVE1-Szenario: Bridges erscheinen, aber jeder per-VM-Config-Abruf liefert
    403 → keine Konnektivitäts-Kanten; die Diagnose meldet guests_failed + Grund.
    """
    nodes = [_node("pve1", pnid=1)]
    guests = [_vm(101, node="pve1", pnid=1), _vm(102, node="pve1", pnid=1)]
    monkeypatch.setattr(service, "fetch_nodes", AsyncMock(return_value=nodes))
    monkeypatch.setattr(
        service, "fetch_visible_vm_resources", AsyncMock(return_value=guests)
    )
    monkeypatch.setattr(service, "_collect_stack_bridges", AsyncMock(return_value={}))
    monkeypatch.setattr(service, "_installation_meta", AsyncMock(return_value={1: "prod"}))
    monkeypatch.setattr(
        "backend.services.nodes_service.list_nodes",
        AsyncMock(return_value=[SimpleNamespace(id=1, name="prod")]),
    )
    client = _mock_client(ifaces=[{"iface": "vmbr0", "type": "bridge"}])

    async def _bulk_403(auth, items, concurrency=10):
        return {(node, vmid): (None, "403") for (node, vmid, _t) in items}

    client.get_vm_configs_bulk = AsyncMock(side_effect=_bulk_403)
    monkeypatch.setattr(
        service, "_resolve_installation_auth", lambda row: (client, object())
    )

    resp = await service.build_network_topology(_user())

    # Bridge node shows, but NO connectivity edges (the PVE1 symptom).
    assert {n.id for n in resp.networks} == {"inst1-pve1-vmbr0"}
    assert resp.edges_conn == []
    # Diagnostics surface the cause.
    assert len(resp.diagnostics) == 1
    diag = resp.diagnostics[0]
    assert diag.installation_id == "inst1"
    assert diag.name == "prod"
    assert diag.guests_total == 2
    assert diag.guests_ok == 0
    assert diag.guests_failed == 2
    assert diag.edges_found == 0
    assert "403" in diag.sample_errors


@pytest.mark.asyncio
async def test_network_includes_bridge_address(monkeypatch):
    nodes = [_node("pve1", pnid=1)]
    monkeypatch.setattr(service, "fetch_nodes", AsyncMock(return_value=nodes))
    monkeypatch.setattr(
        service, "fetch_visible_vm_resources", AsyncMock(return_value=[_vm(101, node="pve1", pnid=1)])
    )
    monkeypatch.setattr(service, "_collect_stack_bridges", AsyncMock(return_value={}))
    monkeypatch.setattr(service, "_installation_meta", AsyncMock(return_value={1: "prod"}))
    monkeypatch.setattr(
        "backend.services.nodes_service.list_nodes",
        AsyncMock(return_value=[SimpleNamespace(id=1, name="prod")]),
    )
    client = _mock_client(
        ifaces=[{"iface": "vmbr0", "type": "bridge", "cidr": "192.168.2.1/24"}],
        configs={101: {"net0": "virtio=AA,bridge=vmbr0"}},
    )
    monkeypatch.setattr(
        service, "_resolve_installation_auth", lambda row: (client, object())
    )

    resp = await service.build_network_topology(_user())
    nets = {n.id: n for n in resp.networks}
    assert nets["inst1-pve1-vmbr0"].address == "192.168.2.1/24"   # bridge IP


@pytest.mark.asyncio
async def test_compute_includes_guest_ip(monkeypatch):
    vm = _vm(101, node="pve1", pnid=1)
    vm.ip = "192.168.2.50"
    _patch_compute(monkeypatch, [_node("pve1", pnid=1)], [vm], {1: "prod"})
    resp = await service.build_cluster_topology(_user())
    g = resp.installations[0].guests[0]
    assert g.ip == "192.168.2.50"   # guest IP from the /cluster endpoint (with_ip=True)


@pytest.mark.asyncio
async def test_network_diag_no_token(monkeypatch):
    """Unreachable installation (no read token) → diagnostics flag 'no_read_token'."""
    nodes = [_node("pve1", pnid=2)]
    guests = [_vm(101, node="pve1", pnid=2)]
    monkeypatch.setattr(service, "fetch_nodes", AsyncMock(return_value=nodes))
    monkeypatch.setattr(
        service, "fetch_visible_vm_resources", AsyncMock(return_value=guests)
    )
    monkeypatch.setattr(service, "_collect_stack_bridges", AsyncMock(return_value={}))
    monkeypatch.setattr(service, "_installation_meta", AsyncMock(return_value={2: "lab"}))
    monkeypatch.setattr(
        "backend.services.nodes_service.list_nodes",
        AsyncMock(return_value=[SimpleNamespace(id=2, name="lab")]),
    )
    monkeypatch.setattr(service, "_resolve_installation_auth", lambda row: None)

    resp = await service.build_network_topology(_user())
    assert resp.unreachable_installations == ["inst2"]
    assert len(resp.diagnostics) == 1
    assert resp.diagnostics[0].sample_errors == ["no_read_token"]
