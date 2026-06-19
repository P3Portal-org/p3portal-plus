# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-76: Tests für validation.py (Struktur + Forward-Compat + Semantik)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from backend.plus.stacks import validation
from backend.plus.stacks.schemas import StackCreateRequest

pytestmark = pytest.mark.plus_only


# ── parse_input ───────────────────────────────────────────────────────────────

def test_parse_input_yaml_verbatim():
    yaml = "name: web\nversion: '1.0.0'\n"
    req = StackCreateRequest(yaml_text=yaml)
    raw, canonical = validation.parse_input(req)
    assert canonical == yaml          # verbatim storage
    assert raw["name"] == "web"


def test_parse_input_structured_to_yaml():
    req = StackCreateRequest(name="web", version="1.0.0", resources=[])
    raw, canonical = validation.parse_input(req)
    assert "name: web" in canonical
    assert raw["resources"] == []


def test_parse_input_broken_yaml():
    req = StackCreateRequest(yaml_text="a: [unterminated")
    with pytest.raises(validation.StackInputError):
        validation.parse_input(req)


def test_parse_input_root_not_mapping():
    req = StackCreateRequest(yaml_text="- a\n- b\n")
    with pytest.raises(validation.StackInputError):
        validation.parse_input(req)


def test_parse_input_empty():
    with pytest.raises(validation.StackInputError):
        validation.parse_input(StackCreateRequest())


# ── validate_structure (Pydantic + unknown fields) ───────────────────────────

def _vm(**over):
    base = {"type": "vm", "name": "web", "node": "pve", "template": "deb12"}
    base.update(over)
    return base


def test_structure_valid():
    raw = {"name": "webcluster", "resources": [_vm()]}
    spec, errors, warnings = validation.validate_structure(raw)
    assert spec is not None
    assert errors == []


def test_structure_name_too_short():
    raw = {"name": "ab", "resources": []}
    spec, errors, warnings = validation.validate_structure(raw)
    assert spec is None
    assert any("name" in e for e in errors)


def test_structure_name_bad_regex():
    raw = {"name": "bad name!", "resources": []}
    spec, errors, _ = validation.validate_structure(raw)
    assert spec is None


def test_structure_vm_missing_node():
    raw = {"name": "webcluster", "resources": [{"type": "vm", "name": "web", "template": "deb12"}]}
    spec, errors, _ = validation.validate_structure(raw)
    assert spec is None
    assert any("node" in e for e in errors)


def test_structure_count_out_of_range():
    raw = {"name": "webcluster", "resources": [_vm(count=99)]}
    spec, errors, _ = validation.validate_structure(raw)
    assert spec is None


def test_structure_duplicate_resource_names():
    raw = {"name": "webcluster", "resources": [_vm(name="web"), _vm(name="web")]}
    spec, errors, _ = validation.validate_structure(raw)
    assert spec is None
    assert any("duplicate" in e for e in errors)


def test_structure_unknown_stack_field_warning():
    raw = {"name": "webcluster", "resources": [], "frobnicate": True}
    spec, errors, warnings = validation.validate_structure(raw)
    assert spec is not None
    assert any("frobnicate" in w for w in warnings)


def test_structure_unknown_vm_field_warning():
    raw = {"name": "webcluster", "resources": [_vm(weird_field=1)]}
    spec, errors, warnings = validation.validate_structure(raw)
    assert spec is not None
    assert any("weird_field" in w for w in warnings)


def test_structure_unknown_network_field_warning():
    raw = {"name": "webcluster", "resources": [_vm(network={"bridge": "vmbr0", "extra": "x"})]}
    spec, errors, warnings = validation.validate_structure(raw)
    assert spec is not None
    assert any("extra" in w for w in warnings)


# ── semantic_warnings ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_semantic_node_not_found_warning():
    raw = {"name": "webcluster", "resources": [_vm(node="ghost")]}
    spec, _, _ = validation.validate_structure(raw)
    with patch(
        "backend.plus.stacks.validation.plus_behavior"
    ) as pb, patch(
        "backend.services.nodes_service.get_node_for_proxmox_name",
        new=AsyncMock(return_value=None),
    ):
        pb.can_use_pools_quotas.return_value = True
        warnings = await validation.semantic_warnings(spec)
    assert any("ghost" in w and "not found" in w for w in warnings)


