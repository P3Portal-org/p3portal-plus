# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-76 Phase 2b: deploy_service gates (RBAC/Quota/Token/Installation/Plan-Token)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from backend.core.plus_protocol import QuotaResult
from backend.plus.stacks import deploy_service as ds
from backend.plus.stacks.schemas import PlanSummary, StackSpec, VMResource

pytestmark = pytest.mark.plus_only


def _node(node_id=1, tofu=True):
    from backend.services.nodes_service import NodeRow
    return NodeRow(
        id=node_id, name="pve", url="https://pve:8006", proxmox_node="pve",
        verify_ssl=False, token_id="", token_secret="",
        viewer_token_id="v", viewer_token_secret="s",
        operator_token_id="", operator_token_secret="",
        admin_token_id="", admin_token_secret="",
        packer_token_id="", packer_token_secret="",
        tofu_token_id="root@pam!tofu" if tofu else "",
        tofu_token_secret="secret" if tofu else "",
        is_default=True, created_at="2026-01-01", created_by="admin",
    )


def _spec(pool=None, count=2, cores=2, memory=2048, disk=32):
    return StackSpec(name="webstack", resources=[
        VMResource(name="web", node="pve", template="deb12",
                   count=count, cores=cores, memory=memory, disk=disk, pool=pool),
    ])


# ── resolve_target_node (Ein-Installation + Token-Pflicht) ────────────────────

@pytest.mark.asyncio
async def test_resolve_target_node_happy():
    with patch.object(ds, "get_node_for_proxmox_name", AsyncMock(return_value=_node())):
        node = await ds.resolve_target_node(_spec())
    assert node.id == 1


