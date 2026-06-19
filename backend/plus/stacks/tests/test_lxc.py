# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-86: Stacks LXC – schema, discriminated union, transpile, state diff, gates.

Covers AC-RESOURCE, AC-TMPL, AC-COMPUTE, AC-NET, AC-SECURITY, AC-FEAT, AC-MOUNT,
AC-GUEST (LXC root login), AC-TRANSPILE, AC-MIX, the edge cases (EC-1/2/6/7/8/10)
and the typ-aware deploy_service/preview helpers. The pure parts need no
tofu/Proxmox; the cloud-init resolve/lockout parts use the temp DB via the shared
``stack_db`` fixture (conftest).
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from backend.plus.stacks import cloud_init, deploy_service as ds, service
from backend.plus.stacks.deployments import (
    _parse_size_gib,
    parse_state_disks,
    parse_state_resources,
)
from backend.plus.stacks.preview import resolve_resources
from backend.plus.stacks.schemas import (
    LXCFeatures,
    LXCMount,
    LXCResource,
    NetworkConfig,
    StackCreateRequest,
    StackSpec,
    VMResource,
)
from backend.plus.stacks.transpile import stack_to_tfjson
from backend.plus.stacks.validation import validate_request

pytestmark = pytest.mark.plus_only

_OSTEMPLATE = "local:vztmpl/debian-12-standard.tar.zst"
_EXAMPLE_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITESTKEY user@host"


def _lxc(**kw) -> LXCResource:
    base = dict(
        type="lxc", name="proxy", node="pve", template=_OSTEMPLATE,
        rootfs_datastore="local-lvm", hostname="proxy",
    )
    base.update(kw)
    return LXCResource(**base)


def _lxc_spec(**kw) -> StackSpec:
    return StackSpec(name="ctstack", resources=[_lxc(**kw)])


def _ct_block(spec, name="proxy"):
    return stack_to_tfjson(spec, {})["resource"][
        "proxmox_virtual_environment_container"][name]


# ════════════════════════════════════════════════════════════════════════════
# Schema validators (AC-RESOURCE / AC-TMPL / AC-MOUNT)
# ════════════════════════════════════════════════════════════════════════════

def test_lxc_defaults():
    r = _lxc()
    assert r.type == "lxc"
    assert r.unprivileged is True          # AC-SEC-1
    assert r.cores == 1 and r.memory == 512 and r.swap == 512 and r.rootfs_size == 8
    assert r.features is None and r.mounts == []


def test_lxc_bad_template_rejected():
    # AC-TMPL-1: a VM-template name is not a valid ostemplate file-id
    with pytest.raises(ValidationError):
        _lxc(template="debian-12")
    with pytest.raises(ValidationError):
        _lxc(template="local:iso/foo.iso")
    # a valid ostemplate passes
    assert _lxc(template="ceph:vztmpl/alpine-3.20.tar.gz").template.endswith("tar.gz")


def test_lxc_bad_hostname_rejected():
    with pytest.raises(ValidationError):
        _lxc(hostname="not_a hostname!")
    assert _lxc(hostname="web-01.lab.local").hostname == "web-01.lab.local"


def test_lxc_bad_rootfs_datastore_charset():
    with pytest.raises(ValidationError):
        _lxc(rootfs_datastore="ceph pool;rm")


def test_lxc_mount_id_format_and_limit():
    with pytest.raises(ValidationError):
        LXCMount(id="m0", datastore="lv", size=10, path="/d")
    with pytest.raises(ValidationError):
        LXCMount(id="mp256", datastore="lv", size=10, path="/d")
    assert LXCMount(id="mp255", datastore="lv", size=10, path="/d").id == "mp255"


def test_lxc_mount_path_must_be_absolute():
    with pytest.raises(ValidationError):
        LXCMount(id="mp0", datastore="lv", size=10, path="data")


def test_lxc_duplicate_mount_id_rejected():
    with pytest.raises(ValidationError) as ei:
        _lxc(mounts=[
            {"id": "mp0", "datastore": "lv", "size": 10, "path": "/a"},
            {"id": "mp0", "datastore": "lv", "size": 5, "path": "/b"},
        ])
    assert "duplicate mount id" in str(ei.value)


