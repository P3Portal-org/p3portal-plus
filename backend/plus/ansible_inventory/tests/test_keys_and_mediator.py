# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-83 Plus: keys_plus (lazy keypair + rotation) + mediator (resolve_guest_scope)."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import text

from backend.db.database import get_db, get_sync_engine, init_db
from backend.plus.ansible_inventory import keys_plus
from backend.plus.ansible_inventory.mediator import AnsibleInventoryPlusBehavior

pytestmark = pytest.mark.plus_only


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    from backend.core.config import settings
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))


@pytest_asyncio.fixture
async def db():
    await init_db()
    # Plus-Tabellen erstellen
    from backend.plus.ansible_inventory.models import plus_metadata as ai_meta
    from backend.plus.pools.models import plus_metadata as pools_meta
    eng = get_sync_engine()
    pools_meta.create_all(eng, checkfirst=True)
    ai_meta.create_all(eng, checkfirst=True)
    async with get_db() as s:
        await s.execute(text(
            "INSERT INTO nodes (id, name, url, proxmox_node, created_at) "
            "VALUES (1, 'n1', 'https://pve:8006', 'pve1', '2026-01-01')"
        ))
        await s.execute(text(
            "INSERT INTO pools (id, name, tags, cpu_quota, ram_quota_mb, disk_quota_gb, "
            "vm_count_quota, created_at, created_by) "
            "VALUES (7, 'team-a', '[]', 0, 0, 0, 0, '2026-01-01', 'admin')"
        ))
        await s.commit()
    yield


@pytest.mark.asyncio
async def test_pool_keypair_lazy_create_and_stable(db):
    priv1, pub1 = await keys_plus.get_or_create_pool_keypair(7)
    assert priv1.startswith("-----BEGIN OPENSSH PRIVATE KEY-----")
    assert pub1.startswith("ssh-ed25519 ")
    priv2, pub2 = await keys_plus.get_or_create_pool_keypair(7)
    assert pub1 == pub2  # stabil, nicht neu erzeugt


@pytest.mark.asyncio
async def test_pool_keypair_rotate_changes_key(db):
    _, pub1 = await keys_plus.get_or_create_pool_keypair(7)
    pub2 = await keys_plus.rotate_pool_keypair(7)
    assert pub2 != pub1


@pytest.mark.asyncio
async def test_global_keypair_singleton(db):
    priv, pub = await keys_plus.get_or_create_global_keypair()
    assert pub.startswith("ssh-ed25519 ")
    _, pub2 = await keys_plus.get_or_create_global_keypair()
    assert pub == pub2
    pub3 = await keys_plus.rotate_global_keypair()
    assert pub3 != pub


@pytest.mark.asyncio
async def test_private_key_never_in_public(db):
    priv, pub = await keys_plus.get_or_create_global_keypair()
    assert "PRIVATE KEY" not in pub


@pytest.mark.asyncio
async def test_get_injection_public_keys_extra(db):
    beh = AnsibleInventoryPlusBehavior()
    keys = await beh.get_injection_public_keys_extra(pool_id=7, global_opt_in=True)
    assert len(keys) == 2  # pool + global
    keys_pool_only = await beh.get_injection_public_keys_extra(pool_id=7, global_opt_in=False)
    assert len(keys_pool_only) == 1
    keys_none = await beh.get_injection_public_keys_extra(pool_id=None, global_opt_in=False)
    assert keys_none == []


@pytest.mark.asyncio
async def test_resolve_guest_scope_pool_member(db):
    # Pool-Mitglied (7) + Pool-Member-VM 201
    async with get_db() as s:
        await s.execute(text(
            "INSERT INTO pool_members (pool_id, resource_type, node_id, vmid, added_at, added_by) "
            "VALUES (7, 'vm', 1, 201, '2026-01-01', 'admin')"
        ))
        await s.commit()

    beh = AnsibleInventoryPlusBehavior()
    # get_pool_permissions liefert die PoolGrants → Mitglied von Pool 7
    from backend.core.plus_protocol import PoolGrant
    beh.get_pool_permissions = AsyncMock(return_value=[
        PoolGrant(pool_id=7, node_id=1, resource_type="vm")
    ])
    gs = await beh.resolve_guest_scope("pool", 7, user_id=5)
    assert gs is not None
    assert gs.scope == "pool"
    assert gs.private_key.startswith("-----BEGIN OPENSSH")
    assert (1, 201, "qemu") in gs.candidate_hosts


@pytest.mark.asyncio
async def test_resolve_guest_scope_pool_non_member_none(db):
    beh = AnsibleInventoryPlusBehavior()
    beh.get_pool_permissions = AsyncMock(return_value=[])
    gs = await beh.resolve_guest_scope("pool", 7, user_id=5)
    assert gs is None


@pytest.mark.asyncio
async def test_resolve_guest_scope_global_opt_in_hosts(db):
    async with get_db() as s:
        await s.execute(text(
            "INSERT INTO ansible_managed_hosts "
            "(portal_node_id, vmid, kind, ssh_managed, ansible_user, global_opt_in, "
            " host_origin, created_at, updated_at) "
            "VALUES (1, 301, 'qemu', 1, 'p3-ansible', 1, 'proxmox', '2026-01-01', '2026-01-01'), "
            "       (1, 302, 'lxc', 1, 'p3-ansible', 0, 'proxmox', '2026-01-01', '2026-01-01')"
        ))
        await s.commit()
    beh = AnsibleInventoryPlusBehavior()
    gs = await beh.resolve_guest_scope("global", None, user_id=5)
    assert gs is not None
    refs = set(gs.candidate_hosts)
    assert (1, 301, "qemu") in refs   # global_opt_in=1
    assert (1, 302, "lxc") not in refs  # global_opt_in=0
