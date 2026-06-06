# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-76: DB-backed service tests (real temp SQLite + stacks tables)."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.plus.stacks import service
from backend.plus.stacks.cleanup import on_user_deleted_stacks
from backend.plus.stacks.schemas import StackCreateRequest, StackUpdateRequest

pytestmark = pytest.mark.plus_only

_YAML = (
    "name: webcluster\n"
    "version: '1.0.0'\n"
    "resources:\n"
    "  - type: vm\n"
    "    name: web\n"
    "    node: pve-01\n"
    "    template: deb12\n"
    "    count: 3\n"
)


async def _create(owner=10, name="webcluster"):
    yaml = _YAML.replace("name: webcluster", f"name: {name}", 1)
    return await service.create_stack(StackCreateRequest(yaml_text=yaml), user_id=owner, username="alice")


# ── create ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_stack(stack_db):
    s = await _create()
    assert s.id > 0
    assert s.name == "webcluster"
    assert s.resource_count == 3        # count:3 expanded
    assert s.status == "active"
    assert s.owner_user_id == 10
    assert s.source_kind == "structured"
    assert len(s.current_etag) == 64


@pytest.mark.asyncio
async def test_create_invalid_structure_422(stack_db):
    with pytest.raises(HTTPException) as exc:
        await service.create_stack(StackCreateRequest(yaml_text="name: ab\nresources: []\n"), 10, "alice")
    assert exc.value.status_code == 422


# ── list (owner filtering) ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_owner_sees_own(stack_db):
    await _create(owner=10, name="alpha")
    await _create(owner=20, name="beta")
    own = await service.list_stacks(user_id=10, role="operator")
    assert {s.name for s in own} == {"alpha"}


@pytest.mark.asyncio
async def test_list_admin_sees_all(stack_db):
    await _create(owner=10, name="alpha")
    await _create(owner=20, name="beta")
    allst = await service.list_stacks(user_id=999, role="admin")
    assert {s.name for s in allst} == {"alpha", "beta"}


@pytest.mark.asyncio
async def test_list_query_filter(stack_db):
    await _create(owner=10, name="alpha")
    await _create(owner=10, name="other")
    res = await service.list_stacks(user_id=10, role="operator", q="alph")
    assert {s.name for s in res} == {"alpha"}


# ── detail ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_detail_resolves_resources(stack_db):
    s = await _create()
    detail = await service.get_stack_detail(s.id)
    assert detail.yaml_text
    assert len(detail.resources) == 3
    assert {r["name"] for r in detail.resources} == {"web-1", "web-2", "web-3"}


@pytest.mark.asyncio
async def test_get_detail_not_found(stack_db):
    with pytest.raises(HTTPException) as exc:
        await service.get_stack_detail(99999)
    assert exc.value.status_code == 404


# ── update + etag + versioning ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_with_correct_etag(stack_db):
    s = await _create()
    new_yaml = _YAML.replace("count: 3", "count: 2").replace("'1.0.0'", "'1.1.0'")
    upd = await service.update_with_etag(
        s.id, StackUpdateRequest(yaml_text=new_yaml, expected_etag=s.current_etag), 10, "alice"
    )
    assert upd.resource_count == 2
    assert upd.version == "1.1.0"
    assert upd.current_etag != s.current_etag


@pytest.mark.asyncio
async def test_update_etag_conflict(stack_db):
    s = await _create()
    with pytest.raises(service.EtagConflict) as exc:
        await service.update_with_etag(
            s.id, StackUpdateRequest(yaml_text=_YAML, expected_etag="0" * 64), 10, "alice"
        )
    assert exc.value.body.current_etag == s.current_etag
    assert exc.value.body.current_yaml


@pytest.mark.asyncio
async def test_update_saves_version(stack_db):
    s = await _create()
    new_yaml = _YAML.replace("count: 3", "count: 1")
    await service.update_with_etag(
        s.id, StackUpdateRequest(yaml_text=new_yaml, expected_etag=s.current_etag), 10, "alice"
    )
    versions = await service.list_versions(s.id)
    assert len(versions) == 1
    assert versions[0].version_number == 1


@pytest.mark.asyncio
async def test_version_numbers_monotonic(stack_db):
    s = await _create()
    etag = s.current_etag
    for i in range(3):
        y = _YAML.replace("count: 3", f"count: {i + 1}")
        upd = await service.update_with_etag(
            s.id, StackUpdateRequest(yaml_text=y, expected_etag=etag), 10, "alice"
        )
        etag = upd.current_etag
    versions = await service.list_versions(s.id)
    assert [v.version_number for v in versions] == [3, 2, 1]


@pytest.mark.asyncio
async def test_version_fifo_cap(stack_db, monkeypatch):
    monkeypatch.setattr(service, "_version_cap", _const_cap(2))
    s = await _create()
    etag = s.current_etag
    for i in range(5):
        y = _YAML.replace("count: 3", f"count: {(i % 4) + 1}") + f"# edit {i}\n"
        upd = await service.update_with_etag(
            s.id, StackUpdateRequest(yaml_text=y, expected_etag=etag), 10, "alice"
        )
        etag = upd.current_etag
    versions = await service.list_versions(s.id)
    assert len(versions) == 2                       # capped
    assert versions[0].version_number == 5          # newest kept


