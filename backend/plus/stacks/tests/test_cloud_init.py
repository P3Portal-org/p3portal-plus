# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-85: Stacks Cloud-Init-Login – store, resolver, transpile mapping, gates.

Covers AC-STORE, AC-ACT, AC-FIELDS, AC-KEYS, AC-IP, AC-TRANSPILE, AC-SEC and the
edge cases (EC-1/2/3/4/5/6/8). Transpile/schema parts are pure; the store/resolve
parts use the temp DB via the shared ``stack_db`` fixture (conftest).
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import text

from backend.core.security import create_access_token
from backend.db.database import get_db, get_sync_engine, init_db
from backend.plus.stacks import cloud_init, models as m, service
from backend.plus.stacks.cloud_init import CloudInitResolved
from backend.plus.stacks.router import router
from backend.plus.stacks.schemas import (
    CloudInitBlock,
    CloudInitConfigRequest,
    StackSpec,
    VMResource,
)
from backend.plus.stacks.transpile import stack_to_tfjson

pytestmark = pytest.mark.plus_only

_EXAMPLE_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITESTKEY user@host"


# ════════════════════════════════════════════════════════════════════════════
# Pure: transpile initialization{} mapping (AC-TRANSPILE / AC-IP-2 / D)
# ════════════════════════════════════════════════════════════════════════════

def _spec(**res) -> StackSpec:
    base = dict(name="web", node="pve", template="deb12")
    base.update(res)
    return StackSpec(name="webstack", resources=[VMResource(**base)])


def _vmblock(out, name="web"):
    return out["resource"]["proxmox_virtual_environment_vm"][name]


def test_no_cloudinit_is_byte_identical():
    """AC-TRANS-1: without cloud-init the output has no initialization block."""
    out_none = stack_to_tfjson(_spec(), {"deb12": 9000})
    out_empty = stack_to_tfjson(_spec(), {"deb12": 9000}, cloudinit={})
    assert out_none == out_empty
    assert "initialization" not in _vmblock(out_none)


def test_cloudinit_user_account_static_ip():
    ci = CloudInitResolved(
        username="ops", password="s3cr3t", ssh_keys=[_EXAMPLE_KEY],
        ip_mode="static", ip_address_cidr="10.0.0.5/24", ip_gateway="10.0.0.1",
        dns_servers=["1.1.1.1", "9.9.9.9"], dns_domain="lab.local",
    )
    block = _vmblock(stack_to_tfjson(_spec(), {"deb12": 9000}, cloudinit={"web": ci}))
    init = block["initialization"]
    assert init["user_account"] == {
        "username": "ops", "password": "s3cr3t", "keys": [_EXAMPLE_KEY],
    }
    assert init["ip_config"] == [{"ipv4": {"address": "10.0.0.5/24", "gateway": "10.0.0.1"}}]
    assert init["dns"] == {"servers": ["1.1.1.1", "9.9.9.9"], "domain": "lab.local"}


def test_cloudinit_dhcp_no_dns():
    ci = CloudInitResolved(username="ops", password=None, ssh_keys=[_EXAMPLE_KEY], ip_mode="dhcp")
    init = _vmblock(stack_to_tfjson(_spec(), {"deb12": 9000}, cloudinit={"web": ci}))["initialization"]
    assert init["ip_config"] == [{"ipv4": {"address": "dhcp"}}]
    assert "dns" not in init
    # password omitted when empty (no empty keys in .tf.json, D)
    assert "password" not in init["user_account"]


def test_cloudinit_no_ip_mode_omits_ip_config():
    ci = CloudInitResolved(username="ops", password="x", ssh_keys=[], ip_mode=None)
    init = _vmblock(stack_to_tfjson(_spec(), {"deb12": 9000}, cloudinit={"web": ci}))["initialization"]
    assert "ip_config" not in init
    assert init["user_account"] == {"username": "ops", "password": "x"}


