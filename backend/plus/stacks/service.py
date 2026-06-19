# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-76 Phase 1: Stack-Service (CRUD + ETag + Versionierung + Orphan).

YAML ist Single Source of Truth (stacks.yaml_text). ETag = SHA-256 von yaml_text.
Versionshistorie pro Edit mit Code-Side-FIFO-Cap (portal_config.stack_version_cap).
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import text

from backend.db.database import get_db
from backend.services.audit_service import write_audit_log

from . import validation
from .diff import diff_yaml
from .preview import resolve_resources, resolved_resource_dicts
from .schemas import (
    DiffEntry,
    EtagConflictResponse,
    OrphanStackResponse,
    PreviewResult,
    StackCreateRequest,
    StackDetailResponse,
    StackDiffResponse,
    StackResponse,
    StackUpdateRequest,
    StackVersionResponse,
    StackVersionSummary,
    ValidationResult,
)

logger = logging.getLogger(__name__)

_DEFAULT_VERSION_CAP = 50


class EtagConflict(Exception):
    """Raised on ETag mismatch in update_with_etag (AC-CONC-2). Router → HTTP 409."""

    def __init__(self, body: EtagConflictResponse) -> None:
        self.body = body
        super().__init__("etag_conflict")


# ── helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def etag_of(yaml_text: str) -> str:
    """SHA-256 hex of the canonical yaml_text (AC-DB-8)."""
    return hashlib.sha256(yaml_text.encode("utf-8")).hexdigest()


async def _version_cap() -> int:
    try:
        from backend.services.config_service import get_config
        raw = await get_config("stack_version_cap")
        if raw:
            return max(1, int(raw))
    except Exception:
        pass
    return _DEFAULT_VERSION_CAP


async def _resolve_usernames(user_ids: list[int]) -> dict[int, str]:
    ids = [u for u in {*user_ids} if u]
    if not ids:
        return {}
    async with get_db() as db:
        placeholders = ",".join(f":u{i}" for i in range(len(ids)))
        result = await db.execute(
            text(f"SELECT id, username FROM local_users WHERE id IN ({placeholders})"),
            {f"u{i}": uid for i, uid in enumerate(ids)},
        )
        return {row["id"]: row["username"] for row in result.mappings().fetchall()}


async def _resource_counts(stack_ids: list[int]) -> dict[int, int]:
    if not stack_ids:
        return {}
    async with get_db() as db:
        placeholders = ",".join(f":s{i}" for i in range(len(stack_ids)))
        result = await db.execute(
            text(
                f"SELECT stack_id, COUNT(*) AS c FROM stack_resources "
                f"WHERE stack_id IN ({placeholders}) GROUP BY stack_id"
            ),
            {f"s{i}": sid for i, sid in enumerate(stack_ids)},
        )
        return {row["stack_id"]: row["c"] for row in result.mappings().fetchall()}


def _row_to_response(row, resource_count: int, owner_username: Optional[str]) -> StackResponse:
    return StackResponse(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        version=row["version"],
        status=row["status"],
        source_kind=row["source_kind"],
        owner_user_id=row["owner_user_id"],
        owner_username=owner_username,
        is_orphan=bool(row["is_orphan"]),
        resource_count=resource_count,
        current_etag=row["current_etag"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        last_drift_state=_row_get(row, "last_drift_state"),
    )


def _row_get(row, key: str):
    """Tolerant column access (Phase-2b columns may be absent on very old rows)."""
    try:
        return row[key]
    except (KeyError, IndexError):
        return None


async def _enrich_deployment_state(resp: StackResponse, row) -> StackResponse:
    """Phase 2b: derive the deployment badge for a response (Tech-Design Open Point 4)."""
    try:
        from .deployments import derive_deployment_state
        resp.deployment_state = await derive_deployment_state(row)
    except Exception:  # pragma: no cover – defensive (table missing in pure-core)
        resp.deployment_state = None
    return resp


async def _get_stack_row(stack_id: int, include_deleted: bool = False):
    async with get_db() as db:
        result = await db.execute(
            text("SELECT * FROM stacks WHERE id = :id"),
            {"id": stack_id},
        )
        row = result.mappings().fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="stack_not_found")
    if row["deleted_at"] is not None and not include_deleted:
        raise HTTPException(status_code=404, detail="stack_not_found")
    return row