# ════════════════════════════════════════════════════════════════════════════
# Discriminated union (AC-RES-1 / AC-TRANS-2 / Tech-Design D)
# ════════════════════════════════════════════════════════════════════════════

def test_legacy_vm_dict_without_type_validates_as_vm():
    # The before-validator injects type="vm" → byte-for-byte legacy behaviour.
    s = StackSpec(name="webstack", resources=[
        {"name": "web", "node": "pve", "template": "deb12"}])
    assert isinstance(s.resources[0], VMResource)
    assert s.resources[0].type == "vm"


def test_vm_instance_form_still_accepted():
    s = StackSpec(name="dbstack", resources=[VMResource(name="db", node="pve", template="t")])
    assert isinstance(s.resources[0], VMResource)


def test_mixed_vm_and_lxc_union():
    s = StackSpec(name="mixstack", resources=[
        {"name": "web", "node": "pve", "template": "deb12"},
        {"type": "lxc", "name": "proxy", "node": "pve", "template": _OSTEMPLATE,
         "rootfs_datastore": "lv", "hostname": "proxy"},
    ])
    assert [type(r).__name__ for r in s.resources] == ["VMResource", "LXCResource"]


@pytest.mark.asyncio
async def test_duplicate_name_vm_lxc_collision(stack_db):
    # EC-10: a name shared by a VM and an LXC is a duplicate (labels must be unique)
    yaml_text = (
        "name: dup\nversion: '1.0.0'\nresources:\n"
        "  - {type: vm, name: web, node: pve, template: deb12}\n"
        f"  - {{type: lxc, name: web, node: pve, template: '{_OSTEMPLATE}', "
        "rootfs_datastore: lv, hostname: web}\n"
    )
    spec, _c, errors, _w = await validate_request(StackCreateRequest(yaml_text=yaml_text))
    assert spec is None
    assert any("duplicate resource names" in e for e in errors)


def test_validation_typ_aware_unknown_fields():
    # AC-RES-3 / Tech-Design D: LXC fields are not flagged as unknown for an LXC
    from backend.plus.stacks.validation import _collect_unknown_field_warnings
    raw = {"name": "s", "resources": [
        {"type": "lxc", "name": "ct", "node": "pve", "template": _OSTEMPLATE,
         "rootfs_datastore": "lv", "hostname": "h", "unprivileged": False,
         "features": {"nesting": True, "bogus": 1},
         "mounts": [{"id": "mp0", "datastore": "lv", "size": 1, "path": "/x", "junk": 2}]},
    ]}
    warnings = _collect_unknown_field_warnings(raw)
    # known LXC fields are NOT flagged; the bogus feature/mount fields ARE
    assert not any("'rootfs_datastore'" in w or "'unprivileged'" in w for w in warnings)
    assert any("'bogus'" in w for w in warnings)
    assert any("'junk'" in w for w in warnings)


# ════════════════════════════════════════════════════════════════════════════
# Transpile (AC-TRANSPILE / AC-COMPUTE / AC-NET / AC-SECURITY / AC-FEAT / AC-MOUNT)
# ════════════════════════════════════════════════════════════════════════════

def test_transpile_pure_vm_has_no_container_map():
    # AC-TRANS-2 / EC-1: a pure-VM stack is byte-for-byte the legacy output.
    out = stack_to_tfjson(
        StackSpec(name="webstack", resources=[VMResource(name="web", node="pve", template="d")]),
        {"d": 9000})
    assert set(out["resource"]) == {"proxmox_virtual_environment_vm"}


def test_transpile_lxc_only_has_no_vm_map():
    out = stack_to_tfjson(_lxc_spec(), {})
    assert set(out["resource"]) == {"proxmox_virtual_environment_container"}


def test_transpile_mixed_emits_both_maps():
    spec = StackSpec(name="mixstack", resources=[
        VMResource(name="web", node="pve", template="deb12"),
        _lxc(name="proxy"),
    ])
    out = stack_to_tfjson(spec, {"deb12": 100})
    assert set(out["resource"]) == {
        "proxmox_virtual_environment_vm", "proxmox_virtual_environment_container"}


