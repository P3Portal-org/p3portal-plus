# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-76 Phase 2b: deploy orchestration + gates (RBAC/Quota/Token/Installation/Lock).

Flow (Tech-Design E):

  POST /plan   → ``prepare_plan``    : gate → transpile → tofu init/validate/plan
                                       → in-memory plan-token (TTL, bound to etag)
  POST /deploy → ``start_stack_job`` : re-gate → consume plan-token (etag 409)
                                       → lock (409) → job-row → background runner
  POST /destroy: same with operation='destroy'
  GET/POST /drift: ``run_drift``     : read-only plan → drift over stack-VMs only

All gate failures (403/412/409/4xx) happen **before** any state-mutating tofu
run. The token is injected via env by the engine and never appears in the plan
or state (Phase 2a). ``count > 1`` resources are pre-expanded by the transpiler.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import text

from backend.core.plus_protocol import plus_behavior
from backend.db.database import get_db
from backend.services.audit_service import write_audit_log
from backend.services.nodes_service import NodeRow, get_node_for_proxmox_name

from . import engine, transpile
from .deployments import create_deployment, set_drift_state
from .permissions import can_deploy_stack
from .preview import resolve_resources
from .schemas import PlanResource, PlanResponse, PlanSummary
from .validation import validate_request
from .schemas import StackCreateRequest

logger = logging.getLogger(__name__)

# In-memory plan tokens (single-container reality, Muster Stack-Lock).
# token → {stack_id, etag, operation, summary, expires_at, node_id}
_PLAN_TOKENS: dict[str, dict] = {}
_PLAN_TTL = timedelta(minutes=15)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Spec / node resolution ────────────────────────────────────────────────────

async def _spec_of(stack_row):
    """Parse the stack's stored yaml_text into a validated StackSpec."""
    spec, _canonical, errors, _warnings = await validate_request(
        StackCreateRequest(yaml_text=stack_row["yaml_text"])
    )
    if spec is None:
        raise HTTPException(status_code=422, detail={"errors": errors})
    return spec


async def resolve_target_node(spec) -> NodeRow:
    """Resolve all referenced Proxmox nodes to exactly one Portal-Node (AC-2b-13).

    A stack deploys against one Proxmox installation = one provider endpoint +
    one tofu-token. Multiple physical cluster members (same endpoint) are fine;
    nodes spread across independent installations are a validation error.
    Raises 4xx **before** any plan when unresolvable or token missing.
    """
    if not spec.resources:
        raise HTTPException(status_code=422, detail="stack_has_no_resources")

    node_rows: dict[int, NodeRow] = {}
    for r in spec.resources:
        node = await get_node_for_proxmox_name(r.node)
        if node is None:
            raise HTTPException(
                status_code=422,
                detail=f"node_not_resolvable:{r.node}",
            )
        node_rows[node.id] = node

    if len(node_rows) != 1:
        raise HTTPException(
            status_code=422,
            detail="multiple_installations_not_supported",
        )

    node = next(iter(node_rows.values()))
    if not node.tofu_token_id or not node.tofu_token_secret:
        raise HTTPException(
            status_code=400,
            detail=f"node_not_stack_deploy_capable:{node.name}",
        )
    return node


def _resource_totals(spec) -> tuple[int, int, int, int]:
    """Sum the resolved resources: (vm_count, cores, ram_mb, disk_gb)."""
    vm_count = cores = ram = disk = 0
    for r in spec.resources:
        n = r.count
        vm_count += n
        cores += r.cores * n
        ram += r.memory * n
        disk += r.disk * n
    return vm_count, cores, ram, disk


async def _resolve_pool_id(pool_name: str) -> Optional[int]:
    async with get_db() as db:
        result = await db.execute(
            text("SELECT id FROM pools WHERE name = :n"), {"n": pool_name}
        )
        row = result.mappings().fetchone()
    return int(row["id"]) if row else None


# ── Gates (RBAC 403 / Quota 412) ──────────────────────────────────────────────

