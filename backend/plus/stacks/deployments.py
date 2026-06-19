# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-76 Phase 2b: deployment + deployed-resource CRUD and state derivation.

  * ``stack_deployments`` – apply/destroy history (one row per run).
  * ``stack_deployed_resources`` – Stack ↔ real VM link (mutations-block lookup,
    drift, detail UI). ``(portal_node_id, vmid)`` UNIQUE ⇒ a VM lives in at most
    one stack state (AC-2B-ISO-4, "1 engine per resource").
  * ``derive_deployment_state`` – computes the UI badge from the latest run +
    drift + edit-after-deploy (Tech-Design Open Point 4); ``stacks.status``-CHECK
    stays untouched.
  * ``sync_deployed_resources`` – fed by ``tofu state pull`` JSON after apply/destroy.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text

from backend.db.database import get_db

logger = logging.getLogger(__name__)

# bpg resource types in the OpenTofu state.
_VM_RESOURCE_TYPE = "proxmox_virtual_environment_vm"
_CONTAINER_RESOURCE_TYPE = "proxmox_virtual_environment_container"  # PROJ-86 LXC


def _parse_size_gib(value: Any) -> Optional[int]:
    """Tolerant GiB parse: int, ``"10"`` or unit-suffixed ``"10G"`` → 10.

    bpg models the rootfs ``disk.size`` as an int (GiB) but a container
    ``mount_point.size`` as a string with a unit (``"10G"``) — both must parse
    for the destructive diff (PROJ-86 OP7).
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        m = re.match(r"^\s*(\d+)\s*[A-Za-z]*\s*$", str(value))
        return int(m.group(1)) if m else None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── stack_deployments CRUD ────────────────────────────────────────────────────

async def create_deployment(
    stack_id: int,
    operation: str,
    job_id: str,
    plan_summary_json: Optional[str],
    triggered_by_user_id: Optional[int],
) -> int:
    """Insert a running deployment row. Returns the new deployment id."""
    now = _now()
    async with get_db() as db:
        await db.execute(
            text(
                "INSERT INTO stack_deployments "
                "(stack_id, operation, status, job_id, plan_summary_json, "
                " triggered_by_user_id, started_at) "
                "VALUES (:sid, :op, 'running', :jid, :ps, :uid, :now)"
            ),
            {
                "sid": stack_id, "op": operation, "jid": job_id,
                "ps": plan_summary_json, "uid": triggered_by_user_id, "now": now,
            },
        )
        # Resolve id dialect-portably via the unique (job_id, started_at).
        r = await db.execute(
            text(
                "SELECT id FROM stack_deployments WHERE job_id = :jid AND started_at = :now "
                "ORDER BY id DESC LIMIT 1"
            ),
            {"jid": job_id, "now": now},
        )
        row = r.mappings().fetchone()
        await db.commit()
    return int(row["id"])


async def finish_deployment(
    deployment_id: int, status: str, error_text: Optional[str] = None
) -> None:
    async with get_db() as db:
        await db.execute(
            text(
                "UPDATE stack_deployments SET status = :st, finished_at = :now, "
                "error_text = :err WHERE id = :id"
            ),
            {"st": status, "now": _now(), "err": error_text, "id": deployment_id},
        )
        await db.commit()


async def list_deployments(stack_id: int) -> list[dict[str, Any]]:
    async with get_db() as db:
        result = await db.execute(
            text(
                "SELECT id, stack_id, operation, status, job_id, plan_summary_json, "
                "triggered_by_user_id, started_at, finished_at, error_text "
                "FROM stack_deployments WHERE stack_id = :sid "
                "ORDER BY started_at DESC, id DESC"
            ),
            {"sid": stack_id},
        )
        return [dict(r) for r in result.mappings().fetchall()]


async def _latest_deployment(db, stack_id: int) -> Optional[dict]:
    result = await db.execute(
        text(
            "SELECT operation, status, started_at, finished_at FROM stack_deployments "
            "WHERE stack_id = :sid ORDER BY started_at DESC, id DESC LIMIT 1"
        ),
        {"sid": stack_id},
    )
    row = result.mappings().fetchone()
    return dict(row) if row else None


# ── stack_deployed_resources sync ─────────────────────────────────────────────

def parse_state_resources(state_json: str) -> list[dict[str, Any]]:
    """Extract VM + LXC instances from a ``tofu state pull`` JSON document.

    Returns a list of ``{resource_name, node, vmid, kind}`` (``kind`` = ``vm`` or
    ``lxc``). Tolerant of malformed state (returns what it can). Only the bpg
    VM/container resource types are considered → drift/sync never touch foreign
    resource types. PROJ-86: containers are tracked the same way as VMs so the
    mutations-block + drift + detail UI work for LXC (AC-MIX-2 / AC-MUT-1).
    """
    out: list[dict[str, Any]] = []
    try:
        doc = json.loads(state_json)
    except (json.JSONDecodeError, TypeError):
        return out
    kind_by_type = {_VM_RESOURCE_TYPE: "vm", _CONTAINER_RESOURCE_TYPE: "lxc"}
    for res in doc.get("resources", []) or []:
        kind = kind_by_type.get(res.get("type"))
        if kind is None:
            continue
        res_name = res.get("name", "")
        for inst in res.get("instances", []) or []:
            attrs = inst.get("attributes", {}) or {}
            vmid = attrs.get("vm_id")
            node = attrs.get("node_name", "")
            if vmid is None:
                continue
            out.append(
                {"resource_name": res_name, "node": node, "vmid": int(vmid), "kind": kind}
            )
    return out


def parse_state_disks(state_json: str) -> dict[str, list[dict[str, Any]]]:
    """PROJ-82/86: extract the deployed disks per resource from ``tofu state pull``.

    Returns ``{resource_name: [{interface, size, datastore_id}]}``. Drives the
    state-vs-spec disk/volume diff (AC-REMOVE / AC-MOUNT-3). Tolerant of malformed
    state (returns what it can).

    VM (``proxmox_virtual_environment_vm``): ``attributes.disk`` is a list of
    objects each with an explicit ``interface`` (scsi0/scsi1/…); ``size`` is GiB.

    PROJ-86 LXC (``proxmox_virtual_environment_container``): the rootfs is
    ``attributes.disk`` (keyed as ``rootfs``) and the extra volumes are
    ``attributes.mount_point`` — a list with NO explicit index attribute, so they
    are keyed positionally (``mp0``, ``mp1`` …) to match ``_spec_disks_by_resource``.
    Mount sizes are unit strings (``"10G"``) → parsed tolerantly.
    """
    out: dict[str, list[dict[str, Any]]] = {}
    try:
        doc = json.loads(state_json)
    except (json.JSONDecodeError, TypeError):
        return out
    for res in doc.get("resources", []) or []:
        rtype = res.get("type")
        if rtype not in (_VM_RESOURCE_TYPE, _CONTAINER_RESOURCE_TYPE):
            continue
        res_name = res.get("name", "")
        disks: list[dict[str, Any]] = []
        for inst in res.get("instances", []) or []:
            attrs = inst.get("attributes", {}) or {}
            if rtype == _VM_RESOURCE_TYPE:
                raw_disk = attrs.get("disk")
                # bpg may serialize a single disk as a dict and several as a list.
                disk_list = raw_disk if isinstance(raw_disk, list) else (
                    [raw_disk] if isinstance(raw_disk, dict) else []
                )
                for d in disk_list:
                    if not isinstance(d, dict):
                        continue
                    iface = d.get("interface")
                    if not iface:
                        continue
                    disks.append({
                        "interface": str(iface),
                        "size": _parse_size_gib(d.get("size")),
                        "datastore_id": d.get("datastore_id", ""),
                    })
            else:  # LXC container — rootfs + positional mountpoints
                raw_disk = attrs.get("disk")
                disk_obj = (
                    raw_disk[0] if isinstance(raw_disk, list) and raw_disk
                    else (raw_disk if isinstance(raw_disk, dict) else None)
                )
                if isinstance(disk_obj, dict):
                    disks.append({
                        "interface": "rootfs",
                        "size": _parse_size_gib(disk_obj.get("size")),
                        "datastore_id": disk_obj.get("datastore_id", ""),
                    })
                raw_mps = attrs.get("mount_point")
                mp_list = raw_mps if isinstance(raw_mps, list) else (
                    [raw_mps] if isinstance(raw_mps, dict) else []
                )
                for i, mp in enumerate(mp_list):
                    if not isinstance(mp, dict):
                        continue
                    disks.append({
                        "interface": f"mp{i}",
                        "size": _parse_size_gib(mp.get("size")),
                        "datastore_id": mp.get("volume", ""),
                    })
        if res_name:
            out[res_name] = disks
    return out


async def sync_deployed_resources(
    stack_id: int,
    deployment_id: Optional[int],
    portal_node_id: int,
    resources: list[dict[str, Any]],
) -> None:
    """Replace the stack's deployed-resource rows from the tofu state (post-apply).

    delete-all-for-stack + re-insert in one transaction. The ``(portal_node_id,
    vmid)`` UNIQUE could otherwise collide with a *stale* row left behind by a
    prior deploy whose VM was already destroyed: OpenTofu only ever receives a
    VMID that Proxmox confirmed free, so any pre-existing row on the same pair is
    by definition obsolete and its ownership transfers to this stack. We
    therefore clear conflicting ``(portal_node_id, vmid)`` rows before inserting
    (covers stale rows from *other* stacks; same-stack rows are already gone via
    the stack-scoped delete above).
    """
    now = _now()
    async with get_db() as db:
        await db.execute(
            text("DELETE FROM stack_deployed_resources WHERE stack_id = :sid"),
            {"sid": stack_id},
        )
        for r in resources:
            await db.execute(
                text(
                    "DELETE FROM stack_deployed_resources "
                    "WHERE portal_node_id = :pnid AND vmid = :vmid"
                ),
                {"pnid": portal_node_id, "vmid": r["vmid"]},
            )
            await db.execute(
                text(
                    "INSERT INTO stack_deployed_resources "
                    "(stack_id, deployment_id, resource_name, portal_node_id, node, vmid, kind, created_at) "
                    "VALUES (:sid, :did, :rn, :pnid, :node, :vmid, :kind, :now)"
                ),
                {
                    "sid": stack_id, "did": deployment_id, "rn": r["resource_name"],
                    "pnid": portal_node_id, "node": r.get("node", ""),
                    "vmid": r["vmid"], "kind": r.get("kind", "vm"), "now": now,
                },
            )
        await db.commit()


async def clear_deployed_resources(stack_id: int) -> None:
    """Remove all deployed-resource rows for a stack (post-destroy)."""
    async with get_db() as db:
        await db.execute(
            text("DELETE FROM stack_deployed_resources WHERE stack_id = :sid"),
            {"sid": stack_id},
        )
        await db.commit()


async def list_deployed_resources(stack_id: int) -> list[dict[str, Any]]:
    async with get_db() as db:
        result = await db.execute(
            text(
                "SELECT resource_name, portal_node_id, node, vmid, kind, created_at "
                "FROM stack_deployed_resources WHERE stack_id = :sid ORDER BY resource_name"
            ),
            {"sid": stack_id},
        )
        return [dict(r) for r in result.mappings().fetchall()]


async def get_stack_for_vm(portal_node_id: int, vmid: int) -> Optional[dict]:
    """Return {stack_id, stack_name} if (portal_node_id, vmid) is stack-managed.

    Drives the mutations-block + VM-detail badge (AC-2B-MUT-1). Joins back to a
    non-deleted stack so a soft-deleted stack stops blocking its ex-VMs.
    """
    async with get_db() as db:
        result = await db.execute(
            text(
                "SELECT s.id AS stack_id, s.name AS stack_name "
                "FROM stack_deployed_resources r "
                "JOIN stacks s ON s.id = r.stack_id "
                "WHERE r.portal_node_id = :pnid AND r.vmid = :vmid "
                "AND s.deleted_at IS NULL LIMIT 1"
            ),
            {"pnid": portal_node_id, "vmid": vmid},
        )
        row = result.mappings().fetchone()
    return {"stack_id": row["stack_id"], "stack_name": row["stack_name"]} if row else None


async def get_stack_firewall_for_vm(portal_node_id: int, vmid: int) -> Optional[dict]:
    """Return {stack_id, stack_name} if this VM's firewall is stack-managed (AC-MUT-1).

    Stricter than ``get_stack_for_vm``: a stack-managed VM blocks PROJ-90 firewall
    mutations ONLY when its spec resource carries an active ``firewall:`` block
    (the stack owns the guest firewall). A stack VM without a firewall block keeps
    its editable PROJ-90 firewall (AC-MUT-2). Returns None otherwise. The grenze is
    "has a firewall block / has none" — only the FW endpoints, not the whole VM.
    """
    async with get_db() as db:
        result = await db.execute(
            text(
                "SELECT s.id AS stack_id, s.name AS stack_name, "
                "r.resource_name AS resource_name, s.yaml_text AS yaml_text "
                "FROM stack_deployed_resources r "
                "JOIN stacks s ON s.id = r.stack_id "
                "WHERE r.portal_node_id = :pnid AND r.vmid = :vmid "
                "AND s.deleted_at IS NULL LIMIT 1"
            ),
            {"pnid": portal_node_id, "vmid": vmid},
        )
        row = result.mappings().fetchone()
    if row is None:
        return None

    # Parse the stored spec and check whether the deployed (count-expanded) name
    # maps to a resource with a firewall block. Best-effort: a corrupt spec must
    # not crash a firewall edit (Core/Plus-grenze), so we fall back to "not
    # managed" rather than raising.
    try:
        from . import transpile
        from .schemas import StackCreateRequest
        from .validation import validate_request
        spec, _canonical, errors, _warnings = await validate_request(
            StackCreateRequest(yaml_text=row["yaml_text"])
        )
        if spec is None:
            return None
        spec_by_name: dict[str, object] = {}
        for r in spec.resources:
            for resolved in transpile._expanded_names(r):
                spec_by_name[resolved] = r
        res = spec_by_name.get(row["resource_name"])
        if res is not None and getattr(res, "firewall", None) is not None:
            return {"stack_id": row["stack_id"], "stack_name": row["stack_name"]}
    except Exception:  # pragma: no cover – defensive
        logger.warning(
            "PROJ-91: firewall mutations-block spec lookup failed (vmid=%s)", vmid
        )
    return None


async def bulk_stack_for_resources() -> dict[tuple[int, str], str]:
    """PROJ-75: single-SELECT map ``(portal_node_id, vmid)`` → ``stack_name``.

    Bulk equivalent of ``get_stack_for_vm`` for the topology view (Open-Point 7,
    avoids N× per-VM lookups). Only non-deleted stacks count, so a soft-deleted
    stack stops claiming its ex-VMs.
    """
    async with get_db() as db:
        result = await db.execute(
            text(
                "SELECT r.portal_node_id AS pnid, r.vmid AS vmid, s.name AS stack_name "
                "FROM stack_deployed_resources r "
                "JOIN stacks s ON s.id = r.stack_id "
                "WHERE s.deleted_at IS NULL"
            )
        )
        rows = result.mappings().fetchall()
    return {(r["pnid"], r["vmid"]): r["stack_name"] for r in rows}


async def list_active_stack_names() -> list[str]:
    """PROJ-75: distinct non-deleted stack names for the topology filter dropdown."""
    async with get_db() as db:
        result = await db.execute(
            text("SELECT name FROM stacks WHERE deleted_at IS NULL ORDER BY name")
        )
        return [r["name"] for r in result.mappings().fetchall()]


async def list_active_stack_yaml() -> list[dict]:
    """PROJ-75: ``[{name, yaml_text}]`` for non-deleted stacks.

    The topology network service parses these (best-effort) to cross-reference
    stack-owned bridges (PROJ-87) — there is no tracking table for them.
    """
    async with get_db() as db:
        result = await db.execute(
            text("SELECT name, yaml_text FROM stacks WHERE deleted_at IS NULL")
        )
        return [dict(r) for r in result.mappings().fetchall()]


# ── Drift state ───────────────────────────────────────────────────────────────

async def set_drift_state(stack_id: int, drift_state: str) -> None:
    """Persist the external drift result (in_sync / out_of_sync)."""
    async with get_db() as db:
        await db.execute(
            text(
                "UPDATE stacks SET last_drift_state = :ds, last_drift_at = :now WHERE id = :sid"
            ),
            {"ds": drift_state, "now": _now(), "sid": stack_id},
        )
        await db.commit()


# ── Deployment-state derivation (Tech-Design Open Point 4) ────────────────────

async def derive_deployment_state(stack_row) -> str:
    """Compute the UI deployment badge for a stack.

    States: not_deployed / deploying / deployed / partial / destroying /
    destroyed / out_of_sync / error.
    """
    stack_id = stack_row["id"]
    async with get_db() as db:
        latest = await _latest_deployment(db, stack_id)
        rcount_result = await db.execute(
            text("SELECT COUNT(*) AS c FROM stack_deployed_resources WHERE stack_id = :sid"),
            {"sid": stack_id},
        )
        deployed_count = rcount_result.mappings().fetchone()["c"]

    if latest is None:
        return "not_deployed"

    op = latest["operation"]
    status = latest["status"]

    if status == "running":
        return "deploying" if op == "apply" else "destroying"
    if status == "failed":
        return "error"
    if status == "partial":
        return "partial"

    # status == "success"
    if op == "destroy":
        return "destroyed"

    # successful apply → check drift + edit-after-deploy
    if deployed_count == 0:
        # apply succeeded but nothing tracked (e.g. empty stack) → treat as deployed
        return "deployed"
    if stack_row["last_drift_state"] == "out_of_sync":
        return "out_of_sync"
    finished_at = latest.get("finished_at") or ""
    updated_at = stack_row["updated_at"] or ""
    # ISO-UTC strings sort lexicographically → edit after the last apply = out_of_sync.
    if finished_at and updated_at > finished_at:
        return "out_of_sync"
    return "deployed"