@pytest.mark.asyncio
async def test_semantic_pool_without_capability_warns():
    raw = {"name": "webcluster", "resources": [_vm(pool="web-servers")]}
    spec, _, _ = validation.validate_structure(raw)
    with patch(
        "backend.plus.stacks.validation.plus_behavior"
    ) as pb, patch(
        "backend.services.nodes_service.get_node_for_proxmox_name",
        new=AsyncMock(return_value=object()),
    ):
        pb.can_use_pools_quotas.return_value = False
        warnings = await validation.semantic_warnings(spec)
    assert any("pool field ignored" in w for w in warnings)


@pytest.mark.asyncio
async def test_semantic_pool_with_capability_no_warn():
    raw = {"name": "webcluster", "resources": [_vm(pool="web-servers")]}
    spec, _, _ = validation.validate_structure(raw)
    with patch(
        "backend.plus.stacks.validation.plus_behavior"
    ) as pb, patch(
        "backend.services.nodes_service.get_node_for_proxmox_name",
        new=AsyncMock(return_value=object()),
    ):
        pb.can_use_pools_quotas.return_value = True
        warnings = await validation.semantic_warnings(spec)
    assert not any("pool field ignored" in w for w in warnings)


@pytest.mark.asyncio
async def test_validate_request_full_invalid_structure():
    req = StackCreateRequest(yaml_text="name: ab\nresources: []\n")
    spec, canonical, errors, warnings = await validation.validate_request(req)
    assert spec is None
    assert errors


# ── PROJ-82: extra-disk datastore semantic warning (AC-VAL-2) ─────────────────

@pytest.mark.asyncio
async def test_semantic_extra_disk_unknown_datastore_warns():
    raw = {"name": "dbcluster", "resources": [
        _vm(extra_disks=[{"interface": "scsi1", "size": 100, "datastore": "ghost-pool"}])]}
    spec, errors, _ = validation.validate_structure(raw)
    assert spec is not None and not errors
    with patch("backend.plus.stacks.validation.plus_behavior") as pb, patch(
        "backend.services.nodes_service.get_node_for_proxmox_name",
        new=AsyncMock(return_value=object()),
    ), patch(
        "backend.plus.stacks.validation._image_storages_on_node",
        new=AsyncMock(return_value={"local-lvm", "ceph"}),
    ):
        pb.can_use_pools_quotas.return_value = True
        warnings = await validation.semantic_warnings(spec)
    assert any("ghost-pool" in w for w in warnings)


@pytest.mark.asyncio
async def test_semantic_extra_disk_known_datastore_no_warn():
    raw = {"name": "dbcluster", "resources": [
        _vm(extra_disks=[{"interface": "scsi1", "size": 100, "datastore": "ceph"}])]}
    spec, _, _ = validation.validate_structure(raw)
    with patch("backend.plus.stacks.validation.plus_behavior") as pb, patch(
        "backend.services.nodes_service.get_node_for_proxmox_name",
        new=AsyncMock(return_value=object()),
    ), patch(
        "backend.plus.stacks.validation._image_storages_on_node",
        new=AsyncMock(return_value={"local-lvm", "ceph"}),
    ):
        pb.can_use_pools_quotas.return_value = True
        warnings = await validation.semantic_warnings(spec)
    assert not any("datastore" in w for w in warnings)


@pytest.mark.asyncio
async def test_semantic_no_extra_disks_skips_proxmox_call():
    raw = {"name": "dbcluster", "resources": [_vm()]}
    spec, _, _ = validation.validate_structure(raw)
    img = AsyncMock(return_value={"ceph"})
    with patch("backend.plus.stacks.validation.plus_behavior") as pb, patch(
        "backend.services.nodes_service.get_node_for_proxmox_name",
        new=AsyncMock(return_value=object()),
    ), patch("backend.plus.stacks.validation._image_storages_on_node", new=img):
        pb.can_use_pools_quotas.return_value = True
        await validation.semantic_warnings(spec)
    img.assert_not_called()  # no extra_disks → never touches Proxmox
