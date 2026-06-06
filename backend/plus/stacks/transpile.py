# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-76 Phase 2b: transpile the structured P3 model → OpenTofu ``.tf.json``.

Pure function — fully unit-testable without tofu/Proxmox (Tech-Design Open Point 1).

Design rules:
  * ``count > 1`` ⇒ **N separately named resources** (``web-1..web-N`` via the
    Phase-1 naming convention), **not** tofu ``count``/``for_each``. This keeps
    ``stack_deployed_resources.resource_name`` 1:1 with the Phase-1 preview and
    avoids ``count.index`` interpolation bugs.
  * **``vm_id`` omitted by default** → Proxmox auto-assigns a free VMID, so a
    stack never collides with or overwrites a foreign VM (AC-2B-ISO-3). An
    optional explicit ``vmid`` (base + offset for count>1) is honored when set.
  * **Provider block carries no inline credentials** — bpg reads the token from
    the environment injected by the engine (AC-2B-TRANS-4 / Phase 2a).
  * Only ``resource`` blocks are emitted — no ``import``, no node-wide
    ``data source`` (AC-2B-ISO-2).

bpg resource ``proxmox_virtual_environment_vm`` attribute mapping (AC-2B-TRANS-2):
  template → ``clone.vm_id`` (resolved template VMID) · cores/sockets → ``cpu``
  · memory → ``memory.dedicated`` · disk → ``disk.size`` · cpu_type → ``cpu.type``
  · network.bridge/tag → ``network_device.bridge``/``vlan_id`` · tags → ``tags``
  · pool → ``pool_id`` · start_after_create → ``started`` · count → N instances.
"""
from __future__ import annotations

from typing import Any

from .schemas import StackSpec, VMResource

# Pinned bpg provider (Phase 2a image bundle). Kept in sync with the Dockerfile
# ARG BPG_PROVIDER_VERSION; only the major.minor constraint is asserted here.
_PROVIDER_SOURCE = "bpg/proxmox"
_PROVIDER_VERSION = "~> 0.78"

# Default block interface for a cloned root disk (model has no datastore field
# in Phase 1; the clone inherits the template datastore — size triggers a resize).
_DEFAULT_DISK_INTERFACE = "scsi0"


def _expanded_names(r: VMResource) -> list[str]:
    """Resolve a resource's instance names (count → suffix), matching Phase-1 preview."""
    if r.count <= 1:
        return [r.name]
    return [f"{r.name}-{i}" for i in range(1, r.count + 1)]


def _vm_resource_block(
    r: VMResource, resolved_name: str, template_vmid: int, vmid: int | None = None
) -> dict[str, Any]:
    """Build a single bpg ``proxmox_virtual_environment_vm`` resource block."""
    block: dict[str, Any] = {
        "node_name": r.node,
        "name": resolved_name,
        # vm_id omitted → Proxmox auto-assigns a free VMID (collision-safe,
        # AC-2B-ISO-3). Only set when the user explicitly pinned a VMID.
        "clone": {"vm_id": template_vmid},
        "cpu": {"cores": r.cores, "sockets": r.sockets, "type": r.cpu_type},
        "memory": {"dedicated": r.memory},
        "disk": {"interface": _DEFAULT_DISK_INTERFACE, "size": r.disk},
        "started": r.start_after_create,
        # agent disabled (default) → bpg does not wait for the guest agent to
        # report an IP, so apply finishes fast. enabled → full integration but
        # bpg waits on the agent (slow on cloud-init boots).
        "agent": {"enabled": r.agent},
    }

    # network_device (bridge + optional VLAN tag)
    bridge = r.network.bridge if r.network else "vmbr0"
    net: dict[str, Any] = {"bridge": bridge}
    if r.network and r.network.tag:
        net["vlan_id"] = r.network.tag
    block["network_device"] = net

    if r.tags:
        block["tags"] = list(r.tags)
    if r.pool:
        block["pool_id"] = r.pool
    if vmid is not None:
        block["vm_id"] = vmid

    # clone is a create-time-only relationship; after the VM exists the bpg
    # provider would otherwise report a perpetual diff on every plan/refresh
    # (phantom drift). Ignoring it makes drift detection report only real changes.
    block["lifecycle"] = {"ignore_changes": ["clone"]}

    return block


def stack_to_tfjson(
    spec: StackSpec,
    template_vmids: dict[str, int],
) -> dict[str, Any]:
    """Generate the full ``main.tf.json`` dict for a stack.

    ``template_vmids`` maps each referenced template name → its resolved VMID
    (looked up against the cluster at plan time). A missing template raises
    ``KeyError`` so the caller can surface a clear plan error (Edge 2/5).
    """
    vm_resources: dict[str, dict[str, Any]] = {}
    for r in spec.resources:
        if r.template not in template_vmids:
            raise KeyError(r.template)
        tmpl_vmid = template_vmids[r.template]
        for idx, resolved_name in enumerate(_expanded_names(r)):
            # Tofu resource labels must be unique; resolved_name already is
            # (Phase-1 duplicate-name validation guarantees it).
            # Explicit VMID (optional): base + offset so count>1 stays unique.
            vmid = (r.vmid + idx) if r.vmid is not None else None
            vm_resources[resolved_name] = _vm_resource_block(
                r, resolved_name, tmpl_vmid, vmid=vmid
            )

    return {
        "terraform": {
            "required_providers": {
                "proxmox": {
                    "source": _PROVIDER_SOURCE,
                    "version": _PROVIDER_VERSION,
                }
            }
        },
        # No inline credentials — token via env (AC-2B-TRANS-4).
        "provider": {"proxmox": {}},
        "resource": {
            "proxmox_virtual_environment_vm": vm_resources,
        },
    }
