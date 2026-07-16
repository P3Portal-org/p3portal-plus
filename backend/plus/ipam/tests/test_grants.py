# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-42 Phase 2: Netz-Freigaben + Sichtbarkeits-Filter (strict AN/AUS, Admin)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.plus.ipam import config_service, grants_service
from backend.plus.ipam.schemas import NetworkGrantRequest
from backend.plus.ipam.tests.conftest import _make_pool

pytestmark = pytest.mark.plus_only


def _user(uid=2, role="operator"):
    return SimpleNamespace(user_id=uid, role=role, auth_type="local", username="bob")


async def _grant_bridge(name="vmbr0", node="pve", uid=2):
    return await grants_service.create_grant(
        NetworkGrantRequest(kind="bridge", network_name=name, node=node,
                            grantee_kind="user", grantee_id=uid),
        created_by="admin",
    )


@pytest.mark.asyncio
async def test_grant_crud_idempotent(db):
    g1 = await _grant_bridge()
    assert g1.network_name == "vmbr0" and g1.grantee_kind == "user"
    g2 = await _grant_bridge()  # idempotent
    assert g1.id == g2.id
    assert len(await grants_service.list_grants()) == 1
    assert await grants_service.delete_grant(g1.id) is True
    assert await grants_service.list_grants() == []


@pytest.mark.asyncio
async def test_filter_networks_disabled_by_default(db):
    # strict AUS (Default) → alle Netze sichtbar (kein Bruch)
    bridges, vnets = await grants_service.filter_networks(
        _user(), ["vmbr0", "vmbr1"], ["guests"], "pve"
    )
    assert bridges == ["vmbr0", "vmbr1"] and vnets == ["guests"]


@pytest.mark.asyncio
async def test_filter_networks_strict(db):
    await config_service.update_config(global_enabled=True, strict_network_visibility=True,
                                       updated_by="admin")
    await _grant_bridge("vmbr0", "pve", uid=2)
    # Nicht-Admin sieht nur freigegebene Bridge
    bridges, vnets = await grants_service.filter_networks(
        _user(), ["vmbr0", "vmbr1"], ["guests"], "pve"
    )
    assert bridges == ["vmbr0"] and vnets == []
    # Admin sieht immer alles
    ab, av = await grants_service.filter_networks(
        _user(role="admin"), ["vmbr0", "vmbr1"], ["guests"], "pve"
    )
    assert ab == ["vmbr0", "vmbr1"] and av == ["guests"]


@pytest.mark.asyncio
async def test_filter_networks_no_grant_empty(db):
    await config_service.update_config(global_enabled=True, strict_network_visibility=True,
                                       updated_by="admin")
    bridges, vnets = await grants_service.filter_networks(
        _user(), ["vmbr0"], ["guests"], "pve"
    )
    assert bridges == [] and vnets == []


@pytest.mark.asyncio
async def test_strict_ignored_when_global_off(db):
    # strict AN aber global AUS → Filter wirkungslos (is_strict_visibility gated auf global)
    await config_service.update_config(global_enabled=False, strict_network_visibility=True,
                                       updated_by="admin")
    bridges, _ = await grants_service.filter_networks(_user(), ["vmbr0"], [], "pve")
    assert bridges == ["vmbr0"]


@pytest.mark.asyncio
async def test_filter_pools_inherits_grants(db):
    await config_service.update_config(global_enabled=True, strict_network_visibility=True,
                                       updated_by="admin")
    pid0 = await _make_pool(network_name="vmbr0", cidr="192.168.2.0/24")
    await _make_pool(network_name="vmbr1", cidr="10.0.0.0/24", gateway=None)
    await _grant_bridge("vmbr0", "pve", uid=2)
    from backend.features.ipam import service as core_pools
    all_pools = await core_pools.list_pools()
    visible = await grants_service.filter_pools(_user(), all_pools)
    assert [p.id for p in visible] == [pid0]


@pytest.mark.asyncio
async def test_visible_keys_union_user_and_group(db, monkeypatch):
    # direkter User-Grant + Gruppen-Grant → Vereinigung
    await grants_service.create_grant(
        NetworkGrantRequest(kind="bridge", network_name="vmbr0", node="pve",
                            grantee_kind="user", grantee_id=2), "admin")
    await grants_service.create_grant(
        NetworkGrantRequest(kind="vnet", network_name="guests",
                            grantee_kind="group", grantee_id=7), "admin")
    # user 2 ist Mitglied von Gruppe 7 (Mitgliedschaft gemockt – FK-Setup irrelevant)
    from unittest.mock import AsyncMock
    monkeypatch.setattr(grants_service, "_user_group_ids", AsyncMock(return_value=[7]))
    keys = await grants_service.visible_network_keys(_user())
    assert ("bridge", "vmbr0", "pve") in keys
    assert ("vnet", "guests", "") in keys