async def assert_deploy_allowed(
    stack_row, spec, node: NodeRow, user_role: str, user_id: Optional[int], username: str,
) -> None:
    """RBAC (403) + pool-quota (412) gate before any plan (AC-2B-RBAC)."""
    allowed = await can_deploy_stack(user_role, user_id, stack_row["owner_user_id"], node.id)
    if not allowed:
        await write_audit_log(
            "stack_deploy_blocked_rbac", username=username,
            detail=f"stack_id={stack_row['id']} node_id={node.id}",
        )
        raise HTTPException(status_code=403, detail="stack_deploy_forbidden")

    # Pool-quota only when a pool is referenced (any resource).
    pool_name = next((r.pool for r in spec.resources if r.pool), None)
    if not pool_name:
        return
    pool_id = await _resolve_pool_id(pool_name)
    if pool_id is None:
        return  # unknown pool → already a validation warning; don't hard-block
    vm_count, cores, ram, disk = _resource_totals(spec)
    quota = await plus_behavior.check_pool_quota_bulk(
        user_id or 0, pool_id, vm_count, cores, ram, disk
    )
    if not quota.allowed:
        await write_audit_log(
            "stack_deploy_blocked_quota", username=username,
            detail=f"stack_id={stack_row['id']} pool_id={pool_id} exceeded={quota.exceeded}",
        )
        raise HTTPException(
            status_code=412,
            detail={"error": "pool_quota_exceeded", "quota": quota.model_dump()},
        )


# ── Template VMID resolution (Proxmox; mockable seam) ─────────────────────────

async def resolve_template_vmids(node: NodeRow, spec) -> dict[str, int]:
    """Resolve each referenced template name → its VMID on the node's cluster.

    Read-only lookup via the node's viewer token. A missing template raises
    HTTP 422 (Edge 2/5). Isolated so tests can mock it.
    """
    from backend.services.proxmox import ProxmoxAuth, ProxmoxClient

    auth = ProxmoxAuth(
        kind="token",
        value=node.viewer_token_id or node.token_id,
        secret=node.viewer_token_secret or node.token_secret,
    )
    client = ProxmoxClient(base_url=node.url, verify_ssl=node.verify_ssl)
    try:
        resources = await client.get_cluster_resources_v2(auth, "vm")
    except Exception as exc:  # pragma: no cover – network
        raise HTTPException(status_code=502, detail="cluster_unreachable") from exc

    by_name: dict[str, int] = {}
    for r in resources:
        if int(r.get("template", 0)) == 1:
            name = r.get("name")
            if name:
                by_name[str(name)] = int(r.get("vmid"))

    wanted = {r.template for r in spec.resources}
    missing = sorted(wanted - set(by_name))
    if missing:
        raise HTTPException(status_code=422, detail=f"template_not_found:{','.join(missing)}")
    return {t: by_name[t] for t in wanted}


def _wanted_explicit_vmids(spec) -> dict[int, str]:
    """Collect explicitly pinned VMIDs → resource name (count → base+offset)."""
    wanted: dict[int, str] = {}
    for r in spec.resources:
        if r.vmid is None:
            continue
        names = [r.name] if r.count <= 1 else [f"{r.name}-{i}" for i in range(1, r.count + 1)]
        for offset, nm in enumerate(names):
            wanted[r.vmid + offset] = nm
    return wanted


def suggest_free_vmids(spec, occupied: set[int]) -> list[dict]:
    """Propose the next free base VMID for every pinned resource whose range collides.

    ``occupied`` = VMIDs taken on the cluster (already excluding this stack's own).
    Walks the resources in order; a resource keeps its VMID range when free, else
    gets the next base ``B`` so that ``B..B+count-1`` is free and does not clash
    with ranges already assigned/kept in this same pass. Mirrors the Provisioning
    "+1 until free" behaviour, count-aware. Returns
    ``[{index, name, old_vmid, new_vmid}]`` only for the resources that moved.
    """
    reserved: set[int] = set()
    needs: list[tuple[int, object]] = []
    # Pass 1: keep every range that is free (and doesn't clash with one already kept).
    for idx, r in enumerate(spec.resources):
        if r.vmid is None:
            continue
        rng = set(range(r.vmid, r.vmid + r.count))
        if rng & occupied or rng & reserved:
            needs.append((idx, r))
        else:
            reserved |= rng
    # Pass 2: reassign only the colliding ones to the next free window.
    suggestions: list[dict] = []
    for idx, r in needs:
        b = r.vmid
        while (set(range(b, b + r.count)) & occupied) or (set(range(b, b + r.count)) & reserved):
            b += 1
        suggestions.append({"index": idx, "name": r.name, "old_vmid": r.vmid, "new_vmid": b})
        reserved |= set(range(b, b + r.count))
    return suggestions


