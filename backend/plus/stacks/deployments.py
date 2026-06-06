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
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text

from backend.db.database import get_db

logger = logging.getLogger(__name__)

# bpg resource type in the OpenTofu state.
_VM_RESOURCE_TYPE = "proxmox_virtual_environment_vm"


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
    """Extract VM instances from a ``tofu state pull`` JSON document.

    Returns a list of ``{resource_name, node, vmid}``. Tolerant of malformed
    state (returns what it can). Only ``proxmox_virtual_environment_vm`` is
    considered → drift/sync never touch foreign resource types.
    """
    out: list[dict[str, Any]] = []
    try:
        doc = json.loads(state_json)
    except (json.JSONDecodeError, TypeError):
        return out
    for res in doc.get("resources", []) or []:
        if res.get("type") != _VM_RESOURCE_TYPE:
            continue
        res_name = res.get("name", "")
        for inst in res.get("instances", []) or []:
            attrs = inst.get("attributes", {}) or {}
            vmid = attrs.get("vm_id")
            node = attrs.get("node_name", "")
            if vmid is None:
                continue
            out.append({"resource_name": res_name, "node": node, "vmid": int(vmid)})
    return out


async def sync_deployed_resources(
    stack_id: int,
    deployment_id: Optional[int],
    portal_node_id: int,
    resources: list[dict[str, Any]],
) -> None:
    """Replace the stack's deployed-resource rows from the tofu state (post-apply).

    delete-all-for-stack + re-insert in one transaction. ``(portal_node_id, vmid)``
    UNIQUE ⇒ if a VMID already belongs to another stack the insert fails — that
    would be a "1 engine per resource" violation surfaced as an error.
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
                    "INSERT INTO stack_deployed_resources "
                    "(stack_id, deployment_id, resource_name, portal_node_id, node, vmid, kind, created_at) "
                    "VALUES (:sid, :did, :rn, :pnid, :node, :vmid, 'vm', :now)"
                ),
                {
                    "sid": stack_id, "did": deployment_id, "rn": r["resource_name"],
                    "pnid": portal_node_id, "node": r.get("node", ""),
                    "vmid": r["vmid"], "now": now,
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
