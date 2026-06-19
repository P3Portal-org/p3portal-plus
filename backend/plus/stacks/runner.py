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


async def _cloud_init_secrets(stack_id: int) -> list[str]:
    """Collect the active cloud-init passwords for live-log masking (PROJ-85 OBS-1).

    Defense-in-depth: bpg marks ``initialization.user_account.password`` as
    sensitive (tofu prints ``(sensitive value)``), but masking it here too
    guarantees it never reaches the live job-log regardless of provider behavior
    — the same belt-and-suspenders stance as the bpg-token masking. Best-effort:
    a cloud-init/decrypt problem must never fail the apply (the reviewed plan
    already carries the real value; gate=False skips the IP/lockout re-check).
    """
    try:
        from . import cloud_init
        spec = await cloud_init._load_spec(stack_id)
        if spec is None:
            return []
        resolved = await cloud_init.resolve_for_transpile(stack_id, spec, gate=False)
        return list({r.password for r in resolved.values() if r.password})
    except Exception:  # pragma: no cover – defensive
        logger.warning(
            "PROJ-85: could not collect cloud-init secrets for log masking (stack %s)",
            stack_id,
        )
        return []


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


async def _commit_sdn(node: NodeRow) -> None:
    """Trigger the cluster-wide SDN apply (``PUT /cluster/sdn``) via the tofu token.

    PROJ-89: the same identity that staged the SDN objects via bpg commits them
    (it carries ``SDN.Allocate``). Per-node client (feedback_per_node_proxmox_client).
    On apply this is an idempotent safety commit (re-apply staleness); on destroy
    it is THE removal commit that flushes the staged deletions (the applier's
    ``on_destroy=false`` left them pending to dodge #2212). Raises on failure so
    the caller can decide (warn on apply, fail on destroy).
    """
    from backend.services.proxmox import ProxmoxAuth, ProxmoxClient

    auth = ProxmoxAuth(
        kind="token", value=node.tofu_token_id, secret=node.tofu_token_secret,
    )
    client = ProxmoxClient(base_url=node.url, verify_ssl=node.verify_ssl)
    await client.apply_sdn(auth)


def _append_log(log_path: Path, msg: str) -> None:
    try:
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(msg if msg.endswith("\n") else msg + "\n")
    except Exception:  # pragma: no cover – defensive
        pass


async def _commit_firewall_after_apply(stack_id: int, node: NodeRow, resources: list[dict]) -> None:
    """PROJ-91: apply the declarative stack firewall after a successful apply.

    Loads the spec, then sets the stack SGs + per-guest options/rules over the
    PROJ-90 API (Pfad B). Raises on failure so the runner surfaces it (AC-RBAC-2).
    """
    from . import cloud_init, firewall_commit
    spec = await cloud_init._load_spec(stack_id)
    if spec is None:
        return
    await firewall_commit.apply_firewall(node, stack_id, spec, resources)


async def run_stack_job(
    job_id: str,
    stack_id: int,
    deployment_id: int,
    operation: str,
    node: NodeRow,
    triggered_by: str,
    lock: asyncio.Lock,
    sdn_lock: asyncio.Lock | None = None,
    is_sdn: bool = False,
    is_firewall: bool = False,
) -> None:
    """Background runner for a stack apply/destroy. Releases the lock(s) on exit.

    PROJ-89: when ``is_sdn`` the run also triggers the cluster-wide SDN apply
    (``apply_sdn``) — an idempotent safety commit after a successful apply
    (re-apply staleness; non-fatal) and THE removal commit after a successful
    destroy (fatal if it fails: the deletion stayed pending). ``sdn_lock`` (the
    global ``_SDN_APPLY_LOCK``) is released last, after the per-stack lock.

    PROJ-91: when ``is_firewall`` the run also commits the declarative firewall —
    after a successful apply the stack SGs + per-guest options/rules are set over
    the PROJ-90 API (Pfad B; a failure marks the run ``partial`` so it is not a
    silent partial success, AC-RBAC-2), and after a successful destroy the
    stack-prefixed cluster SGs are removed (a failure marks the run ``failed``,
    Edge 6). No extra lock — the firewall is per-guest/live.
    """
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
        # PROJ-85 OBS-1: mask the active cloud-init passwords in the live job-log.
        ci_secrets = await _cloud_init_secrets(stack_id)
        rc = await engine.run_tofu_streaming(
            apply_args, str(stack_id), node, log_path=log_path,
            extra_secrets=ci_secrets,
        )

        if operation == "apply":
            resources = await _pull_state_resources(stack_id, node)
            await sync_deployed_resources(stack_id, deployment_id, node.id, resources)
            if rc == 0:
                job_status, deploy_status = "success", "success"
                # PROJ-89: idempotent safety commit (re-apply staleness — the
                # applier's on_create fires only on first creation). Non-fatal:
                # the applier already committed the create for the first deploy.
                if is_sdn:
                    try:
                        await _commit_sdn(node)
                    except Exception as exc:  # pragma: no cover – best-effort
                        _append_log(log_path, f"[p3] SDN safety apply warning: {exc}")
                        logger.warning("PROJ-89: SDN safety apply failed (stack %s): %s", stack_id, exc)
                # PROJ-91: commit the declarative firewall (Pfad B) — the NIC flag
                # is already live from tofu apply, so the guests exist + their NICs
                # are firewall-enabled. A failure (e.g. missing token privilege)
                # marks the run ``partial`` so it is not a silent partial success
                # (AC-RBAC-2); the VMs stay (re-deploy is idempotent, OP6).
                if is_firewall:
                    try:
                        await _commit_firewall_after_apply(stack_id, node, resources)
                    except Exception as exc:
                        job_status, deploy_status = "failed", "partial"
                        error_text = f"firewall commit failed: {exc}"
                        _append_log(log_path, f"[p3] {error_text}")
                        logger.warning("PROJ-91: firewall commit failed (stack %s): %s", stack_id, exc)
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
                # PROJ-89: removal commit (AC-LC-1) — the applier left the SDN
                # deletions pending (on_destroy=false, dodges #2212), so P3 flushes
                # them with one cluster-wide apply. Fatal if it fails (SDN leak).
                if is_sdn:
                    try:
                        await _commit_sdn(node)
                    except Exception as exc:
                        job_status, deploy_status = "failed", "failed"
                        error_text = f"SDN removal apply failed: {exc}"
                        _append_log(log_path, f"[p3] {error_text} (SDN deletion stayed pending)")
                        logger.warning("PROJ-89: SDN removal apply failed (stack %s): %s", stack_id, exc)
                # PROJ-91: the guests (and their firewall rules/options) are gone;
                # only the stack-prefixed cluster SGs remain → remove them (AC-LC-2).
                # A failure (Edge 6: a foreign guest still references an SG) marks
                # the run failed so the leftover SG is surfaced, not swallowed.
                if is_firewall:
                    try:
                        from . import firewall_commit
                        await firewall_commit.destroy_stack_security_groups(node, stack_id)
                    except Exception as exc:
                        job_status, deploy_status = "failed", "failed"
                        error_text = f"firewall security-group cleanup failed: {exc}"
                        _append_log(log_path, f"[p3] {error_text}")
                        logger.warning("PROJ-91: firewall SG cleanup failed (stack %s): %s", stack_id, exc)
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
        # Release reverse to the acquire order (per-stack first, SDN last).
        if lock.locked():
            lock.release()
        if sdn_lock is not None and sdn_lock.locked():
            sdn_lock.release()

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
