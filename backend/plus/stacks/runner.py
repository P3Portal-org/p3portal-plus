# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-76 Phase 2b: stack apply/destroy job runner (background task).

State machine for one deploy/destroy run:

  jobs→running → ``tofu apply <planfile>`` (streamed to /app/data/logs/{job}.log,
  the existing job-log WebSocket tails it) → pull state → sync
  ``stack_deployed_resources`` → finish ``stack_deployments`` (success/partial/
  failed) → jobs→success/failed → post-apply drift plan (AC-2B-DEP-5) → audit.

The per-stack lock (Phase 2a) is acquired by ``deploy_service.start_stack_job``
and released here in ``finally`` (asyncio.Lock is not owner-bound). Token is
injected via env by the engine and never reaches the log (Open Point 11).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

from backend.core.config import settings
from backend.db.database import get_db
from backend.services.audit_service import write_audit_log
from backend.services.nodes_service import NodeRow

from . import engine
from .deployments import (
    clear_deployed_resources,
    finish_deployment,
    parse_state_resources,
    set_drift_state,
    sync_deployed_resources,
)

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _set_job(job_id: str, **cols) -> None:
    assignments = ", ".join(f"{k} = :{k}" for k in cols)
    cols["id"] = job_id
    async with get_db() as db:
        await db.execute(
            text(f"UPDATE jobs SET {assignments} WHERE id = :id"), cols
        )
        await db.commit()


async def _pull_state_resources(stack_id: int, node: NodeRow) -> list[dict]:
    """Run ``tofu state pull`` and parse the VM instances (best-effort)."""
    try:
        rc, out, _err = await engine.run_tofu(["state", "pull"], str(stack_id), node)
        if rc != 0:
            return []
        return parse_state_resources(out)
    except Exception as exc:  # pragma: no cover – defensive
        logger.warning("PROJ-76: state pull failed for stack %s: %s", stack_id, exc)
        return []


async def run_stack_job(
    job_id: str,
    stack_id: int,
    deployment_id: int,
    operation: str,
    node: NodeRow,
    triggered_by: str,
    lock: asyncio.Lock,
) -> None:
    """Background runner for a stack apply/destroy. Releases ``lock`` on exit."""
    log_dir = Path(settings.data_dir) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{job_id}.log"

    await _set_job(job_id, status="running", started_at=_now(), log_path=str(log_path))
    await write_audit_log(
        f"stack_{operation}_started", username=triggered_by,
        detail=f"stack_id={stack_id} job_id={job_id[:8]}",
    )
    log_path.write_text(
        f"[p3] stack {operation} starting (stack_id={stack_id})\n", encoding="utf-8"
    )

    job_status = "failed"
    deploy_status = "failed"
    error_text: str | None = None

    try:
        # apply executes the exact reviewed plan; destroy's plan was built with -destroy.
        apply_args = ["apply", "-input=false", "-no-color", "plan.tfplan"]
        rc = await engine.run_tofu_streaming(
            apply_args, str(stack_id), node, log_path=log_path
        )

        if operation == "apply":
            resources = await _pull_state_resources(stack_id, node)
            await sync_deployed_resources(stack_id, deployment_id, node.id, resources)
            if rc == 0:
                job_status, deploy_status = "success", "success"
            elif resources:
                job_status, deploy_status = "failed", "partial"
                error_text = f"tofu apply exited with code {rc} (partial)"
            else:
                job_status, deploy_status = "failed", "failed"
                error_text = f"tofu apply exited with code {rc}"
        else:  # destroy
            if rc == 0:
                await clear_deployed_resources(stack_id)
                job_status, deploy_status = "success", "success"
            else:
                resources = await _pull_state_resources(stack_id, node)
                await sync_deployed_resources(stack_id, deployment_id, node.id, resources)
                job_status, deploy_status = "failed", "failed"
                error_text = f"tofu destroy exited with code {rc}"
    except Exception as exc:  # pragma: no cover – defensive
        logger.exception("PROJ-76: stack %s job %s crashed", operation, job_id)
        error_text = str(exc)[:1000]
        try:
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(f"[p3] runner error: {error_text}\n")
        except Exception:
            pass
    finally:
        # Post-apply drift (AC-2B-DEP-5): a successful apply means reality matches.
        if operation == "apply" and deploy_status == "success":
            try:
                await set_drift_state(stack_id, "in_sync")
            except Exception:
                pass
        await finish_deployment(deployment_id, deploy_status, error_text)
        await _set_job(job_id, status=job_status, finished_at=_now())
        if lock.locked():
            lock.release()

    audit_event = {
        "success": f"stack_{operation}_succeeded",
        "partial": f"stack_{operation}_partial",
        "failed": f"stack_{operation}_failed",
    }.get(deploy_status, f"stack_{operation}_failed")
    if operation == "destroy" and deploy_status == "success":
        audit_event = "stack_destroyed"
    await write_audit_log(
        audit_event, username=triggered_by,
        detail=f"stack_id={stack_id} job_id={job_id[:8]} status={deploy_status}",
    )