async def assert_explicit_vmids_free(stack_id: int, node: NodeRow, spec) -> None:
    """Reject a deploy when an explicitly pinned VMID is already taken (Edge: VMID-Kollision).

    Only runs when the stack actually pins VMIDs (the auto-assign default skips
    the cluster call entirely). VMIDs this stack already manages are excluded so
    a re-deploy of an unchanged stack does not false-positive on its own VMs.
    On conflict raises HTTP 422 with a structured detail
    ``{error, taken, suggestions}`` so the UI can offer "pick next free VMID".
    """
    wanted = _wanted_explicit_vmids(spec)
    if not wanted:
        return

    from backend.services.proxmox import ProxmoxAuth, ProxmoxClient
    from . import deployments

    auth = ProxmoxAuth(
        kind="token",
        value=node.viewer_token_id or node.token_id,
        secret=node.viewer_token_secret or node.token_secret,
    )
    client = ProxmoxClient(base_url=node.url, verify_ssl=node.verify_ssl)
    try:
        resources = await client.get_cluster_resources_v2(auth, "vm")
    except Exception as exc:  # pragma: no cover – network
        raise HTTPException(status_code=502, detail="cluster_unreachable") from exc
    used_vmids = {int(r["vmid"]) for r in resources if r.get("vmid") is not None}

    # Exclude VMIDs this stack already owns (re-deploy must not collide with itself).
    own = {int(r["vmid"]) for r in await deployments.list_deployed_resources(stack_id)
           if r.get("vmid") is not None}
    occupied = used_vmids - own

    taken = sorted(v for v in wanted if v in occupied)
    if taken:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "vmid_taken",
                "taken": taken,
                "suggestions": suggest_free_vmids(spec, occupied),
            },
        )


# ── Plan parsing ──────────────────────────────────────────────────────────────

def parse_plan_json(stdout: str) -> PlanSummary:
    """Parse ``tofu plan -json`` line-stream into a PlanSummary.

    Best-effort: reads ``change_summary`` for counts and ``planned_change`` /
    ``resource_drift`` for the per-resource list. Robust against unknown lines.
    """
    create = change = destroy = replace = 0
    resources: list[PlanResource] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        mtype = obj.get("type")
        if mtype == "change_summary":
            ch = obj.get("changes", {}) or {}
            create = int(ch.get("add", 0))
            change = int(ch.get("change", 0))
            destroy = int(ch.get("remove", 0))
        elif mtype == "planned_change":
            ch = obj.get("change", {}) or {}
            action = ch.get("action", "")
            res = ch.get("resource", {}) or {}
            name = res.get("addr") or res.get("resource_name") or ""
            if action in ("create", "update", "delete", "replace"):
                resources.append(PlanResource(name=name, action=action))
                if action == "replace":
                    replace += 1
    return PlanSummary(
        create=create, change=change, destroy=destroy, replace=replace, resources=resources
    )


def extract_tofu_json_errors(stdout: str) -> str:
    """Pull human-readable error diagnostics out of a ``tofu … -json`` stream.

    With ``-json`` tofu emits its diagnostics as JSON lines on **stdout**, not
    stderr — so a failed ``plan`` leaves stderr empty. This collects every
    ``@level == "error"`` line's message + diagnostic summary/detail so the API
    can surface the real cause instead of an empty ``stderr``.
    """
    msgs: list[str] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("@level") != "error":
            continue
        diag = obj.get("diagnostic") or {}
        summary = diag.get("summary") or obj.get("@message") or ""
        detail = diag.get("detail") or ""
        piece = summary if not detail else f"{summary}: {detail}"
        if piece and piece not in msgs:
            msgs.append(piece)
    return "\n".join(msgs)


# ── Plan token registry ───────────────────────────────────────────────────────

def _make_plan_token(stack_id: int, etag: str, operation: str, summary: PlanSummary, node_id: int) -> str:
    token = uuid.uuid4().hex
    _PLAN_TOKENS[token] = {
        "stack_id": stack_id,
        "etag": etag,
        "operation": operation,
        "summary": summary,
        "node_id": node_id,
        "expires_at": datetime.now(timezone.utc) + _PLAN_TTL,
    }
    return token