# ── denormalization ───────────────────────────────────────────────────────────

async def _replace_resources(db, stack_id: int, spec) -> None:
    await db.execute(
        text("DELETE FROM stack_resources WHERE stack_id = :sid"),
        {"sid": stack_id},
    )
    for idx, rdict in enumerate(resolved_resource_dicts(spec)):
        await db.execute(
            text(
                "INSERT INTO stack_resources (stack_id, type, name, definition_json, sort_index) "
                "VALUES (:sid, :type, :name, :dj, :si)"
            ),
            {
                "sid": stack_id,
                "type": rdict.get("type", "vm"),
                "name": rdict["name"],
                "dj": json.dumps(rdict, sort_keys=True),
                "si": idx,
            },
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Validate / Preview (no persistence)
# ═══════════════════════════════════════════════════════════════════════════════

async def validate_definition(req: StackCreateRequest) -> ValidationResult:
    spec, _canonical, errors, warnings = await validation.validate_request(req)
    return ValidationResult(valid=spec is not None, errors=errors, warnings=warnings)


async def preview_definition(req: StackCreateRequest) -> PreviewResult:
    spec, _canonical, errors, warnings = await validation.validate_request(req)
    if spec is None:
        return PreviewResult(valid=False, errors=errors, warnings=warnings)
    resources = resolve_resources(spec)
    return PreviewResult(
        valid=True,
        errors=[],
        warnings=warnings,
        resources=resources,
        resource_count=len(resources),
    )


async def preview_saved_stack(stack_id: int) -> PreviewResult:
    row = await _get_stack_row(stack_id)
    req = StackCreateRequest(yaml_text=row["yaml_text"])
    return await preview_definition(req)


# ═══════════════════════════════════════════════════════════════════════════════
# CRUD
# ═══════════════════════════════════════════════════════════════════════════════

async def create_stack(
    req: StackCreateRequest,
    user_id: Optional[int],
    username: str,
) -> StackResponse:
    spec, canonical, errors, _warnings = await validation.validate_request(req)
    if spec is None:
        raise HTTPException(status_code=422, detail={"errors": errors})

    etag = etag_of(canonical)
    now = _now()

    async with get_db() as db:
        await db.execute(
            text(
                "INSERT INTO stacks "
                "(name, description, yaml_text, version, status, source_kind, "
                " owner_user_id, is_orphan, current_etag, created_at, updated_at) "
                "VALUES (:name, :desc, :yaml, :version, 'active', 'structured', "
                ":uid, false, :etag, :now, :now)"
            ),
            {
                "name": spec.name,
                "desc": spec.description,
                "yaml": canonical,
                "version": spec.version,
                "uid": user_id,
                "etag": etag,
                "now": now,
            },
        )
        # Resolve new id dialect-portably via the unique created_at timestamp.
        # Owner-Filter (BUG-76-3): schließt eine theoretische Mikrosekunden-Kollision
        # zwischen zwei Ownern mit gleichem Stack-Namen aus.
        r2 = await db.execute(
            text(
                "SELECT id FROM stacks WHERE created_at = :now AND name = :name "
                "AND (owner_user_id = :uid OR (:uid IS NULL AND owner_user_id IS NULL)) "
                "ORDER BY id DESC LIMIT 1"
            ),
            {"now": now, "name": spec.name, "uid": user_id},
        )
        stack_id = r2.mappings().fetchone()["id"]
        await _replace_resources(db, stack_id, spec)
        await db.commit()

    await write_audit_log(
        "stack_created", username=username,
        detail=f"stack_id={stack_id} name={spec.name}",
    )
    return await get_stack_response(stack_id)


async def get_stack_response(stack_id: int) -> StackResponse:
    row = await _get_stack_row(stack_id)
    counts = await _resource_counts([stack_id])
    unames = await _resolve_usernames([row["owner_user_id"]] if row["owner_user_id"] else [])
    resp = _row_to_response(row, counts.get(stack_id, 0), unames.get(row["owner_user_id"]))
    return await _enrich_deployment_state(resp, row)


async def get_stack_detail(stack_id: int) -> StackDetailResponse:
    row = await _get_stack_row(stack_id)
    async with get_db() as db:
        result = await db.execute(
            text(
                "SELECT definition_json FROM stack_resources "
                "WHERE stack_id = :sid ORDER BY sort_index"
            ),
            {"sid": stack_id},
        )
        resources = [json.loads(r["definition_json"]) for r in result.mappings().fetchall()]
    unames = await _resolve_usernames([row["owner_user_id"]] if row["owner_user_id"] else [])
    base = _row_to_response(row, len(resources), unames.get(row["owner_user_id"]))
    base = await _enrich_deployment_state(base, row)
    return StackDetailResponse(
        **base.model_dump(),
        yaml_text=row["yaml_text"],
        resources=resources,
        yaml_corrupt=_is_yaml_corrupt(row["yaml_text"]),
    )


def _is_yaml_corrupt(yaml_text: Optional[str]) -> bool:
    """True wenn yaml_text leer ist oder nicht zu einem Mapping parst (BUG-76-4)."""
    import yaml as _yaml
    if not yaml_text or not yaml_text.strip():
        return True
    try:
        parsed = _yaml.safe_load(yaml_text)
    except _yaml.YAMLError:
        return True
    return not isinstance(parsed, dict)


async def list_stacks(
    user_id: Optional[int],
    role: str,
    q: Optional[str] = None,
    include_deleted: bool = False,
) -> list[StackResponse]:
    conditions: list[str] = []
    params: dict[str, Any] = {}

    if role != "admin":
        if user_id is None:
            return []
        conditions.append("owner_user_id = :uid")
        params["uid"] = user_id

    if not include_deleted or role != "admin":
        conditions.append("deleted_at IS NULL")

    if q:
        conditions.append("(name LIKE :q OR description LIKE :q)")
        params["q"] = f"%{q}%"

    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    async with get_db() as db:
        result = await db.execute(
            text(f"SELECT * FROM stacks{where} ORDER BY updated_at DESC"),
            params,
        )
        rows = result.mappings().fetchall()

    stack_ids = [r["id"] for r in rows]
    counts = await _resource_counts(stack_ids)
    unames = await _resolve_usernames([r["owner_user_id"] for r in rows if r["owner_user_id"]])
    out: list[StackResponse] = []
    for r in rows:
        resp = _row_to_response(r, counts.get(r["id"], 0), unames.get(r["owner_user_id"]))
        out.append(await _enrich_deployment_state(resp, r))
    return out


# ── Update with ETag + versioning ─────────────────────────────────────────────

async def update_with_etag(
    stack_id: int,
    req: StackUpdateRequest,
    user_id: Optional[int],
    username: str,
) -> StackResponse:
    row = await _get_stack_row(stack_id)

    # Validate new definition (structure must pass → else 422)
    spec, canonical, errors, _warnings = await validation.validate_request(req)
    if spec is None:
        raise HTTPException(status_code=422, detail={"errors": errors})

    # ETag concurrency check (AC-CONC-2)
    if req.expected_etag != row["current_etag"]:
        raise EtagConflict(EtagConflictResponse(
            current_etag=row["current_etag"],
            current_yaml=row["yaml_text"],
            your_yaml=canonical,
            base_yaml=req.base_yaml,
        ))

    change_summary = req.change_summary or f"edit by {username}"
    new_etag = etag_of(canonical)
    await _commit_edit(
        stack_id=stack_id,
        old_row=row,
        new_yaml=canonical,
        new_version_str=spec.version,
        new_name=spec.name,
        new_description=spec.description,
        new_etag=new_etag,
        spec=spec,
        change_summary=change_summary,
        editor_user_id=user_id,
    )
    await write_audit_log(
        "stack_edited", username=username,
        detail=f"stack_id={stack_id} change_summary={change_summary}",
    )
    return await get_stack_response(stack_id)


async def _commit_edit(
    stack_id: int,
    old_row,
    new_yaml: str,
    new_version_str: str,
    new_name: str,
    new_description: Optional[str],
    new_etag: str,
    spec,
    change_summary: str,
    editor_user_id: Optional[int],
) -> None:
    """Save old state as version, update stack, FIFO-cap, re-denormalize resources."""
    now = _now()
    async with get_db() as db:
        # 1) next version number (monotonic, max+1)
        r = await db.execute(
            text("SELECT COALESCE(MAX(version_number), 0) AS m FROM stack_versions WHERE stack_id = :sid"),
            {"sid": stack_id},
        )
        next_vnum = r.mappings().fetchone()["m"] + 1

        # 2) save OLD state as version row
        await db.execute(
            text(
                "INSERT INTO stack_versions "
                "(stack_id, version_number, yaml_text, etag, change_summary, edited_by_user_id, created_at) "
                "VALUES (:sid, :vn, :yaml, :etag, :cs, :eid, :now)"
            ),
            {
                "sid": stack_id,
                "vn": next_vnum,
                "yaml": old_row["yaml_text"],
                "etag": old_row["current_etag"],
                "cs": change_summary,
                "eid": editor_user_id,
                "now": now,
            },
        )

        # 3) update stack to new state
        await db.execute(
            text(
                "UPDATE stacks SET yaml_text = :yaml, version = :ver, name = :name, "
                "description = :desc, current_etag = :etag, status = 'active', updated_at = :now "
                "WHERE id = :sid"
            ),
            {
                "yaml": new_yaml,
                "ver": new_version_str,
                "name": new_name,
                "desc": new_description,
                "etag": new_etag,
                "now": now,
                "sid": stack_id,
            },
        )

        # 4) re-denormalize resources
        await _replace_resources(db, stack_id, spec)
        await db.commit()

    # 5) FIFO cap (after insert, outside the same txn is fine)
    await _apply_fifo_cap(stack_id)


async def _apply_fifo_cap(stack_id: int) -> None:
    cap = await _version_cap()
    async with get_db() as db:
        await db.execute(
            text(
                "DELETE FROM stack_versions WHERE stack_id = :sid AND version_number NOT IN ("
                "  SELECT version_number FROM stack_versions WHERE stack_id = :sid "
                "  ORDER BY version_number DESC LIMIT :cap"
                ")"
            ),
            {"sid": stack_id, "cap": cap},
        )
        await db.commit()


# ── Soft-delete ────────────────────────────────────────────────────────────────

async def soft_delete(stack_id: int, username: str) -> None:
    await _get_stack_row(stack_id)  # 404 if missing/deleted
    now = _now()
    async with get_db() as db:
        await db.execute(
            text("UPDATE stacks SET deleted_at = :now, updated_at = :now WHERE id = :sid"),
            {"now": now, "sid": stack_id},
        )
        await db.commit()
    await write_audit_log(
        "stack_deleted", username=username, detail=f"stack_id={stack_id}",
    )


# ── Versions ───────────────────────────────────────────────────────────────────

async def list_versions(stack_id: int) -> list[StackVersionSummary]:
    await _get_stack_row(stack_id)
    async with get_db() as db:
        result = await db.execute(
            text(
                "SELECT version_number, etag, change_summary, edited_by_user_id, created_at "
                "FROM stack_versions WHERE stack_id = :sid ORDER BY version_number DESC"
            ),
            {"sid": stack_id},
        )
        rows = result.mappings().fetchall()
    unames = await _resolve_usernames([r["edited_by_user_id"] for r in rows if r["edited_by_user_id"]])
    return [
        StackVersionSummary(
            version_number=r["version_number"],
            etag=r["etag"],
            change_summary=r["change_summary"],
            edited_by_user_id=r["edited_by_user_id"],
            edited_by_username=unames.get(r["edited_by_user_id"]),
            created_at=r["created_at"],
        )
        for r in rows
    ]


async def get_version(stack_id: int, version_number: int) -> StackVersionResponse:
    await _get_stack_row(stack_id)
    async with get_db() as db:
        result = await db.execute(
            text(
                "SELECT * FROM stack_versions WHERE stack_id = :sid AND version_number = :vn"
            ),
            {"sid": stack_id, "vn": version_number},
        )
        row = result.mappings().fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="version_not_found")
    unames = await _resolve_usernames([row["edited_by_user_id"]] if row["edited_by_user_id"] else [])
    return StackVersionResponse(
        version_number=row["version_number"],
        yaml_text=row["yaml_text"],
        etag=row["etag"],
        change_summary=row["change_summary"],
        edited_by_user_id=row["edited_by_user_id"],
        edited_by_username=unames.get(row["edited_by_user_id"]),
        created_at=row["created_at"],
    )