def test_transpile_lxc_template_passthrough_no_keyerror():
    # AC-TMPL-1: an LXC template is NOT looked up in template_vmids → no KeyError
    ct = _ct_block(_lxc_spec())
    assert ct["operating_system"] == {"template_file_id": _OSTEMPLATE}


def test_transpile_lxc_compute_and_rootfs():
    ct = _ct_block(_lxc_spec(cores=4, memory=2048, swap=1024, rootfs_size=20,
                             rootfs_datastore="ceph"))
    assert ct["cpu"] == {"cores": 4}
    assert ct["memory"] == {"dedicated": 2048, "swap": 1024}
    assert ct["disk"] == {"datastore_id": "ceph", "size": 20}   # AC-DISK-1


def test_transpile_lxc_network_with_vlan():
    ct = _ct_block(_lxc_spec(network=NetworkConfig(bridge="vmbr1", tag=42)))
    assert ct["network_interface"] == [{"name": "eth0", "bridge": "vmbr1", "vlan_id": 42}]


def test_transpile_lxc_network_default_bridge():
    ct = _ct_block(_lxc_spec())
    assert ct["network_interface"] == [{"name": "eth0", "bridge": "vmbr0"}]


def test_transpile_lxc_unprivileged_default_true():
    assert _ct_block(_lxc_spec())["unprivileged"] is True


def test_transpile_lxc_privileged():
    assert _ct_block(_lxc_spec(unprivileged=False))["unprivileged"] is False


def test_transpile_lxc_features_only_active_emitted():
    ct = _ct_block(_lxc_spec(features=LXCFeatures(nesting=True, mount="nfs;cifs")))
    assert ct["features"] == {"nesting": True, "mount": "nfs;cifs"}


def test_transpile_lxc_no_features_block_when_all_off():
    # AC-FEAT-1: default all-off → no features block
    assert "features" not in _ct_block(_lxc_spec())
    assert "features" not in _ct_block(_lxc_spec(features=LXCFeatures()))


def test_transpile_lxc_mountpoints_sorted_with_unit_size():
    ct = _ct_block(_lxc_spec(mounts=[
        {"id": "mp1", "datastore": "ceph", "size": 5, "path": "/logs"},
        {"id": "mp0", "datastore": "ceph", "size": 20, "path": "/data", "backup": True},
    ]))
    # sorted by index → mp0 first; size is a unit string; backup only when true
    assert ct["mount_point"] == [
        {"volume": "ceph", "size": "20G", "path": "/data", "backup": True},
        {"volume": "ceph", "size": "5G", "path": "/logs"},
    ]


def test_transpile_lxc_ignore_changes_operating_system():
    # AC-TRANS-3: ostemplate is create-time-only, like clone for a VM
    assert _ct_block(_lxc_spec())["lifecycle"] == {"ignore_changes": ["operating_system"]}


def test_transpile_lxc_count_named_with_hostname_suffix():
    vms = stack_to_tfjson(
        StackSpec(name="ctstack", resources=[_lxc(name="ct", count=3, hostname="ct")]), {})[
        "resource"]["proxmox_virtual_environment_container"]
    assert set(vms) == {"ct-1", "ct-2", "ct-3"}
    assert vms["ct-1"]["initialization"]["hostname"] == "ct-1"
    assert vms["ct-3"]["initialization"]["hostname"] == "ct-3"


def test_transpile_lxc_tags_and_pool():
    ct = _ct_block(_lxc_spec(tags=["edge"], pool="mypool"))
    assert ct["tags"] == ["edge"]
    assert ct["pool_id"] == "mypool"


# ── LXC cloud-init: root login, no username (AC-GUEST-2 / EC-7) ────────────────

def test_transpile_lxc_cloudinit_omits_username():
    ci = cloud_init.CloudInitResolved(
        username="ignored", password="s3cret", ssh_keys=[_EXAMPLE_KEY], ip_mode="dhcp")
    ct = stack_to_tfjson(_lxc_spec(), {}, cloudinit={"proxy": ci})[
        "resource"]["proxmox_virtual_environment_container"]["proxy"]
    ua = ct["initialization"]["user_account"]
    assert "username" not in ua                       # root login (AC-GUEST-2)
    assert ua["password"] == "s3cret"
    assert ua["keys"] == [_EXAMPLE_KEY]
    assert ct["initialization"]["ip_config"] == [{"ipv4": {"address": "dhcp"}}]
    assert ct["initialization"]["hostname"] == "proxy"   # hostname from r.hostname


