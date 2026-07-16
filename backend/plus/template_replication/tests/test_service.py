# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-101: Service-Tests — Preflight-Status + Plan-Bau/Guards beim Start."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.plus.template_replication import service
from backend.plus.template_replication.schemas import ReplicateRequest, ReplicationTarget

from ._helpers import FakeResult, fake_client, make_get_db, node_row

pytestmark = pytest.mark.plus_only

TMPL_CONFIG = {"template": 1, "name": "deb12", "scsi0": "local-lvm:vm-100-disk-0,size=32G"}
STORAGES = {
    "pve1": [{"storage": "local-lvm", "type": "lvmthin", "shared": 0, "avail": 10, "total": 20}],
    "pve2": [{"storage": "local-lvm", "shared": 0}, {"storage": "ceph", "shared": 1}],
    "pve3": [{"storage": "local-lvm", "shared": 0}, {"storage": "ceph", "shared": 1}],
}


def _patch_common(monkeypatch, *, config=TMPL_CONFIG, storages=STORAGES, guard_count=0):
    monkeypatch.setattr(service, "get_node_for_proxmox_name", _async(node_row()))
    client = fake_client(config=config, storages_by_node=storages)
    monkeypatch.setattr(service, "_admin_client", lambda nr: (client, object()))
    monkeypatch.setattr(service, "get_db", make_get_db([FakeResult([{"c": guard_count}]), FakeResult()]))
    return client


def _async(value):
    async def _f(*_a, **_k):
        return value
    return _f


def _user():
    return SimpleNamespace(username="admin", role="admin", user_id=1)


# ── Preflight ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_preflight_local_source_lists_targets(monkeypatch):
    monkeypatch.setattr(service, "get_node_for_proxmox_name", _async(node_row()))
    client = fake_client(config=TMPL_CONFIG, storages_by_node=STORAGES)
    monkeypatch.setattr(service, "_admin_client", lambda nr: (client, object()))

    res = await service.preflight("pve1", 100)
    assert res.is_template is True
    assert res.source_shared is False
    assert res.source_storage == "local-lvm"
    assert res.single_node is False
    assert sorted(t.node for t in res.targets) == ["pve2", "pve3"]
    # ceph als shared markiert
    ceph = [s for t in res.targets for s in t.storages if s.name == "ceph"][0]
    assert ceph.shared is True


@pytest.mark.asyncio
async def test_preflight_shared_source_flags_no_op(monkeypatch):
    storages = {"pve1": [{"storage": "ceph", "shared": 1}], "pve2": [], "pve3": []}
    config = {"template": 1, "name": "deb12", "scsi0": "ceph:vm-100-disk-0,size=32G"}
    monkeypatch.setattr(service, "get_node_for_proxmox_name", _async(node_row()))
    client = fake_client(config=config, storages_by_node=storages)
    monkeypatch.setattr(service, "_admin_client", lambda nr: (client, object()))

    res = await service.preflight("pve1", 100)
    assert res.source_shared is True
    assert res.source_storage == "ceph"


@pytest.mark.asyncio
async def test_preflight_single_node(monkeypatch):
    # Echte Single-Node-Installation: keine zusätzlichen cluster_nodes.
    monkeypatch.setattr(service, "get_node_for_proxmox_name", _async(node_row(cluster_nodes=[])))
    client = fake_client(config=TMPL_CONFIG, storages_by_node=STORAGES)
    monkeypatch.setattr(service, "_admin_client", lambda nr: (client, object()))
    res = await service.preflight("pve1", 100)
    assert res.single_node is True
    assert res.targets == []


@pytest.mark.asyncio
async def test_preflight_includes_primary_node_as_target(monkeypatch):
    # Regression: Quelle ist ein Zusatz-Member (pve2) → die PRIMÄRE Node (pve1,
    # steht in proxmox_node, NICHT in cluster_nodes) muss als Ziel erscheinen.
    monkeypatch.setattr(service, "get_node_for_proxmox_name", _async(node_row()))
    client = fake_client(config=TMPL_CONFIG, storages_by_node=STORAGES)
    monkeypatch.setattr(service, "_admin_client", lambda nr: (client, object()))
    res = await service.preflight("pve2", 100)
    assert sorted(t.node for t in res.targets) == ["pve1", "pve3"]
    assert res.single_node is False


# ── Start / Plan-Bau ───────────────────────────────────────────────────────────

def _capture_plan(monkeypatch):
    captured = {}

    def _fake_run(*args, **_kw):
        captured["args"] = args
        return "coro"

    monkeypatch.setattr(service, "run_replication_job", _fake_run)
    monkeypatch.setattr(service.asyncio, "create_task", lambda _c: None)
    return captured


@pytest.mark.asyncio
async def test_start_shared_targets_collapse_to_one_op(monkeypatch):
    _patch_common(monkeypatch)
    captured = _capture_plan(monkeypatch)
    req = ReplicateRequest(source_node="pve1", source_vmid=100, targets=[
        ReplicationTarget(node="pve2", storage="ceph"),
        ReplicationTarget(node="pve3", storage="ceph"),
    ])
    res = await service.start_replication(_user(), req)
    assert res.type == "template_replication"
    plan = captured["args"][5]
    assert len(plan) == 1                     # N→1 (AC-STORAGE-3)
    assert plan[0]["kind"] == "shared"
    assert plan[0]["storage"] == "ceph"