async def _yaml_for_label(stack_id: int, row, label: str) -> tuple[str, str]:
    """Return (yaml_text, etag) for a label 'current' or 'vN'."""
    if label == "current":
        return row["yaml_text"], row["current_etag"]
    if label.startswith("v"):
        try:
            vn = int(label[1:])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="invalid_version_label") from exc
        ver = await get_version(stack_id, vn)
        return ver.yaml_text, ver.etag
    raise HTTPException(status_code=422, detail="invalid_version_label")


async def diff_stack(stack_id: int, from_label: str, to_label: str) -> StackDiffResponse:
    row = await _get_stack_row(stack_id)
    from_yaml, from_etag = await _yaml_for_label(stack_id, row, from_label)
    to_yaml, to_etag = await _yaml_for_label(stack_id, row, to_label)
    diff: list[DiffEntry] = diff_yaml(from_yaml, to_yaml)
    return StackDiffResponse(
        from_label=from_label,
        to_label=to_label,
        from_etag=from_etag,
        to_etag=to_etag,
        diff=diff,
    )


# ── Restore ────────────────────────────────────────────────────────────────────

async def restore_version(
    stack_id: int,
    version_number: int,
    user_id: Optional[int],
    username: str,
    change_summary: Optional[str] = None,
    expected_etag: Optional[str] = None,
) -> StackResponse:
    row = await _get_stack_row(stack_id)
    target = await get_version(stack_id, version_number)

    # ETag-Concurrency-Schutz (BUG-76-2, Edge 9): wenn der Client einen erwarteten
    # ETag mitschickt, darf der Stack zwischenzeitlich nicht editiert worden sein.
    if expected_etag is not None and expected_etag != row["current_etag"]:
        raise EtagConflict(EtagConflictResponse(
            current_etag=row["current_etag"],
            current_yaml=row["yaml_text"],
            your_yaml=target.yaml_text,
            base_yaml=None,
        ))

    # Validate the restored YAML (should pass, but stay safe)
    req = StackCreateRequest(yaml_text=target.yaml_text)
    spec, canonical, errors, _warnings = await validation.validate_request(req)
    if spec is None:
        raise HTTPException(status_code=422, detail={"errors": errors})

    summary = change_summary or f"restored from v{version_number}"
    new_etag = etag_of(canonical)
    await _commit_edit(
        stack_id=stack_id,
        old_row=row,
        new_yaml=canonical,
        new_version_str=spec.version,
        new_name=spec.name,
        new_description=spec.description,
        new_etag=new_etag,
        spec=spec,
        change_summary=summary,
        editor_user_id=user_id,
    )
    await write_audit_log(
        "stack_restored", username=username,
        detail=f"stack_id={stack_id} from_version={version_number}",
    )
    return await get_stack_response(stack_id)