def test_transpile_vm_cloudinit_keeps_username():
    # the same resolver record keeps username for a VM target
    ci = cloud_init.CloudInitResolved(username="ops", password="x", ssh_keys=[])
    block = stack_to_tfjson(
        StackSpec(name="webstack", resources=[VMResource(name="web", node="pve", template="d")]),
        {"d": 1}, cloudinit={"web": ci})["resource"]["proxmox_virtual_environment_vm"]["web"]
    assert block["initialization"]["user_account"]["username"] == "ops"


# ════════════════════════════════════════════════════════════════════════════
# Preview typ-aware disk (K)
# ════════════════════════════════════════════════════════════════════════════

def test_preview_lxc_disk_is_rootfs_size():
    out = resolve_resources(_lxc_spec(rootfs_size=16))
    assert len(out) == 1
    assert out[0].type == "lxc" and out[0].disk == 16
    assert out[0].template == _OSTEMPLATE


# ════════════════════════════════════════════════════════════════════════════
# deploy_service typ-aware helpers (F / K / OP7)
# ════════════════════════════════════════════════════════════════════════════

def test_resource_totals_counts_lxc_rootfs():
    spec = StackSpec(name="mixstack", resources=[
        VMResource(name="web", node="pve", template="d", count=2, cores=2, memory=1024, disk=30),
        _lxc(name="ct", count=1, cores=1, memory=512, rootfs_size=8),
    ])
    vm_count, cores, ram, disk = ds._resource_totals(spec)
    assert vm_count == 3                      # 2 VMs + 1 LXC
    assert cores == 2 * 2 + 1                 # 5
    assert ram == 1024 * 2 + 512             # 2560
    assert disk == 30 * 2 + 8                # 68 (LXC rootfs)


@pytest.mark.asyncio
async def test_resolve_template_vmids_filters_vm_only():
    # AC-TMPL-1: the LXC ostemplate must NOT be searched as a VM template.
    spec = StackSpec(name="mixstack", resources=[
        VMResource(name="web", node="pve", template="deb12"),
        _lxc(name="proxy"),
    ])
    client = type("C", (), {"get_cluster_resources_v2": AsyncMock(
        return_value=[{"vmid": 9000, "name": "deb12", "template": 1}])})()
    from backend.plus.stacks.tests.test_deploy_service import _node
    with patch("backend.services.proxmox.ProxmoxClient", return_value=client):
        out = await ds.resolve_template_vmids(_node(), spec)
    assert out == {"deb12": 9000}             # only the VM template, no ostemplate


def test_spec_disks_by_resource_lxc_rootfs_and_mounts():
    spec = _lxc_spec(rootfs_size=8, mounts=[
        {"id": "mp1", "datastore": "ceph", "size": 50, "path": "/b"},
        {"id": "mp0", "datastore": "ceph", "size": 20, "path": "/a"},
    ])
    out = ds._spec_disks_by_resource(spec)
    # rootfs + positional mp keys (sorted by index → mp0 = the 20G one)
    assert out["proxy"] == {"rootfs": 8, "mp0": 20, "mp1": 50}


def test_diff_mount_removed_is_destructive():
    # state has rootfs + mp0 + mp1; new spec drops mp1 → destructive (AC-MOUNT-3)
    state = {"proxy": [
        {"interface": "rootfs", "size": 8},
        {"interface": "mp0", "size": 20},
        {"interface": "mp1", "size": 50},
    ]}
    spec_disks = {"proxy": {"rootfs": 8, "mp0": 20}}
    changes = ds.diff_disks(state, spec_disks)
    assert [(c.interface, c.reason) for c in changes] == [("mp1", "removed")]


def test_diff_rootfs_shrink_is_destructive():
    state = {"proxy": [{"interface": "rootfs", "size": 20}]}
    changes = ds.diff_disks(state, {"proxy": {"rootfs": 8}})
    assert changes and changes[0].interface == "rootfs" and changes[0].reason == "shrunk"