def test_cloudinit_not_in_lifecycle_ignore_changes():
    """D: initialization is tracked normally, never added to ignore_changes."""
    ci = CloudInitResolved(username="ops", password="x", ssh_keys=[])
    block = _vmblock(stack_to_tfjson(_spec(), {"deb12": 9000}, cloudinit={"web": ci}))
    assert block["lifecycle"]["ignore_changes"] == ["clone"]


def test_cloudinit_count_applies_to_all_instances():
    """AC-TRANS-2: an entry per expanded name; only listed names get a block."""
    spec = _spec(count=2)
    ci = CloudInitResolved(username="ops", password="x", ssh_keys=[], ip_mode="dhcp")
    out = stack_to_tfjson(spec, {"deb12": 9000}, cloudinit={"web-1": ci, "web-2": ci})
    vms = out["resource"]["proxmox_virtual_environment_vm"]
    assert "initialization" in vms["web-1"]
    assert "initialization" in vms["web-2"]


# ════════════════════════════════════════════════════════════════════════════
# Pure: schema validators (AC-KEYS / AC-IP form)
# ════════════════════════════════════════════════════════════════════════════

def test_block_rejects_bad_ssh_key():
    with pytest.raises(ValidationError):
        CloudInitBlock(enabled=True, username="ops", ssh_keys=["not-a-key"])


def test_block_rejects_multiline_ssh_key():
    with pytest.raises(ValidationError):
        CloudInitBlock(ssh_keys=[f"{_EXAMPLE_KEY}\nrm -rf /"])


def test_block_accepts_known_key_types():
    CloudInitBlock(ssh_keys=[
        "ssh-rsa AAAAB3xx a@b",
        "ecdsa-sha2-nistp256 AAAExx c@d",
        "sk-ssh-ed25519@openssh.com AAAExx e@f",
    ])


def test_block_static_requires_cidr_and_gateway():
    with pytest.raises(ValidationError):
        CloudInitBlock(enabled=True, username="ops", password="x", ip_mode="static")


def test_block_static_rejects_bad_cidr():
    with pytest.raises(ValidationError):
        CloudInitBlock(
            enabled=True, username="ops", password="x",
            ip_mode="static", ip_address_cidr="not-an-ip", ip_gateway="10.0.0.1",
        )


def test_block_dhcp_allows_no_ip_fields():
    b = CloudInitBlock(enabled=True, username="ops", password="x", ip_mode="dhcp")
    assert b.ip_mode == "dhcp"


# ════════════════════════════════════════════════════════════════════════════
# Store + resolver (DB) — shared stack_db fixture from conftest
# ════════════════════════════════════════════════════════════════════════════

_YAML_SINGLE = (
    "name: webstack\n"
    "version: '1.0.0'\n"
    "resources:\n"
    "  - {type: vm, name: web, node: pve, template: deb12}\n"
)
_YAML_COUNT = (
    "name: webstack\n"
    "version: '1.0.0'\n"
    "resources:\n"
    "  - {type: vm, name: web, node: pve, template: deb12, count: 3}\n"
)
_YAML_MIX = (
    "name: mixstack\n"
    "version: '1.0.0'\n"
    "resources:\n"
    "  - {type: vm, name: web, node: pve, template: deb12}\n"
    "  - {type: vm, name: db, node: pve, template: deb12}\n"
)


async def _make_stack(yaml_text: str) -> int:
    from backend.plus.stacks.schemas import StackCreateRequest
    resp = await service.create_stack(StackCreateRequest(yaml_text=yaml_text), 10, "alice")
    return resp.id


async def _spec_of_id(stack_id: int):
    return await cloud_init._load_spec(stack_id)


@pytest.mark.asyncio
async def test_get_empty_returns_disabled_default(stack_db):
    sid = await _make_stack(_YAML_SINGLE)
    cfg = await cloud_init.get_cloud_init(sid)
    assert cfg.default.enabled is False
    assert cfg.default.password_set is False
    assert cfg.overrides == []