# ═══════════════════════════════════════════════════════════════════════════════
# Orphans
# ═══════════════════════════════════════════════════════════════════════════════

async def list_orphans() -> list[OrphanStackResponse]:
    async with get_db() as db:
        result = await db.execute(
            text(
                "SELECT * FROM stacks WHERE is_orphan = true AND deleted_at IS NULL "
                "ORDER BY orphaned_at DESC"
            )
        )
        rows = result.mappings().fetchall()
    counts = await _resource_counts([r["id"] for r in rows])
    return [
        OrphanStackResponse(
            id=r["id"],
            name=r["name"],
            description=r["description"],
            version=r["version"],
            resource_count=counts.get(r["id"], 0),
            orphaned_at=r["orphaned_at"],
            ex_owner_user_id=r["owner_user_id"],
        )
        for r in rows
    ]


async def reassign_orphan(stack_id: int, new_owner_user_id: int, admin_username: str) -> StackResponse:
    async with get_db() as db:
        result = await db.execute(
            text("SELECT * FROM stacks WHERE id = :sid AND is_orphan = true AND deleted_at IS NULL"),
            {"sid": stack_id},
        )
        row = result.mappings().fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="orphan_stack_not_found")
        # Verify the new owner exists
        owner = await db.execute(
            text("SELECT id FROM local_users WHERE id = :uid"),
            {"uid": new_owner_user_id},
        )
        if owner.mappings().fetchone() is None:
            raise HTTPException(status_code=422, detail="owner_user_not_found")
        await db.execute(
            text(
                "UPDATE stacks SET owner_user_id = :uid, is_orphan = false, orphaned_at = NULL, "
                "updated_at = :now WHERE id = :sid"
            ),
            {"uid": new_owner_user_id, "now": _now(), "sid": stack_id},
        )
        await db.commit()
    await write_audit_log(
        "stack_reassigned", username=admin_username,
        detail=f"stack_id={stack_id} new_owner_user_id={new_owner_user_id}",
    )
    return await get_stack_response(stack_id)