# ── change_summary ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_custom_change_summary(stack_db):
    s = await _create()
    new_yaml = _YAML.replace("count: 3", "count: 2")
    await service.update_with_etag(
        s.id,
        StackUpdateRequest(yaml_text=new_yaml, expected_etag=s.current_etag, change_summary="reduce web nodes"),
        10, "alice",
    )
    versions = await service.list_versions(s.id)
    assert versions[0].change_summary == "reduce web nodes"


# ── diff ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_diff_current_vs_version(stack_db):
    s = await _create()
    new_yaml = _YAML.replace("count: 3", "count: 1")
    await service.update_with_etag(
        s.id, StackUpdateRequest(yaml_text=new_yaml, expected_etag=s.current_etag), 10, "alice"
    )
    d = await service.diff_stack(s.id, "v1", "current")
    changed = [e.key for e in d.diff if e.change != "unchanged"]
    assert "resources.0.count" in changed


@pytest.mark.asyncio
async def test_diff_invalid_label_422(stack_db):
    s = await _create()
    with pytest.raises(HTTPException) as exc:
        await service.diff_stack(s.id, "bogus", "current")
    assert exc.value.status_code == 422


# ── restore ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_restore_version(stack_db):
    s = await _create()
    new_yaml = _YAML.replace("count: 3", "count: 1")
    await service.update_with_etag(
        s.id, StackUpdateRequest(yaml_text=new_yaml, expected_etag=s.current_etag), 10, "alice"
    )
    restored = await service.restore_version(s.id, 1, 10, "alice")
    assert restored.resource_count == 3             # v1 had count:3
    versions = await service.list_versions(s.id)
    assert any("restored from v1" in (v.change_summary or "") for v in versions)


@pytest.mark.asyncio
async def test_get_version_not_found(stack_db):
    s = await _create()
    with pytest.raises(HTTPException) as exc:
        await service.get_version(s.id, 99)
    assert exc.value.status_code == 404


# ── soft delete + same name reuse ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_soft_delete_hides_from_list(stack_db):
    s = await _create()
    await service.soft_delete(s.id, "alice")
    assert await service.list_stacks(10, "operator") == []


@pytest.mark.asyncio
async def test_soft_delete_then_same_name(stack_db):
    s = await _create(name="web")
    await service.soft_delete(s.id, "alice")
    s2 = await _create(name="web")        # partial-unique excludes soft-deleted
    assert s2.id != s.id


@pytest.mark.asyncio
async def test_admin_include_deleted(stack_db):
    s = await _create()
    await service.soft_delete(s.id, "alice")
    deleted = await service.list_stacks(999, "admin", include_deleted=True)
    assert any(x.id == s.id for x in deleted)


# ── orphan flow ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_user_delete_orphans_stacks(stack_db):
    s = await _create(owner=10)
    count = await on_user_deleted_stacks(10)
    assert count == 1
    orphans = await service.list_orphans()
    assert any(o.id == s.id for o in orphans)


@pytest.mark.asyncio
async def test_reassign_orphan(stack_db):
    s = await _create(owner=10)
    await on_user_deleted_stacks(10)
    reassigned = await service.reassign_orphan(s.id, 20, "admin")
    assert reassigned.owner_user_id == 20
    assert reassigned.is_orphan is False
    assert await service.list_orphans() == []


@pytest.mark.asyncio
async def test_reassign_unknown_owner_422(stack_db):
    s = await _create(owner=10)
    await on_user_deleted_stacks(10)
    with pytest.raises(HTTPException) as exc:
        await service.reassign_orphan(s.id, 99999, "admin")
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_purge_orphan(stack_db):
    s = await _create(owner=10)
    await on_user_deleted_stacks(10)
    await service.purge_orphan(s.id, "admin")
    with pytest.raises(HTTPException):
        await service.get_stack_detail(s.id)


@pytest.mark.asyncio
async def test_purge_non_orphan_404(stack_db):
    s = await _create(owner=10)
    with pytest.raises(HTTPException) as exc:
        await service.purge_orphan(s.id, "admin")
    assert exc.value.status_code == 404


# ── apply_pending (approval handlers) ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_apply_pending_edit_ok(stack_db):
    s = await _create()
    new_yaml = _YAML.replace("count: 3", "count: 2")
    await service.apply_pending_edit(s.id, s.current_etag, new_yaml, None, 10, "alice")
    detail = await service.get_stack_detail(s.id)
    assert len(detail.resources) == 2


@pytest.mark.asyncio
async def test_apply_pending_edit_etag_mismatch(stack_db):
    s = await _create()
    with pytest.raises(service.EtagConflict):
        await service.apply_pending_edit(s.id, "0" * 64, _YAML, None, 10, "alice")


@pytest.mark.asyncio
async def test_apply_pending_delete(stack_db):
    s = await _create()
    await service.apply_pending_delete(s.id, "alice")
    assert await service.list_stacks(10, "operator") == []


def _const_cap(n):
    async def _cap():
        return n
    return _cap
