# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-50: Handler-Registry – Mapping action_type → execute_handler.

Der Approval-Service ist agnostisch gegenüber der konkreten Aktion.
Jeder Handler bekommt (approval: dict, full_payload: dict, actor_username: str)
und gibt optional eine job_id zurück (None bei synchronen Operationen).
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Callable, Awaitable, Any

from sqlalchemy import text

from backend.db.database import get_db
from backend.services.audit_service import write_audit_log

logger = logging.getLogger(__name__)

HandlerFn = Callable[[dict, dict, str], Awaitable[str | None]]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── playbook_run ──────────────────────────────────────────────────────────────

async def _handle_playbook_run(
    approval: dict,
    full_payload: dict,
    actor_username: str,
) -> str | None:
    """Startet einen Ansible-Job nach Freigabe."""
    from backend.services.ansible_runner_service import run_ansible_job
    from backend.core.config import settings

    playbook = approval["action_target"]
    params = {k: v for k, v in full_payload.items() if k not in ("playbook", "action_type")}

    job_id = str(uuid.uuid4())
    now = _now()

    async with get_db() as db:
        await db.execute(
            text("""
                INSERT INTO jobs (id, type, playbook, status, created_at, username, params)
                VALUES (:id, 'ansible', :playbook, 'pending', :now, :username, :params)
            """),
            {
                "id": job_id, "playbook": playbook, "now": now,
                "username": actor_username,
                "params": json.dumps(params),
            },
        )
        await db.commit()

    asyncio.create_task(run_ansible_job(job_id, playbook, params, "operator"))
    logger.info("PROJ-50: playbook_run handler: job_id=%s playbook=%s", job_id, playbook)
    return job_id


# ── packer_build ──────────────────────────────────────────────────────────────

async def _handle_packer_build(
    approval: dict,
    full_payload: dict,
    actor_username: str,
) -> str | None:
    """Startet einen Packer-Build-Job nach Freigabe."""
    from backend.services.packer_runner_service import run_packer_job

    template_name = approval["action_target"]
    params = {k: v for k, v in full_payload.items() if k not in ("action_type",)}

    job_id = str(uuid.uuid4())
    now = _now()

    async with get_db() as db:
        await db.execute(
            text("""
                INSERT INTO jobs (id, type, playbook, status, created_at, username, params)
                VALUES (:id, 'packer', :tmpl, 'pending', :now, :username, :params)
            """),
            {
                "id": job_id, "tmpl": template_name, "now": now,
                "username": actor_username,
                "params": json.dumps(params),
            },
        )
        await db.commit()

    asyncio.create_task(run_packer_job(job_id, template_name, params))
    logger.info("PROJ-50: packer_build handler: job_id=%s template=%s", job_id, template_name)
    return job_id


# ── vm_delete / lxc_delete / template_delete ──────────────────────────────────

async def _handle_vm_delete(
    approval: dict,
    full_payload: dict,
    actor_username: str,
) -> str | None:
    """Löscht eine VM nach Freigabe via Proxmox API."""
    node_id = full_payload.get("node_id")
    vmid = full_payload.get("vmid")
    resource_type = full_payload.get("resource_type", "vm")

    if not node_id or not vmid:
        raise ValueError("vm_delete: node_id und vmid sind Pflicht")

    try:
        from backend.services.cluster_service import delete_vm as proxmox_delete_vm
        await proxmox_delete_vm(node_id=node_id, vmid=vmid, resource_type=resource_type)
    except Exception as exc:
        logger.error("PROJ-50: vm_delete handler fehlgeschlagen: %s", exc)
        raise

    # Owner-Cleanup
    try:
        from backend.features.owners.cleanup import on_resource_deleted
        await on_resource_deleted(resource_type, node_id, vmid, actor_username)
    except Exception as exc:
        logger.warning("PROJ-50: vm_delete Owner-Cleanup fehlgeschlagen: %s", exc)

    await write_audit_log(
        "vm_deleted", actor_username, "local",
        detail=f"Approval-Delete: {resource_type} vmid={vmid} node_id={node_id}"
    )
    return None


async def _handle_lxc_delete(
    approval: dict,
    full_payload: dict,
    actor_username: str,
) -> str | None:
    return await _handle_vm_delete(approval, {**full_payload, "resource_type": "lxc"}, actor_username)


async def _handle_template_delete(
    approval: dict,
    full_payload: dict,
    actor_username: str,
) -> str | None:
    return await _handle_vm_delete(approval, {**full_payload, "resource_type": "vm"}, actor_username)


# ── owner_delete_request ───────────────────────────────────────────────────────

async def _handle_owner_delete_request(
    approval: dict,
    full_payload: dict,
    actor_username: str,
) -> str | None:
    """Führt den finalen VM-Delete + Owner-Cleanup nach Freigabe aus."""
    return await _handle_vm_delete(approval, full_payload, actor_username)


# ── owner_adopt_request ────────────────────────────────────────────────────────