@pytest.mark.asyncio
async def test_put_then_get_default_password_never_plaintext(stack_db):
    """AC-STORE-4 / AC-SEC-1: GET returns password_set, never the value."""
    sid = await _make_stack(_YAML_SINGLE)
    req = CloudInitConfigRequest(default=CloudInitBlock(
        enabled=True, username="ops", password="topsecret", ssh_keys=[_EXAMPLE_KEY],
    ))
    await cloud_init.put_cloud_init(sid, req, "alice")
    cfg = await cloud_init.get_cloud_init(sid)
    assert cfg.default.enabled is True
    assert cfg.default.username == "ops"
    assert cfg.default.password_set is True
    # The response object must not carry a password field value anywhere.
    assert "topsecret" not in cfg.model_dump_json()
    # And the DB stores a Fernet blob, not the plaintext.
    async with get_db() as db:
        r = await db.execute(
            text("SELECT password_enc FROM stack_cloud_init WHERE stack_id=:s AND vm_name=''"),
            {"s": sid},
        )
        enc = r.mappings().fetchone()["password_enc"]
    assert enc and "topsecret" not in enc


@pytest.mark.asyncio
async def test_password_merge_empty_keeps_existing(stack_db):
    """EC-6: editing other fields without re-entering the password keeps it."""
    sid = await _make_stack(_YAML_SINGLE)
    await cloud_init.put_cloud_init(sid, CloudInitConfigRequest(default=CloudInitBlock(
        enabled=True, username="ops", password="keepme",
    )), "alice")
    # second PUT without password but still enabled (lockout ok because pw exists)
    await cloud_init.put_cloud_init(sid, CloudInitConfigRequest(default=CloudInitBlock(
        enabled=True, username="ops2", password=None,
    )), "alice")
    cfg = await cloud_init.get_cloud_init(sid)
    assert cfg.default.username == "ops2"
    assert cfg.default.password_set is True
    # resolve decrypts back to the original kept password
    resolved = await cloud_init.resolve_for_transpile(sid, await _spec_of_id(sid))
    assert resolved["web"].password == "keepme"


@pytest.mark.asyncio
async def test_lockout_422_no_key_no_password(stack_db):
    """AC-ACT-4 / EC-2: enabled needs username AND (key OR password)."""
    sid = await _make_stack(_YAML_SINGLE)
    with pytest.raises(HTTPException) as ei:
        await cloud_init.put_cloud_init(sid, CloudInitConfigRequest(default=CloudInitBlock(
            enabled=True, username="ops",  # no key, no password
        )), "alice")
    assert ei.value.status_code == 422


@pytest.mark.asyncio
async def test_lockout_422_missing_username(stack_db):
    sid = await _make_stack(_YAML_SINGLE)
    with pytest.raises(HTTPException) as ei:
        await cloud_init.put_cloud_init(sid, CloudInitConfigRequest(default=CloudInitBlock(
            enabled=True, ssh_keys=[_EXAMPLE_KEY],
        )), "alice")
    assert ei.value.status_code == 422


@pytest.mark.asyncio
async def test_static_with_count_gt1_422(stack_db):
    """AC-IP-3 / EC-5: static IP + count>1 is rejected."""
    sid = await _make_stack(_YAML_COUNT)
    with pytest.raises(HTTPException) as ei:
        await cloud_init.put_cloud_init(sid, CloudInitConfigRequest(default=CloudInitBlock(
            enabled=True, username="ops", password="x",
            ip_mode="static", ip_address_cidr="10.0.0.5/24", ip_gateway="10.0.0.1",
        )), "alice")
    assert ei.value.status_code == 422