@pytest.mark.asyncio
async def test_resolve_target_node_unresolvable_422():
    with patch.object(ds, "get_node_for_proxmox_name", AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as ei:
            await ds.resolve_target_node(_spec())
    assert ei.value.status_code == 422
    assert "node_not_resolvable" in ei.value.detail


@pytest.mark.asyncio
async def test_resolve_target_node_missing_token_400():
    with patch.object(ds, "get_node_for_proxmox_name", AsyncMock(return_value=_node(tofu=False))):
        with pytest.raises(HTTPException) as ei:
            await ds.resolve_target_node(_spec())
    assert ei.value.status_code == 400
    assert "node_not_stack_deploy_capable" in ei.value.detail


@pytest.mark.asyncio
async def test_resolve_target_node_multiple_installations_422():
    spec = StackSpec(name="xyz", resources=[
        VMResource(name="a", node="pveA", template="t"),
        VMResource(name="b", node="pveB", template="t"),
    ])

    async def _lookup(name):
        return _node(node_id=1) if name == "pveA" else _node(node_id=2)

    with patch.object(ds, "get_node_for_proxmox_name", AsyncMock(side_effect=_lookup)):
        with pytest.raises(HTTPException) as ei:
            await ds.resolve_target_node(spec)
    assert ei.value.status_code == 422
    assert ei.value.detail == "multiple_installations_not_supported"


# ── resource totals ───────────────────────────────────────────────────────────

def test_resource_totals_sums_count():
    vm_count, cores, ram, disk = ds._resource_totals(_spec(count=3, cores=2, memory=1024, disk=10))
    assert (vm_count, cores, ram, disk) == (3, 6, 3072, 30)


# ── RBAC / Quota gate ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_assert_deploy_allowed_rbac_403():
    row = {"id": 1, "owner_user_id": 99}
    with patch.object(ds, "can_deploy_stack", AsyncMock(return_value=False)), \
         patch.object(ds, "write_audit_log", AsyncMock()):
        with pytest.raises(HTTPException) as ei:
            await ds.assert_deploy_allowed(row, _spec(), _node(), "operator", 5, "bob")
    assert ei.value.status_code == 403


@pytest.mark.asyncio
async def test_assert_deploy_allowed_quota_412():
    row = {"id": 1, "owner_user_id": 5}
    quota = QuotaResult(allowed=False, exceeded=["cpu_cores"])
    with patch.object(ds, "can_deploy_stack", AsyncMock(return_value=True)), \
         patch.object(ds, "_resolve_pool_id", AsyncMock(return_value=7)), \
         patch.object(ds, "write_audit_log", AsyncMock()), \
         patch("backend.plus.stacks.deploy_service.plus_behavior") as pb:
        pb.check_pool_quota_bulk = AsyncMock(return_value=quota)
        with pytest.raises(HTTPException) as ei:
            await ds.assert_deploy_allowed(row, _spec(pool="mypool"), _node(), "operator", 5, "bob")
    assert ei.value.status_code == 412


@pytest.mark.asyncio
async def test_assert_deploy_allowed_ok_no_pool():
    row = {"id": 1, "owner_user_id": 5}
    with patch.object(ds, "can_deploy_stack", AsyncMock(return_value=True)):
        # no pool → no quota check, returns None without raising
        await ds.assert_deploy_allowed(row, _spec(), _node(), "operator", 5, "bob")


# ── plan-token registry ───────────────────────────────────────────────────────

def test_consume_plan_token_invalid():
    with pytest.raises(HTTPException) as ei:
        ds.consume_plan_token("nope", 1, "etag", "apply")
    assert ei.value.status_code == 400


def test_consume_plan_token_etag_mismatch_409(tmp_path, monkeypatch):
    from backend.core.config import settings
    monkeypatch.setattr(settings, "data_dir", str(tmp_path), raising=False)
    summary = PlanSummary(create=2)
    token = ds._make_plan_token(1, "old-etag", "apply", summary, 1)
    with pytest.raises(HTTPException) as ei:
        ds.consume_plan_token(token, 1, "new-etag", "apply")
    assert ei.value.status_code == 409
    assert ei.value.detail == "stack_definition_changed"


def test_consume_plan_token_expired_409(tmp_path, monkeypatch):
    from backend.core.config import settings
    monkeypatch.setattr(settings, "data_dir", str(tmp_path), raising=False)
    token = ds._make_plan_token(1, "etag", "apply", PlanSummary(), 1)
    ds._PLAN_TOKENS[token]["expires_at"] = datetime.now(timezone.utc) - timedelta(minutes=1)
    with pytest.raises(HTTPException) as ei:
        ds.consume_plan_token(token, 1, "etag", "apply")
    assert ei.value.status_code == 409


def test_consume_plan_token_happy(tmp_path, monkeypatch):
    from backend.core.config import settings
    monkeypatch.setattr(settings, "data_dir", str(tmp_path), raising=False)
    # planfile must exist
    wd = ds.engine.stack_working_dir("1")
    (wd / "plan.tfplan").write_text("binary")
    token = ds._make_plan_token(1, "etag", "apply", PlanSummary(create=1), 1)
    entry = ds.consume_plan_token(token, 1, "etag", "apply")
    assert entry["summary"].create == 1
    assert token not in ds._PLAN_TOKENS  # popped


# ── explicit VMID availability (Inbetriebnahme: belegte ID → klarer 422) ──────

def test_wanted_explicit_vmids_count_offset():
    spec = StackSpec(name="webstack", resources=[
        VMResource(name="web", node="pve", template="deb12", vmid=250, count=3),
        VMResource(name="db", node="pve", template="deb12"),  # no vmid → skipped
    ])
    assert ds._wanted_explicit_vmids(spec) == {250: "web-1", 251: "web-2", 252: "web-3"}


@pytest.mark.asyncio
async def test_assert_vmids_free_no_pins_skips_cluster_call():
    # _spec() pins no VMID → returns immediately, no ProxmoxClient needed
    with patch("backend.services.proxmox.ProxmoxClient") as PClient:
        await ds.assert_explicit_vmids_free(1, _node(), _spec())
        PClient.assert_not_called()


@pytest.mark.asyncio
async def test_assert_vmids_free_taken_raises_422():
    spec = StackSpec(name="webstack", resources=[
        VMResource(name="web", node="pve", template="deb12", vmid=101)])
    client = type("C", (), {"get_cluster_resources_v2": AsyncMock(return_value=[{"vmid": 101}])})()
    with patch("backend.services.proxmox.ProxmoxClient", return_value=client), \
         patch("backend.plus.stacks.deployments.list_deployed_resources", AsyncMock(return_value=[])):
        with pytest.raises(HTTPException) as ei:
            await ds.assert_explicit_vmids_free(1, _node(), spec)
    assert ei.value.status_code == 422
    assert ei.value.detail["error"] == "vmid_taken"
    assert ei.value.detail["taken"] == [101]
    # 101 taken → suggestion moves it to the next free (102)
    assert ei.value.detail["suggestions"] == [
        {"index": 0, "name": "web", "old_vmid": 101, "new_vmid": 102}
    ]


def test_suggest_free_vmids_count_aware_and_no_self_clash():
    # web (count 2) pinned at 101 with 101,102 taken → needs a 2-wide free window;
    # db pinned at 103 (free) keeps its slot, so web must skip past it.
    spec = StackSpec(name="stk", resources=[
        VMResource(name="web", node="pve", template="t", vmid=101, count=2),
        VMResource(name="db", node="pve", template="t", vmid=103),
    ])
    out = ds.suggest_free_vmids(spec, occupied={101, 102})
    # db keeps 103; web needs 104,105 (106 onward also fine, but 104 is first free pair
    # not overlapping reserved {103})
    assert {s["name"]: s["new_vmid"] for s in out} == {"web": 104}


@pytest.mark.asyncio
async def test_assert_vmids_free_own_vmid_excluded():
    # VMID 101 is taken but already owned by THIS stack → re-deploy must pass
    spec = StackSpec(name="webstack", resources=[
        VMResource(name="web", node="pve", template="deb12", vmid=101)])
    client = type("C", (), {"get_cluster_resources_v2": AsyncMock(return_value=[{"vmid": 101}])})()
    with patch("backend.services.proxmox.ProxmoxClient", return_value=client), \
         patch("backend.plus.stacks.deployments.list_deployed_resources",
               AsyncMock(return_value=[{"vmid": 101}])):
        await ds.assert_explicit_vmids_free(1, _node(), spec)  # no raise