async def purge_orphan(stack_id: int, admin_username: str) -> None:
    async with get_db() as db:
        result = await db.execute(
            text("SELECT id FROM stacks WHERE id = :sid AND is_orphan = true"),
            {"sid": stack_id},
        )
        if result.mappings().fetchone() is None:
            raise HTTPException(status_code=404, detail="orphan_stack_not_found")
        # Hard-delete: stack_resources + stack_versions cascade via FK, but delete explicitly
        # for portability (SQLite FK enforcement may be off).
        await db.execute(text("DELETE FROM stack_versions WHERE stack_id = :sid"), {"sid": stack_id})
        await db.execute(text("DELETE FROM stack_resources WHERE stack_id = :sid"), {"sid": stack_id})
        await db.execute(text("DELETE FROM stacks WHERE id = :sid"), {"sid": stack_id})
        await db.commit()
    await write_audit_log(
        "stack_orphan_purged", username=admin_username,
        detail=f"stack_id={stack_id}",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Approval apply-handlers (called by PROJ-50 HANDLER_REGISTRY after approve)
# ═══════════════════════════════════════════════════════════════════════════════

async def apply_pending_edit(
    stack_id: int,
    expected_etag: str,
    new_yaml: str,
    change_summary: Optional[str],
    user_id: Optional[int],
    username: str,
) -> StackResponse:
    """Apply a previously-approved stack edit (AC-APPR-3 re-check).

    Re-checks the ETag at approval time. Mismatch → raise (handler cancels approval).
    """
    row = await _get_stack_row(stack_id)
    if expected_etag != row["current_etag"]:
        raise EtagConflict(EtagConflictResponse(
            current_etag=row["current_etag"],
            current_yaml=row["yaml_text"],
            your_yaml=new_yaml,
            base_yaml=None,
        ))
    req = StackCreateRequest(yaml_text=new_yaml)
    spec, canonical, errors, _warnings = await validation.validate_request(req)
    if spec is None:
        raise HTTPException(status_code=422, detail={"errors": errors})
    summary = change_summary or f"edit by {username} (approved)"
    await _commit_edit(
        stack_id=stack_id,
        old_row=row,
        new_yaml=canonical,
        new_version_str=spec.version,
        new_name=spec.name,
        new_description=spec.description,
        new_etag=etag_of(canonical),
        spec=spec,
        change_summary=summary,
        editor_user_id=user_id,
    )
    await write_audit_log(
        "stack_edited", username=username,
        detail=f"stack_id={stack_id} change_summary={summary} (approved)",
    )
    return await get_stack_response(stack_id)


async def apply_pending_delete(stack_id: int, username: str) -> None:
    """Apply a previously-approved stack delete (AC-APPR-4)."""
    await soft_delete(stack_id, username)