def test_diff_mount_add_and_grow_not_destructive():
    state = {"proxy": [{"interface": "rootfs", "size": 8}, {"interface": "mp0", "size": 20}]}
    spec_disks = {"proxy": {"rootfs": 16, "mp0": 40, "mp1": 5}}  # grow + add
    assert ds.diff_disks(state, spec_disks) == []


# ════════════════════════════════════════════════════════════════════════════
# deployments: container state parse (OP4 / OP7)
# ════════════════════════════════════════════════════════════════════════════

def test_parse_size_gib_tolerant():
    assert _parse_size_gib(10) == 10
    assert _parse_size_gib("10") == 10
    assert _parse_size_gib("10G") == 10
    assert _parse_size_gib("  50 GiB ") == 50
    assert _parse_size_gib(None) is None
    assert _parse_size_gib("garbage") is None


def test_parse_state_resources_extracts_container_kind():
    state = json.dumps({"resources": [
        {"type": "proxmox_virtual_environment_vm", "name": "web",
         "instances": [{"attributes": {"vm_id": 100, "node_name": "pve"}}]},
        {"type": "proxmox_virtual_environment_container", "name": "proxy",
         "instances": [{"attributes": {"vm_id": 200, "node_name": "pve"}}]},
    ]})
    res = parse_state_resources(state)
    assert {(r["resource_name"], r["vmid"], r["kind"]) for r in res} == {
        ("web", 100, "vm"), ("proxy", 200, "lxc")}


def test_parse_state_disks_container_rootfs_and_positional_mounts():
    state = json.dumps({"resources": [
        {"type": "proxmox_virtual_environment_container", "name": "proxy", "instances": [
            {"attributes": {
                "vm_id": 200,
                "disk": [{"datastore_id": "local-lvm", "size": 8}],
                "mount_point": [
                    {"volume": "ceph", "size": "20G", "path": "/a"},
                    {"volume": "ceph", "size": "5G", "path": "/b"},
                ],
            }}]},
    ]})
    res = parse_state_disks(state)
    assert res["proxy"] == [
        {"interface": "rootfs", "size": 8, "datastore_id": "local-lvm"},
        {"interface": "mp0", "size": 20, "datastore_id": "ceph"},
        {"interface": "mp1", "size": 5, "datastore_id": "ceph"},
    ]


def test_parse_state_disks_container_single_disk_dict():
    state = json.dumps({"resources": [
        {"type": "proxmox_virtual_environment_container", "name": "ct", "instances": [
            {"attributes": {"vm_id": 1, "disk": {"datastore_id": "lv", "size": 4}}}]},
    ]})
    assert parse_state_disks(state)["ct"] == [
        {"interface": "rootfs", "size": 4, "datastore_id": "lv"}]


# ════════════════════════════════════════════════════════════════════════════
# Cloud-init lockout: LXC = root, no username (AC-GUEST-3 / EC-6) — DB tests
# ════════════════════════════════════════════════════════════════════════════

_YAML_LXC = (
    "name: ctstack\nversion: '1.0.0'\nresources:\n"
    f"  - {{type: lxc, name: proxy, node: pve, template: '{_OSTEMPLATE}', "
    "rootfs_datastore: lv, hostname: proxy}\n"
)
_YAML_LXC_COUNT = (
    "name: ctstack\nversion: '1.0.0'\nresources:\n"
    f"  - {{type: lxc, name: proxy, node: pve, template: '{_OSTEMPLATE}', "
    "rootfs_datastore: lv, hostname: proxy, count: 2}\n"
)
_YAML_VM_PLUS_LXC = (
    "name: mixstack\nversion: '1.0.0'\nresources:\n"
    "  - {type: vm, name: web, node: pve, template: deb12}\n"
    f"  - {{type: lxc, name: proxy, node: pve, template: '{_OSTEMPLATE}', "
    "rootfs_datastore: lv, hostname: proxy}\n"
)


async def _make_stack(yaml_text: str) -> int:
    resp = await service.create_stack(StackCreateRequest(yaml_text=yaml_text), 10, "alice")
    return resp.id


async def _spec_of_id(stack_id: int):
    return await cloud_init._load_spec(stack_id)