@pytest.mark.asyncio
async def test_dhcp_with_count_gt1_allowed(stack_db):
    sid = await _make_stack(_YAML_COUNT)
    await cloud_init.put_cloud_init(sid, CloudInitConfigRequest(default=CloudInitBlock(
        enabled=True, username="ops", password="x", ip_mode="dhcp",
    )), "alice")
    resolved = await cloud_init.resolve_for_transpile(sid, await _spec_of_id(sid))
    assert set(resolved) == {"web-1", "web-2", "web-3"}
    assert all(r.ip_mode == "dhcp" for r in resolved.values())


@pytest.mark.asyncio
async def test_resolve_default_applies_to_all(stack_db):
    """AC-ACT-2: active default → every VM gets it."""
    sid = await _make_stack(_YAML_MIX)
    await cloud_init.put_cloud_init(sid, CloudInitConfigRequest(default=CloudInitBlock(
        enabled=True, username="ops", password="x",
    )), "alice")
    resolved = await cloud_init.resolve_for_transpile(sid, await _spec_of_id(sid))
    assert set(resolved) == {"web", "db"}
    assert resolved["web"].username == "ops"


@pytest.mark.asyncio
async def test_resolve_override_wins(stack_db):
    """AC-ACT-2: an active override beats the default for that VM."""
    sid = await _make_stack(_YAML_MIX)
    await cloud_init.put_cloud_init(sid, CloudInitConfigRequest(
        default=CloudInitBlock(enabled=True, username="ops", password="x"),
        overrides=[CloudInitBlock(vm_name="db", enabled=True, username="dba", password="y")],
    ), "alice")
    resolved = await cloud_init.resolve_for_transpile(sid, await _spec_of_id(sid))
    assert resolved["web"].username == "ops"
    assert resolved["db"].username == "dba"


@pytest.mark.asyncio
async def test_resolve_disabled_override_suppresses(stack_db):
    """AC-ACT-3 / EC-8: a disabled override → that VM inherits from template."""
    sid = await _make_stack(_YAML_MIX)
    await cloud_init.put_cloud_init(sid, CloudInitConfigRequest(
        default=CloudInitBlock(enabled=True, username="ops", password="x"),
        overrides=[CloudInitBlock(vm_name="db", enabled=False)],
    ), "alice")
    resolved = await cloud_init.resolve_for_transpile(sid, await _spec_of_id(sid))
    assert "web" in resolved
    assert "db" not in resolved  # suppressed


@pytest.mark.asyncio
async def test_resolve_inactive_default_no_blocks(stack_db):
    """EC-1: default disabled, no overrides → no blocks at all (Weg 1)."""
    sid = await _make_stack(_YAML_MIX)
    await cloud_init.put_cloud_init(sid, CloudInitConfigRequest(
        default=CloudInitBlock(enabled=False),
    ), "alice")
    resolved = await cloud_init.resolve_for_transpile(sid, await _spec_of_id(sid))
    assert resolved == {}


@pytest.mark.asyncio
async def test_resolve_no_rows_empty(stack_db):
    """EC-1: never touched → empty map (no migration / byte-identical)."""
    sid = await _make_stack(_YAML_MIX)
    resolved = await cloud_init.resolve_for_transpile(sid, await _spec_of_id(sid))
    assert resolved == {}


@pytest.mark.asyncio
async def test_orphan_override_flagged_and_ignored(stack_db):
    """EC-4: an override for a vanished VM name is flagged + ignored on resolve."""
    sid = await _make_stack(_YAML_MIX)
    # Insert an override directly for a name that doesn't exist in the spec.
    async with get_db() as db:
        await db.execute(
            text(
                "INSERT INTO stack_cloud_init "
                "(stack_id, vm_name, enabled, username, password_enc, created_at, updated_at) "
                "VALUES (:s, 'ghost', 1, 'x', :pw, '2026-01-01', '2026-01-01')"
            ),
            {"s": sid, "pw": cloud_init.encrypt_secret("z")},
        )
        await db.commit()
    cfg = await cloud_init.get_cloud_init(sid)
    ghost = next(o for o in cfg.overrides if o.vm_name == "ghost")
    assert ghost.orphan is True
    # resolve ignores the orphan (no 'ghost' key, and web/db unaffected)
    resolved = await cloud_init.resolve_for_transpile(sid, await _spec_of_id(sid))
    assert "ghost" not in resolved


