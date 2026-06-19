# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-82: Stacks-Multi-Disk – schema validators, transpile list, state diff.

All pure (no tofu/Proxmox). Covers AC-MODEL, AC-TRANSPILE, AC-VAL, AC-REMOVE.
"""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from backend.plus.stacks.schemas import ExtraDisk, StackSpec, VMResource
from backend.plus.stacks.transpile import stack_to_tfjson
from backend.plus.stacks.deployments import parse_state_disks
from backend.plus.stacks.deploy_service import (
    _spec_disks_by_resource,
    diff_disks,
)

pytestmark = pytest.mark.plus_only


def _spec(**res) -> StackSpec:
    base = dict(name="db", node="pve", template="deb12")
    base.update(res)
    return StackSpec(name="dbstack", resources=[VMResource(**base)])


def _ed(interface="scsi1", size=100, datastore="ceph"):
    return {"interface": interface, "size": size, "datastore": datastore}


# ── ExtraDisk schema validators (AC-MODEL-2 / AC-VAL-1) ───────────────────────

def test_extra_disk_valid():
    d = ExtraDisk(interface="scsi1", size=100, datastore="ceph-pool")
    assert d.interface == "scsi1"


def test_extra_disk_bad_interface_format():
    with pytest.raises(ValidationError):
        ExtraDisk(interface="sdb", size=10, datastore="ceph")


def test_extra_disk_scsi0_reserved():
    with pytest.raises(ValidationError) as ei:
        ExtraDisk(interface="scsi0", size=10, datastore="ceph")
    assert "reserved" in str(ei.value)


def test_extra_disk_index_over_bus_limit():
    # virtio max index is 15 → virtio16 invalid
    with pytest.raises(ValidationError):
        ExtraDisk(interface="virtio16", size=10, datastore="ceph")
    # sata max index is 5 → sata6 invalid
    with pytest.raises(ValidationError):
        ExtraDisk(interface="sata6", size=10, datastore="ceph")
    # scsi max index is 30 → scsi31 invalid, scsi30 valid
    with pytest.raises(ValidationError):
        ExtraDisk(interface="scsi31", size=10, datastore="ceph")
    assert ExtraDisk(interface="scsi30", size=10, datastore="ceph").interface == "scsi30"


def test_extra_disk_bad_datastore_charset():
    with pytest.raises(ValidationError):
        ExtraDisk(interface="scsi1", size=10, datastore="ceph pool;rm")


def test_extra_disk_size_range():
    with pytest.raises(ValidationError):
        ExtraDisk(interface="scsi1", size=0, datastore="ceph")
    with pytest.raises(ValidationError):
        ExtraDisk(interface="scsi1", size=99999, datastore="ceph")


def test_vmresource_duplicate_interface_rejected():
    with pytest.raises(ValidationError) as ei:
        VMResource(name="db", node="pve", template="t",
                   extra_disks=[_ed("scsi1"), _ed("scsi1")])
    assert "duplicate disk interface" in str(ei.value)


def test_vmresource_different_buses_ok():
    r = VMResource(name="db", node="pve", template="t",
                   extra_disks=[_ed("scsi1"), _ed("virtio0"), _ed("sata2")])
    assert len(r.extra_disks) == 3


# ── Backward-compat (AC-MODEL-3) ──────────────────────────────────────────────

def test_legacy_resource_has_empty_extra_disks_by_default():
    r = VMResource(name="db", node="pve", template="t")
    assert r.extra_disks == []


def test_transpile_single_disk_is_one_element_list():
    # No extra_disks → disk is a one-element list. bpg-0.109 requires a list even
    # for a single disk (framework migration, S654 bump); the old single-dict form
    # is rejected by `tofu validate`.
    block = stack_to_tfjson(_spec(), {"deb12": 9000})["resource"][
        "proxmox_virtual_environment_vm"]["db"]
    assert block["disk"] == [{"interface": "scsi0", "size": 32}]


# ── Transpile multi-disk (AC-TRANSPILE) ───────────────────────────────────────

def test_transpile_extra_disks_emit_list_with_root_first():
    spec = _spec(disk=32, extra_disks=[_ed("scsi1", 100, "ceph"), _ed("virtio0", 50, "local-lvm")])
    block = stack_to_tfjson(spec, {"deb12": 9000})["resource"][
        "proxmox_virtual_environment_vm"]["db"]
    disks = block["disk"]
    assert isinstance(disks, list)
    # Root at position 0, no datastore_id (inherits template)
    assert disks[0] == {"interface": "scsi0", "size": 32}
    assert "datastore_id" not in disks[0]
    # Extras carry datastore_id + size
    assert disks[1] == {"interface": "scsi1", "size": 100, "datastore_id": "ceph"}
    assert disks[2] == {"interface": "virtio0", "size": 50, "datastore_id": "local-lvm"}


def test_transpile_count_duplicates_disk_layout():
    spec = StackSpec(name="dbstack", resources=[
        VMResource(name="db", node="pve", template="deb12", count=2,
                   extra_disks=[_ed("scsi1", 100, "ceph")])])
    vms = stack_to_tfjson(spec, {"deb12": 9000})["resource"]["proxmox_virtual_environment_vm"]
    for nm in ("db-1", "db-2"):
        disks = vms[nm]["disk"]
        assert disks[0]["interface"] == "scsi0"
        assert disks[1] == {"interface": "scsi1", "size": 100, "datastore_id": "ceph"}


# ── parse_state_disks ─────────────────────────────────────────────────────────

def test_parse_state_disks_list_form():
    state = json.dumps({"resources": [
        {"type": "proxmox_virtual_environment_vm", "name": "db", "instances": [
            {"attributes": {"vm_id": 123, "node_name": "pve", "disk": [
                {"interface": "scsi0", "size": 32, "datastore_id": "local-lvm"},
                {"interface": "scsi1", "size": 100, "datastore_id": "ceph"},
            ]}}]},
    ]})
    res = parse_state_disks(state)
    assert res["db"][0]["interface"] == "scsi0"
    assert res["db"][1] == {"interface": "scsi1", "size": 100, "datastore_id": "ceph"}


def test_parse_state_disks_single_dict_form():
    state = json.dumps({"resources": [
        {"type": "proxmox_virtual_environment_vm", "name": "db", "instances": [
            {"attributes": {"vm_id": 1, "disk": {"interface": "scsi0", "size": 32}}}]},
    ]})
    assert parse_state_disks(state)["db"] == [
        {"interface": "scsi0", "size": 32, "datastore_id": ""}]


def test_parse_state_disks_ignores_foreign_types_and_garbage():
    assert parse_state_disks("{bad") == {}
    state = json.dumps({"resources": [
        {"type": "other", "name": "x", "instances": [{"attributes": {"disk": []}}]}]})
    assert parse_state_disks(state) == {}


# ── _spec_disks_by_resource ───────────────────────────────────────────────────

def test_spec_disks_by_resource_includes_root_and_extras():
    spec = _spec(disk=32, extra_disks=[_ed("scsi1", 100, "ceph")])
    out = _spec_disks_by_resource(spec)
    assert out["db"] == {"scsi0": 32, "scsi1": 100}


def test_spec_disks_by_resource_count_expanded():
    spec = StackSpec(name="stk", resources=[
        VMResource(name="db", node="pve", template="t", count=2, disk=20,
                   extra_disks=[_ed("scsi1", 50, "ceph")])])
    out = _spec_disks_by_resource(spec)
    assert set(out) == {"db-1", "db-2"}
    assert out["db-1"] == {"scsi0": 20, "scsi1": 50}


# ── diff_disks (AC-REMOVE) ────────────────────────────────────────────────────

def _state(**disks_by_vm):
    return {vm: [dict(d) for d in disks] for vm, disks in disks_by_vm.items()}


def test_diff_disks_removed_extra_disk():
    state = {"db": [
        {"interface": "scsi0", "size": 32},
        {"interface": "scsi1", "size": 100},
    ]}
    spec_disks = {"db": {"scsi0": 32}}  # scsi1 dropped
    changes = diff_disks(state, spec_disks)
    assert len(changes) == 1
    assert changes[0].interface == "scsi1"
    assert changes[0].reason == "removed"
    assert changes[0].old_size == 100


def test_diff_disks_shrunk_extra_disk():
    state = {"db": [{"interface": "scsi1", "size": 100}]}
    spec_disks = {"db": {"scsi0": 32, "scsi1": 50}}
    changes = diff_disks(state, spec_disks)
    assert len(changes) == 1
    assert changes[0].reason == "shrunk"
    assert changes[0].old_size == 100 and changes[0].new_size == 50


def test_diff_disks_root_shrink_is_destructive():
    state = {"db": [{"interface": "scsi0", "size": 32}]}
    spec_disks = {"db": {"scsi0": 16}}
    changes = diff_disks(state, spec_disks)
    assert changes and changes[0].interface == "scsi0" and changes[0].reason == "shrunk"


def test_diff_disks_add_and_grow_not_destructive():
    state = {"db": [{"interface": "scsi0", "size": 32}, {"interface": "scsi1", "size": 50}]}
    spec_disks = {"db": {"scsi0": 64, "scsi1": 100, "scsi2": 20}}  # grow scsi0/1 + add scsi2
    assert diff_disks(state, spec_disks) == []


def test_diff_disks_whole_vm_gone_skipped():
    # VM no longer in spec → resource-level destroy, not a disk diff
    state = {"db": [{"interface": "scsi1", "size": 100}]}
    assert diff_disks(state, {}) == []


def test_diff_disks_no_state_no_changes():
    assert diff_disks({}, {"db": {"scsi0": 32}}) == []