@pytest.mark.asyncio
async def test_lxc_default_no_username_ok(stack_db):
    """AC-GUEST-3: an LXC-only active default needs a key/password but NO username."""
    sid = await _make_stack(_YAML_LXC)
    from backend.plus.stacks.schemas import CloudInitBlock, CloudInitConfigRequest
    await cloud_init.put_cloud_init(sid, CloudInitConfigRequest(default=CloudInitBlock(
        enabled=True, password="rootpw",  # no username
    )), "alice")
    resolved = await cloud_init.resolve_for_transpile(sid, await _spec_of_id(sid))
    assert resolved["proxy"].password == "rootpw"


@pytest.mark.asyncio
async def test_lxc_default_lockout_still_needs_key_or_password(stack_db):
    """AC-GUEST-3: key OR password is still required for an LXC block."""
    sid = await _make_stack(_YAML_LXC)
    from backend.plus.stacks.schemas import CloudInitBlock, CloudInitConfigRequest
    with pytest.raises(HTTPException) as ei:
        await cloud_init.put_cloud_init(sid, CloudInitConfigRequest(default=CloudInitBlock(
            enabled=True,  # no key, no password, no username
        )), "alice")
    assert ei.value.status_code == 422


@pytest.mark.asyncio
async def test_lxc_override_no_username_ok(stack_db):
    """AC-GUEST-3: a per-LXC override needs no username either."""
    sid = await _make_stack(_YAML_LXC)
    from backend.plus.stacks.schemas import CloudInitBlock, CloudInitConfigRequest
    await cloud_init.put_cloud_init(sid, CloudInitConfigRequest(
        default=CloudInitBlock(enabled=False),
        overrides=[CloudInitBlock(vm_name="proxy", enabled=True, ssh_keys=[_EXAMPLE_KEY])],
    ), "alice")
    resolved = await cloud_init.resolve_for_transpile(sid, await _spec_of_id(sid))
    assert resolved["proxy"].ssh_keys == [_EXAMPLE_KEY]


@pytest.mark.asyncio
async def test_default_covering_vm_still_needs_username(stack_db):
    """AC-GUEST-3: when the default covers a VM, username is still required."""
    sid = await _make_stack(_YAML_VM_PLUS_LXC)
    from backend.plus.stacks.schemas import CloudInitBlock, CloudInitConfigRequest
    with pytest.raises(HTTPException) as ei:
        await cloud_init.put_cloud_init(sid, CloudInitConfigRequest(default=CloudInitBlock(
            enabled=True, password="x",  # missing username, default covers the VM "web"
        )), "alice")
    assert ei.value.status_code == 422
    assert any("username" in e for e in ei.value.detail["errors"])


@pytest.mark.asyncio
async def test_lxc_static_with_count_gt1_422(stack_db):
    """EC-8 / AC-GUEST-4: static IP + count>1 is rejected for LXC too."""
    sid = await _make_stack(_YAML_LXC_COUNT)
    from backend.plus.stacks.schemas import CloudInitBlock, CloudInitConfigRequest
    with pytest.raises(HTTPException) as ei:
        await cloud_init.put_cloud_init(sid, CloudInitConfigRequest(default=CloudInitBlock(
            enabled=True, password="x",
            ip_mode="static", ip_address_cidr="10.0.0.5/24", ip_gateway="10.0.0.1",
        )), "alice")
    assert ei.value.status_code == 422


@pytest.mark.asyncio
async def test_lxc_resolve_ignores_default_username_for_root(stack_db):
    """EC-7: a username set in the default is ignored for the LXC (root)."""
    sid = await _make_stack(_YAML_LXC)
    from backend.plus.stacks.schemas import CloudInitBlock, CloudInitConfigRequest
    # username is allowed (harmless), but the transpile drops it for LXC
    await cloud_init.put_cloud_init(sid, CloudInitConfigRequest(default=CloudInitBlock(
        enabled=True, username="ops", password="x",
    )), "alice")
    resolved = await cloud_init.resolve_for_transpile(sid, await _spec_of_id(sid))
    ct = stack_to_tfjson(await _spec_of_id(sid), {}, cloudinit=resolved)[
        "resource"]["proxmox_virtual_environment_container"]["proxy"]
    assert "username" not in ct["initialization"]["user_account"]