@pytest.mark.asyncio
async def test_start_local_targets_one_op_each(monkeypatch):
    _patch_common(monkeypatch)
    captured = _capture_plan(monkeypatch)
    req = ReplicateRequest(source_node="pve1", source_vmid=100, targets=[
        ReplicationTarget(node="pve2", storage="local-lvm"),
        ReplicationTarget(node="pve3", storage="local-lvm"),
    ])
    await service.start_replication(_user(), req)
    plan = captured["args"][5]
    assert len(plan) == 2
    assert {op["node"] for op in plan} == {"pve2", "pve3"}
    assert all(op["kind"] == "local" for op in plan)


@pytest.mark.asyncio
async def test_start_accepts_primary_node_as_target(monkeypatch):
    # Regression: Quelle pve2, Ziel = primäre Node pve1 (nur in proxmox_node) → gültig.
    _patch_common(monkeypatch)
    captured = _capture_plan(monkeypatch)
    req = ReplicateRequest(source_node="pve2", source_vmid=100,
                           targets=[ReplicationTarget(node="pve1", storage="local-lvm")])
    await service.start_replication(_user(), req)
    plan = captured["args"][5]
    assert len(plan) == 1
    assert plan[0]["node"] == "pve1"
    assert plan[0]["kind"] == "local"


@pytest.mark.asyncio
async def test_start_rejects_non_template(monkeypatch):
    _patch_common(monkeypatch, config={"template": 0, "name": "vm", "scsi0": "local-lvm:vm-100-disk-0"})
    _capture_plan(monkeypatch)
    req = ReplicateRequest(source_node="pve1", source_vmid=100,
                           targets=[ReplicationTarget(node="pve2", storage="local-lvm")])
    with pytest.raises(HTTPException) as exc:
        await service.start_replication(_user(), req)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_start_rejects_shared_source_no_op(monkeypatch):
    storages = {"pve1": [{"storage": "ceph", "shared": 1}], "pve2": [{"storage": "ceph", "shared": 1}]}
    config = {"template": 1, "name": "deb12", "scsi0": "ceph:vm-100-disk-0,size=32G"}
    _patch_common(monkeypatch, config=config, storages=storages)
    _capture_plan(monkeypatch)
    req = ReplicateRequest(source_node="pve1", source_vmid=100,
                           targets=[ReplicationTarget(node="pve2", storage="ceph")])
    with pytest.raises(HTTPException) as exc:
        await service.start_replication(_user(), req)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_start_rejects_storage_not_on_node(monkeypatch):
    _patch_common(monkeypatch)
    _capture_plan(monkeypatch)
    req = ReplicateRequest(source_node="pve1", source_vmid=100,
                           targets=[ReplicationTarget(node="pve2", storage="does-not-exist")])
    with pytest.raises(HTTPException) as exc:
        await service.start_replication(_user(), req)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_start_rejects_target_outside_cluster(monkeypatch):
    _patch_common(monkeypatch)
    _capture_plan(monkeypatch)
    req = ReplicateRequest(source_node="pve1", source_vmid=100,
                           targets=[ReplicationTarget(node="other-cluster", storage="local-lvm")])
    with pytest.raises(HTTPException) as exc:
        await service.start_replication(_user(), req)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_start_concurrency_guard(monkeypatch):
    _patch_common(monkeypatch, guard_count=1)   # bereits ein Lauf aktiv
    _capture_plan(monkeypatch)
    req = ReplicateRequest(source_node="pve1", source_vmid=100,
                           targets=[ReplicationTarget(node="pve2", storage="local-lvm")])
    with pytest.raises(HTTPException) as exc:
        await service.start_replication(_user(), req)
    assert exc.value.status_code == 409


# ── Disk-Storage-Parser ─────────────────────────────────────────────────────────

def test_first_disk_storage_skips_cdrom():
    cfg = {"ide2": "local:iso/x.iso,media=cdrom", "scsi0": "local-lvm:vm-100-disk-0,size=32G"}
    assert service._first_disk_storage(cfg) == "local-lvm"


def test_first_disk_storage_none_when_no_disk():
    assert service._first_disk_storage({"name": "x", "cores": 2}) is None


# ── Auto-VMID-Bereich (Template-/Packer-Range) ──────────────────────────────────

@pytest.mark.asyncio
async def test_next_vmid_auto_uses_configured_range():
    from unittest.mock import AsyncMock
    client = SimpleNamespace(get_next_vmid=AsyncMock(return_value=9010))
    got = await service._next_vmid(client, object(), None, 9000, 9100)
    assert got == 9010
    # Auto-Zweig muss GENAU den konfigurierten Template-Bereich weiterreichen.
    args = client.get_next_vmid.await_args.args
    assert args[1] == 9000 and args[2] == 9100


@pytest.mark.asyncio
async def test_next_vmid_provided_rejects_taken():
    from unittest.mock import AsyncMock
    # get_next_vmid(provided,provided) liefert nicht die gewünschte ID → belegt.
    client = SimpleNamespace(get_next_vmid=AsyncMock(return_value=9999))
    with pytest.raises(ValueError):
        await service._next_vmid(client, object(), 9001, 9000, 9100)