def consume_plan_token(token: str, stack_id: int, current_etag: str, operation: str) -> dict:
    """Validate + pop a plan token. Raises 409 on etag mismatch, 400 otherwise."""
    entry = _PLAN_TOKENS.get(token)
    if entry is None:
        raise HTTPException(status_code=400, detail="invalid_plan_token")
    if entry["expires_at"] < datetime.now(timezone.utc):
        _PLAN_TOKENS.pop(token, None)
        raise HTTPException(status_code=409, detail="plan_token_expired")
    if entry["stack_id"] != stack_id or entry["operation"] != operation:
        raise HTTPException(status_code=400, detail="invalid_plan_token")
    if entry["etag"] != current_etag:
        _PLAN_TOKENS.pop(token, None)
        raise HTTPException(status_code=409, detail="stack_definition_changed")
    # Verify the planfile still exists.
    planfile = engine.stack_working_dir(str(stack_id)) / "plan.tfplan"
    if not planfile.exists():
        _PLAN_TOKENS.pop(token, None)
        raise HTTPException(status_code=409, detail="planfile_missing")
    return _PLAN_TOKENS.pop(token)


# ── Plan ──────────────────────────────────────────────────────────────────────

async def prepare_plan(
    stack_row, user_role: str, user_id: Optional[int], username: str, operation: str,
) -> PlanResponse:
    """Gate → transpile → tofu init/validate/plan → plan-token (AC-2B-PLAN-1)."""
    stack_id = stack_row["id"]
    spec = await _spec_of(stack_row)
    node = await resolve_target_node(spec)
    await assert_deploy_allowed(stack_row, spec, node, user_role, user_id, username)

    # Reject pinned-but-taken VMIDs before tofu runs (destroy needs no free VMID).
    if operation != "destroy":
        await assert_explicit_vmids_free(stack_id, node, spec)

    template_vmids = await resolve_template_vmids(node, spec)
    tfjson = transpile.stack_to_tfjson(spec, template_vmids)

    workdir = engine.stack_working_dir(str(stack_id))
    (workdir / "main.tf.json").write_text(json.dumps(tfjson, indent=2), encoding="utf-8")

    lock = engine.get_stack_lock(str(stack_id))
    if lock.locked():
        raise HTTPException(status_code=409, detail="stack_busy")
    async with lock:
        rc_i, out_i, err_i = await engine.tofu_init_if_needed(str(stack_id), node)
        if rc_i != 0:
            raise HTTPException(
                status_code=422,
                detail={"error": "tofu_init_failed", "stderr": (err_i or out_i)[:2000]},
            )
        rc_v, _out_v, err_v = await engine.run_tofu(
            ["validate", "-no-color"], str(stack_id), node
        )
        if rc_v != 0:
            raise HTTPException(status_code=422, detail={"error": "tofu_validate_failed", "stderr": err_v[:2000]})

        plan_args = ["plan", "-out=plan.tfplan", "-json", "-input=false", "-no-color"]
        if operation == "destroy":
            plan_args.insert(1, "-destroy")
        rc_p, out_p, err_p = await engine.run_tofu(plan_args, str(stack_id), node)
        # tofu plan exit code 0 = no changes, 2 = changes (with -detailed-exitcode);
        # without it, 0 = success. Non-zero(!=0) without detailed-exitcode = error.
        if rc_p not in (0,):
            # With -json the diagnostics land on stdout, not stderr → extract them
            # so the API surfaces the real cause instead of an empty stderr.
            err_detail = err_p.strip() or extract_tofu_json_errors(out_p) or "(keine Fehlerausgabe von tofu)"
            raise HTTPException(status_code=422, detail={"error": "tofu_plan_failed", "stderr": err_detail[:2000]})

    summary = parse_plan_json(out_p)
    token = _make_plan_token(stack_id, stack_row["current_etag"], operation, summary, node.id)
    await write_audit_log(
        "stack_plan_created", username=username,
        detail=(
            f"stack_id={stack_id} op={operation} "
            f"create={summary.create} change={summary.change} destroy={summary.destroy}"
        ),
    )
    return PlanResponse(plan_token=token, operation=operation, summary=summary)


# ── Start deploy/destroy job ──────────────────────────────────────────────────