@pytest.mark.asyncio
async def test_full_replace_drops_removed_overrides(stack_db):
    sid = await _make_stack(_YAML_MIX)
    await cloud_init.put_cloud_init(sid, CloudInitConfigRequest(
        default=CloudInitBlock(enabled=True, username="ops", password="x"),
        overrides=[CloudInitBlock(vm_name="db", enabled=True, username="dba", password="y")],
    ), "alice")
    # second PUT without the db override → it must be gone
    await cloud_init.put_cloud_init(sid, CloudInitConfigRequest(
        default=CloudInitBlock(enabled=True, username="ops", password="x"),
    ), "alice")
    cfg = await cloud_init.get_cloud_init(sid)
    assert cfg.overrides == []


# ════════════════════════════════════════════════════════════════════════════
# OBS-2 (/qa S629): undecryptable password at deploy time (SECRET_KEY rotated)
# ════════════════════════════════════════════════════════════════════════════

async def _insert_block(sid: int, *, vm_name: str = "", pw_enc: str = "bad-token",
                        keys: list[str] | None = None) -> None:
    async with get_db() as db:
        await db.execute(
            text(
                "INSERT INTO stack_cloud_init "
                "(stack_id, vm_name, enabled, username, password_enc, ssh_keys_json, "
                " created_at, updated_at) "
                "VALUES (:s, :vm, 1, 'ops', :pw, :keys, '2026-01-01', '2026-01-01')"
            ),
            {"s": sid, "vm": vm_name, "pw": pw_enc,
             "keys": json.dumps(keys) if keys else None},
        )
        await db.commit()


@pytest.mark.asyncio
async def test_resolve_undecryptable_password_no_key_422(stack_db):
    """OBS-2: a stored password that can't be decrypted + no SSH key → 422 at
    resolve (gate) instead of silently shipping a locked-out VM."""
    sid = await _make_stack(_YAML_SINGLE)
    await _insert_block(sid, pw_enc="not-a-valid-fernet-token")
    with pytest.raises(HTTPException) as ei:
        await cloud_init.resolve_for_transpile(sid, await _spec_of_id(sid))
    assert ei.value.status_code == 422


@pytest.mark.asyncio
async def test_resolve_undecryptable_password_with_key_ok(stack_db):
    """OBS-2: same broken password but an SSH key is present → no 422; deploys
    with the key (no lockout)."""
    sid = await _make_stack(_YAML_SINGLE)
    await _insert_block(sid, pw_enc="not-a-valid-fernet-token", keys=[_EXAMPLE_KEY])
    resolved = await cloud_init.resolve_for_transpile(sid, await _spec_of_id(sid))
    assert resolved["web"].password is None
    assert resolved["web"].ssh_keys == [_EXAMPLE_KEY]


@pytest.mark.asyncio
async def test_resolve_undecryptable_password_destroy_skips_gate(stack_db):
    """OBS-2: destroy (gate=False) must not be blocked by a broken password."""
    sid = await _make_stack(_YAML_SINGLE)
    await _insert_block(sid, pw_enc="not-a-valid-fernet-token")
    resolved = await cloud_init.resolve_for_transpile(
        sid, await _spec_of_id(sid), gate=False,
    )
    assert resolved["web"].password is None


# ════════════════════════════════════════════════════════════════════════════
# OBS-3 (/qa S629): per-SSH-key length cap
# ════════════════════════════════════════════════════════════════════════════

def test_block_rejects_overlong_ssh_key():
    with pytest.raises(ValidationError):
        CloudInitBlock(ssh_keys=["ssh-ed25519 " + "A" * 9000])