async def _handle_owner_adopt_request(
    approval: dict,
    full_payload: dict,
    actor_username: str,
) -> str | None:
    """Trägt den Requester als Owner ein nach Freigabe."""
    from backend.features.owners.service import add_owner

    requester_user_id = approval["requester_user_id"]
    node_id = full_payload.get("node_id")
    vmid = full_payload.get("vmid")
    resource_type = full_payload.get("resource_type", "vm")

    if not (requester_user_id and node_id and vmid):
        raise ValueError("owner_adopt_request: requester_user_id, node_id, vmid sind Pflicht")

    await add_owner(
        resource_type=resource_type,
        node_id=node_id,
        vmid=vmid,
        user_id=requester_user_id,
        source="adopt",
        assigned_by_user_id=None,
        actor_username=actor_username,
    )
    logger.info(
        "PROJ-50: owner_adopt_request: user_id=%s vmid=%s node_id=%s",
        requester_user_id, vmid, node_id,
    )
    return None


# ── config_snapshot_restore ──────────────────────────────────────────────────

async def _handle_config_snapshot_restore(
    approval: dict,
    full_payload: dict,
    actor_username: str,
) -> str | None:
    """Führt einen Config-Snapshot-Restore nach Freigabe durch (PROJ-74)."""
    from backend.plus.config_snapshots.service import restore_snapshot

    snapshot_id = full_payload.get("snapshot_id", "")
    etag = full_payload.get("etag", "")
    vm_name_confirm = full_payload.get("vm_name_confirm", "")
    create_pre = full_payload.get("create_pre_restore_snapshot", True)
    restart = full_payload.get("restart_after_restore", False)
    requester_user_id: int | None = approval.get("requester_user_id")

    await restore_snapshot(
        snapshot_id=snapshot_id,
        etag=etag,
        vm_name_confirm=vm_name_confirm,
        create_pre_restore_snapshot=bool(create_pre),
        restart_after_restore=bool(restart),
        username=actor_username,
        user_id=requester_user_id,
    )
    return None


# ── Registry ─────────────────────────────────────────────────────────────────

async def _handle_scheduled_job_create_auto_config_snapshot(
    approval: dict,
    full_payload: dict,
    actor_username: str,
) -> str | None:
    """PROJ-77: Aktiviert einen pending Scheduled Job nach Approval (Config-Snapshot-Auto-Job).

    Job wurde mit ``active=0`` und scheduled_job_approval_status='pending_approval'
    angelegt. Approve setzt ``active=1`` + berechnet ``next_run_at``.
    """
    from datetime import datetime, timezone
    from croniter import croniter

    from backend.db.database import get_db
    from sqlalchemy import text

    sj_id = full_payload.get("sj_id") or approval.get("action_target", "")
    if not sj_id:
        return None
    now = datetime.now(timezone.utc).isoformat()
    async with get_db() as db:
        row = await db.execute(
            text("SELECT cron_expression FROM scheduled_jobs WHERE id = :id"),
            {"id": sj_id},
        )
        rec = row.fetchone()
        if not rec:
            return None
        try:
            next_run = croniter(rec[0], datetime.now()).get_next(datetime).isoformat()
        except Exception:
            next_run = None
        await db.execute(
            text(
                "UPDATE scheduled_jobs SET active = 1, next_run_at = :next, "
                "updated_at = :now WHERE id = :id"
            ),
            {"next": next_run, "now": now, "id": sj_id},
        )
        await db.commit()
    return sj_id


async def _handle_scheduled_job_create_auto_vm_snapshot(
    approval: dict,
    full_payload: dict,
    actor_username: str,
) -> str | None:
    """PROJ-77: Pendant zu _handle_scheduled_job_create_auto_config_snapshot."""
    return await _handle_scheduled_job_create_auto_config_snapshot(
        approval, full_payload, actor_username,
    )


HANDLER_REGISTRY: dict[str, HandlerFn] = {
    "playbook_run":              _handle_playbook_run,
    "packer_build":              _handle_packer_build,
    "vm_delete":                 _handle_vm_delete,
    "lxc_delete":                _handle_lxc_delete,
    "template_delete":           _handle_template_delete,
    "owner_delete_request":      _handle_owner_delete_request,
    "owner_adopt_request":       _handle_owner_adopt_request,
    "config_snapshot_restore":   _handle_config_snapshot_restore,
    # PROJ-77: optionale Approval-Integration (Default-aus, Admin muss Regel anlegen)
    "scheduled_job_create_auto_config_snapshot": _handle_scheduled_job_create_auto_config_snapshot,
    "scheduled_job_create_auto_vm_snapshot":     _handle_scheduled_job_create_auto_vm_snapshot,
}


async def execute_handler(
    action_type: str,
    approval: dict,
    full_payload: dict,
    actor_username: str,
) -> str | None:
    """Ruft den Handler für den action_type auf und gibt optional job_id zurück."""
    handler = HANDLER_REGISTRY.get(action_type)
    if handler is None:
        raise ValueError(f"Kein Handler für action_type={action_type!r} registriert")
    return await handler(approval, full_payload, actor_username)