async def start_stack_job(
    stack_row, operation: str, summary: PlanSummary, node: NodeRow,
    triggered_by_user_id: Optional[int], username: str,
) -> dict:
    """Acquire the lock (409 if busy), create job + deployment rows, launch runner.

    Lock is acquired here and released by the runner in its finally block
    (asyncio.Lock is not owner-bound). Returns {job_id, deployment_id}.
    """
    from .runner import run_stack_job

    stack_id = stack_row["id"]
    lock = engine.get_stack_lock(str(stack_id))
    if lock.locked():
        raise HTTPException(status_code=409, detail="stack_busy")
    await lock.acquire()
    try:
        job_id = str(uuid.uuid4())
        now = _now()
        async with get_db() as db:
            await db.execute(
                text(
                    "INSERT INTO jobs (id, type, playbook, status, created_at, username, params) "
                    "VALUES (:id, :jtype, :pb, 'pending', :now, :user, :params)"
                ),
                {
                    "id": job_id,
                    "jtype": f"stack_{operation}",
                    "pb": f"stack:{stack_row['name']}",
                    "now": now,
                    "user": username,
                    "params": json.dumps({"stack_id": stack_id, "operation": operation}),
                },
            )
            await db.commit()

        deployment_id = await create_deployment(
            stack_id=stack_id,
            operation=operation,
            job_id=job_id,
            plan_summary_json=json.dumps(summary.model_dump()),
            triggered_by_user_id=triggered_by_user_id,
        )

        import asyncio
        asyncio.create_task(
            run_stack_job(
                job_id=job_id,
                stack_id=stack_id,
                deployment_id=deployment_id,
                operation=operation,
                node=node,
                triggered_by=username,
                lock=lock,
            )
        )
    except Exception:
        lock.release()
        raise

    return {"job_id": job_id, "deployment_id": deployment_id}


# ── Drift (read-only) ─────────────────────────────────────────────────────────

async def run_drift(stack_row, username: str):
    """On-demand drift: read-only ``tofu plan`` over the stack's own VMs only.

    Never touches foreign VMs (state isolation, AC-2B-DRIFT-5). Writes
    ``last_drift_state``. Returns a DriftReport.
    """
    from .deployments import list_deployed_resources
    from .schemas import DriftItem, DriftReport

    stack_id = stack_row["id"]
    spec = await _spec_of(stack_row)
    node = await resolve_target_node(spec)

    lock = engine.get_stack_lock(str(stack_id))
    if lock.locked():
        raise HTTPException(status_code=409, detail="stack_busy")

    deployed = await list_deployed_resources(stack_id)
    if not deployed:
        # Nothing deployed → nothing to drift.
        await set_drift_state(stack_id, "in_sync")
        return DriftReport(drift_state="in_sync")

    async with lock:
        # tofu needs an up-to-date provider cache, so init if the throwaway
        # .terraform/ is missing (e.g. fresh container) before planning.
        await engine.tofu_init_if_needed(str(stack_id), node)
        # A normal plan (NOT -refresh-only) answers "does reality differ from the
        # definition" and honours lifecycle.ignore_changes=[clone] → no phantom
        # drift from the create-time clone block. refresh-only would show clone
        # drift regardless (ignore_changes only affects the planned changes).
        rc, out, err = await engine.run_tofu(
            ["plan", "-json", "-input=false", "-no-color"],
            str(stack_id), node,
        )
    if rc != 0:
        # A failed plan must NOT be reported as "in_sync" (would hide drift).
        err_detail = err.strip() or extract_tofu_json_errors(out) or "(keine Fehlerausgabe von tofu)"
        raise HTTPException(status_code=422, detail={"error": "tofu_drift_failed", "stderr": err_detail[:2000]})
    summary = parse_plan_json(out)

    # Drift = what tofu would change to re-reach the definition:
    # update/replace = changed in place; create = the tracked VM vanished (missing).
    changed_names = {r.name for r in summary.resources if r.action in ("update", "replace")}
    missing_names = {r.name for r in summary.resources if r.action in ("create", "delete")}
    items: list[DriftItem] = []
    n_sync = n_changed = n_missing = 0
    for d in deployed:
        name = d["resource_name"]
        # tofu resource addr looks like proxmox_virtual_environment_vm.<name>
        addr_match = any(name == cn.split(".")[-1] or name == cn for cn in changed_names)
        miss_match = any(name == cn.split(".")[-1] or name == cn for cn in missing_names)
        if miss_match:
            state = "missing"
            n_missing += 1
        elif addr_match:
            state = "changed"
            n_changed += 1
        else:
            state = "in_sync"
            n_sync += 1
        items.append(DriftItem(resource_name=name, vmid=d.get("vmid"), state=state))

    drift_state = "out_of_sync" if (n_changed or n_missing) else "in_sync"
    await set_drift_state(stack_id, drift_state)
    await write_audit_log(
        "stack_drift_checked", username=username,
        detail=f"stack_id={stack_id} state={drift_state} changed={n_changed} missing={n_missing}",
    )
    return DriftReport(
        drift_state=drift_state, in_sync=n_sync, changed=n_changed,
        missing=n_missing, items=items,
    )