def test_block_accepts_normal_length_key():
    CloudInitBlock(ssh_keys=["ssh-ed25519 " + "A" * 700 + " user@host"])


# ════════════════════════════════════════════════════════════════════════════
# OBS-1 (/qa S629): runner collects active cloud-init passwords for log masking
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_runner_collects_active_cloud_init_passwords(stack_db):
    from backend.plus.stacks import runner
    sid = await _make_stack(_YAML_MIX)
    await cloud_init.put_cloud_init(sid, CloudInitConfigRequest(default=CloudInitBlock(
        enabled=True, username="ops", password="masked-pw",
    )), "alice")
    # default applies to web + db → same password, deduped to one entry.
    secrets = await runner._cloud_init_secrets(sid)
    assert secrets == ["masked-pw"]


@pytest.mark.asyncio
async def test_runner_secrets_empty_when_inactive(stack_db):
    from backend.plus.stacks import runner
    sid = await _make_stack(_YAML_SINGLE)
    assert await runner._cloud_init_secrets(sid) == []


# ════════════════════════════════════════════════════════════════════════════
# Router: Core-404 gate + auth (AC-RBAC-1)
# ════════════════════════════════════════════════════════════════════════════

_app = FastAPI()
_app.include_router(router)
_OP_TOKEN = create_access_token("alice", auth_type="local", role="operator", portal_permissions=[])
_OP_H = {"Authorization": f"Bearer {_OP_TOKEN}"}


@pytest_asyncio.fixture
async def client():
    await init_db()
    eng = get_sync_engine()
    if eng is not None:
        m.stacks.create(eng, checkfirst=True)
        m.stack_resources.create(eng, checkfirst=True)
        m.stack_versions.create(eng, checkfirst=True)
        m.stack_cloud_init.create(eng, checkfirst=True)
    async with get_db() as db:
        try:
            await db.execute(text(
                "INSERT INTO local_users (id, username, password_hash, role, active, created_at) "
                "VALUES (2, 'alice', 'x', 'operator', 1, '2026-01-01T00:00:00')"
            ))
        except Exception:
            pass
        await db.commit()
    async with AsyncClient(transport=ASGITransport(app=_app), base_url="http://test") as ac:
        yield ac


def _plus():
    return patch("backend.plus.stacks.router.plus_behavior")


@pytest.mark.asyncio
async def test_cloud_init_get_404_in_core(client):
    with _plus() as pb:
        pb.can_use_stacks.return_value = False
        r = await client.get("/api/stacks/1/cloud-init", headers=_OP_H)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_cloud_init_put_404_in_core(client):
    with _plus() as pb:
        pb.can_use_stacks.return_value = False
        r = await client.put("/api/stacks/1/cloud-init", headers=_OP_H, json={"default": {}})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_cloud_init_get_unauthenticated(client):
    r = await client.get("/api/stacks/1/cloud-init")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_cloud_init_roundtrip_via_router(client):
    """End-to-end PUT→GET through the router with plus active + owner auth."""
    from backend.plus.stacks.schemas import StackCreateRequest
    resp = await service.create_stack(StackCreateRequest(yaml_text=_YAML_SINGLE), 2, "alice")
    sid = resp.id
    with _plus() as pb:
        pb.can_use_stacks.return_value = True
        put = await client.put(
            f"/api/stacks/{sid}/cloud-init", headers=_OP_H,
            json={"default": {"enabled": True, "username": "ops", "password": "pw",
                              "ssh_keys": [_EXAMPLE_KEY]}},
        )
        assert put.status_code == 200, put.text
        assert put.json()["default"]["password_set"] is True
        assert "pw" not in put.text
        get = await client.get(f"/api/stacks/{sid}/cloud-init", headers=_OP_H)
    assert get.status_code == 200
    assert get.json()["default"]["username"] == "ops"
