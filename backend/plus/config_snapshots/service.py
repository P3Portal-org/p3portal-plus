# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-74: VM/LXC Config-Snapshot service.

Handles all database and Proxmox API interactions for the config-snapshot
feature: create, list, diff, restore, download, bulk-download, upload, delete.

Concurrent restore protection: one asyncio.Lock per (portal_node_id, proxmox_node, vmid, kind).
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import uuid
import zipfile
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException, UploadFile
from sqlalchemy import text

logger = logging.getLogger(__name__)

from backend.db.database import get_db
from backend.db.dialect import json_path_extract
from backend.services.audit_service import write_audit_log
from backend.services.nodes_service import NodeRow, get_node
from backend.services.proxmox import ProxmoxAuth, ProxmoxClient

from ._conf_render import render_conf
from ._conf_safety import UnsafeConfValue, parse_conf_text
from .schemas import (
    DiffABOut,
    DiffEntry,
    DiffOut,
    OrphanOut,
    SnapshotDetail,
    SnapshotOut,
    UploadOut,
)

# ── Layer 1+2 upload limits ───────────────────────────────────────────────────
_UPLOAD_MAX_BYTES = 100 * 1024          # 100 KB
_UPLOAD_ALLOWED_MIME = {"text/plain", "application/octet-stream", ""}
_UPLOAD_FILENAME_RE = __import__("re").compile(r"^[\w\-\.]+\.conf$")
_UPLOAD_MAX_LINES = 5_000
_UPLOAD_MAX_LINE_CHARS = 10_000

# Bulk-download cap
_BULK_DOWNLOAD_CAP = 200

# Proxmox API-only keys that must never be stored or compared
_API_ONLY_KEYS: frozenset[str] = frozenset({"digest"})

# ── Concurrent-restore locks ─────────────────────────────────────────────────
# Dict key: (portal_node_id, proxmox_node, vmid, kind)
_RESTORE_LOCKS: dict[tuple, asyncio.Lock] = {}
_RESTORE_LOCKS_META_LOCK = asyncio.Lock()


async def _get_restore_lock(key: tuple) -> asyncio.Lock:
    async with _RESTORE_LOCKS_META_LOCK:
        return _RESTORE_LOCKS.setdefault(key, asyncio.Lock())


# ── Node helpers ──────────────────────────────────────────────────────────────

async def _get_node_or_404(portal_node_id: int) -> NodeRow:
    node = await get_node(portal_node_id)
    if not node:
        raise HTTPException(status_code=404, detail="portal_node_not_found")
    return node


def _admin_auth(node: NodeRow) -> tuple[ProxmoxClient, ProxmoxAuth]:
    client = ProxmoxClient(base_url=node.url, verify_ssl=node.verify_ssl)
    auth = ProxmoxAuth(kind="token", value=node.admin_token_id, secret=node.admin_token_secret)
    return client, auth


# ── ETag helpers ──────────────────────────────────────────────────────────────

def _etag_of(payload: dict) -> str:
    """SHA-256 of canonical JSON (sorted keys, no whitespace)."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


# ── Row → schema ──────────────────────────────────────────────────────────────

def _row_to_out(row, username: Optional[str] = None) -> SnapshotOut:
    return SnapshotOut(
        id=row["id"],
        portal_node_id=row["portal_node_id"],
        proxmox_node=row["proxmox_node"],
        vmid=row["vmid"],
        kind=row["kind"],
        name=row["name"],
        note=row["note"],
        description=row["description"],
        source=row["source"],
        created_at=row["created_at"],
        created_by_user_id=row["created_by_user_id"],
        created_by_username=username,
        is_orphan=bool(row["is_orphan"]),
        orphaned_at=row["orphaned_at"],
        vm_name_at_delete=row["vm_name_at_delete"],
    )


def _row_to_detail(row, username: Optional[str] = None) -> SnapshotDetail:
    payload = json.loads(row["payload_json"])
    return SnapshotDetail(
        **_row_to_out(row, username).model_dump(),
        payload=payload,
        etag=_etag_of(payload),
    )


# ── Username resolver ─────────────────────────────────────────────────────────

async def _resolve_usernames(user_ids: list[int]) -> dict[int, str]:
    if not user_ids:
        return {}
    async with get_db() as db:
        placeholders = ",".join(f":u{i}" for i in range(len(user_ids)))
        result = await db.execute(
            text(f"SELECT id, username FROM local_users WHERE id IN ({placeholders})"),
            {f"u{i}": uid for i, uid in enumerate(user_ids)},
        )
        return {row["id"]: row["username"] for row in result.mappings().fetchall()}


# ═══════════════════════════════════════════════════════════════════════════════
# CRUD
# ═══════════════════════════════════════════════════════════════════════════════

async def list_snapshots(
    portal_node_id: int,
    proxmox_node: str,
    vmid: int,
    kind: str,
) -> list[SnapshotOut]:
    async with get_db() as db:
        result = await db.execute(
            text(
                "SELECT * FROM vm_config_snapshots "
                "WHERE portal_node_id = :nid "
                "  AND proxmox_node = :pn "
                "  AND vmid = :vmid "
                "  AND kind = :kind "
                "  AND is_orphan = 0 "
                "ORDER BY created_at DESC"
            ),
            {"nid": portal_node_id, "pn": proxmox_node, "vmid": vmid, "kind": kind},
        )
        rows = result.mappings().fetchall()

    user_ids = [r["created_by_user_id"] for r in rows if r["created_by_user_id"]]
    usernames = await _resolve_usernames(list(set(user_ids)))
    return [_row_to_out(r, usernames.get(r["created_by_user_id"])) for r in rows]


async def list_snapshots_by_node(
    portal_node_id: int,
    q: Optional[str] = None,
    kind: Optional[str] = None,
    user_id: Optional[int] = None,
    since: Optional[str] = None,
) -> list[SnapshotOut]:
    conditions = ["portal_node_id = :nid", "is_orphan = 0"]
    params: dict[str, Any] = {"nid": portal_node_id}

    if kind:
        conditions.append("kind = :kind")
        params["kind"] = kind
    if user_id:
        conditions.append("created_by_user_id = :uid")
        params["uid"] = user_id
    if since:
        conditions.append("created_at >= :since")
        params["since"] = since
    if q:
        conditions.append("(name LIKE :q OR note LIKE :q)")
        params["q"] = f"%{q}%"

    where = " AND ".join(conditions)
    async with get_db() as db:
        result = await db.execute(
            text(f"SELECT * FROM vm_config_snapshots WHERE {where} ORDER BY created_at DESC"),
            params,
        )
        rows = result.mappings().fetchall()

    uids = list({r["created_by_user_id"] for r in rows if r["created_by_user_id"]})
    usernames = await _resolve_usernames(uids)
    return [_row_to_out(r, usernames.get(r["created_by_user_id"])) for r in rows]


async def get_snapshot(snapshot_id: str) -> SnapshotDetail:
    async with get_db() as db:
        result = await db.execute(
            text("SELECT * FROM vm_config_snapshots WHERE id = :id"),
            {"id": snapshot_id},
        )
        row = result.mappings().fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="snapshot_not_found")
    unames = await _resolve_usernames([row["created_by_user_id"]] if row["created_by_user_id"] else [])
    return _row_to_detail(row, unames.get(row["created_by_user_id"]))


async def create_snapshot(
    portal_node_id: int,
    proxmox_node: str,
    vmid: int,
    kind: str,
    note: str,
    name: Optional[str],
    created_by_user_id: Optional[int],
    username: str,
    source: str = "manual",
    payload_override: Optional[dict] = None,
    created_by_scheduled_job_id: Optional[str] = None,
) -> SnapshotOut:
    """Fetch live config from Proxmox and persist as a new snapshot."""
    try:
        return await _create_snapshot_impl(
            portal_node_id, proxmox_node, vmid, kind, note, name,
            created_by_user_id, username, source, payload_override,
            created_by_scheduled_job_id,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "create_snapshot unhandled error: portal_node_id=%s proxmox_node=%s vmid=%s kind=%s",
            portal_node_id, proxmox_node, vmid, kind,
        )
        raise HTTPException(status_code=500, detail=f"internal_error: {type(exc).__name__}: {exc}") from exc


async def _create_snapshot_impl(
    portal_node_id: int,
    proxmox_node: str,
    vmid: int,
    kind: str,
    note: str,
    name: Optional[str],
    created_by_user_id: Optional[int],
    username: str,
    source: str = "manual",
    payload_override: Optional[dict] = None,
    created_by_scheduled_job_id: Optional[str] = None,
) -> SnapshotOut:
    node = await _get_node_or_404(portal_node_id)
    client, auth = _admin_auth(node)

    if payload_override is None:
        vm_type = "qemu" if kind == "qemu" else "lxc"
        try:
            raw = await client.get_vm_config(auth, proxmox_node, vmid, vm_type=vm_type)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"proxmox_unreachable: {exc}") from exc
    else:
        raw = payload_override

    description = raw.pop("description", None) or ""
    for _k in _API_ONLY_KEYS:
        raw.pop(_k, None)
    payload_json = json.dumps(raw, sort_keys=True, separators=(",", ":"))

    snap_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()

    if not name:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        name = f"snapshot-config-{proxmox_node}-{vmid}-{ts}"

    async with get_db() as db:
        await db.execute(
            text(
                "INSERT INTO vm_config_snapshots "
                "(id, portal_node_id, proxmox_node, vmid, kind, name, note, "
                " payload_json, description, source, created_at, created_by_user_id, "
                " created_by_scheduled_job_id, is_orphan, orphaned_at, vm_name_at_delete) "
                "VALUES (:id, :nid, :pn, :vmid, :kind, :name, :note, "
                ":pj, :desc, :src, :ca, :uid, :sjid, 0, NULL, NULL)"
            ),
            {
                "id": snap_id,
                "nid": portal_node_id,
                "pn": proxmox_node,
                "vmid": vmid,
                "kind": kind,
                "name": name,
                "note": note,
                "pj": payload_json,
                "desc": description,
                "src": source,
                "ca": now,
                "uid": created_by_user_id,
                "sjid": created_by_scheduled_job_id,
            },
        )
        await db.commit()

    await write_audit_log(
        "config_snapshot_created",
        username=username,
        detail=f"snapshot_id={snap_id} kind={kind} vmid={vmid} node={proxmox_node}",
    )

    return await _fetch_snapshot_out(snap_id, username, created_by_user_id)


async def _fetch_snapshot_out(
    snap_id: str,
    username: Optional[str],
    user_id: Optional[int],
) -> SnapshotOut:
    async with get_db() as db:
        result = await db.execute(
            text("SELECT * FROM vm_config_snapshots WHERE id = :id"),
            {"id": snap_id},
        )
        row = result.mappings().fetchone()
    return _row_to_out(row, username)


# ═══════════════════════════════════════════════════════════════════════════════
# Diff
# ═══════════════════════════════════════════════════════════════════════════════

def _diff_dicts(base: dict, compare: dict) -> list[DiffEntry]:
    """Produce a full diff list comparing two config dicts, including unchanged entries."""
    entries: list[DiffEntry] = []
    all_keys = set(base) | set(compare)
    for key in sorted(all_keys):
        bv = base.get(key)
        cv = compare.get(key)
        # Stringify for display and comparison (Proxmox API mixes int/str types)
        bvs = str(bv) if bv is not None else None
        cvs = str(cv) if cv is not None else None
        if bv is None and cv is not None:
            entries.append(DiffEntry(key=key, live_value=cvs, snapshot_value=None, change="added"))
        elif bv is not None and cv is None:
            entries.append(DiffEntry(key=key, live_value=None, snapshot_value=bvs, change="removed"))
        elif bvs != cvs:
            entries.append(DiffEntry(key=key, live_value=cvs, snapshot_value=bvs, change="changed"))
        else:
            entries.append(DiffEntry(key=key, live_value=cvs, snapshot_value=bvs, change="unchanged"))
    return entries


async def diff_snapshot_vs_live(snapshot_id: str) -> DiffOut:
    """Compare a stored snapshot against the current live config."""
    detail = await get_snapshot(snapshot_id)

    portal_node_id = detail.portal_node_id
    proxmox_node = detail.proxmox_node
    vmid = detail.vmid
    kind = detail.kind

    node = await _get_node_or_404(portal_node_id)
    client, auth = _admin_auth(node)
    vm_type = "qemu" if kind == "qemu" else "lxc"
    try:
        live_raw = await client.get_vm_config(auth, proxmox_node, vmid, vm_type=vm_type)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"proxmox_unreachable: {exc}") from exc

    live_raw.pop("description", None)
    for _k in _API_ONLY_KEYS:
        live_raw.pop(_k, None)
    live_etag = _etag_of(live_raw)

    _exclude = {"description"} | _API_ONLY_KEYS
    snap_payload = {k: v for k, v in detail.payload.items() if k not in _exclude}
    snap_etag = detail.etag

    diff = _diff_dicts(snap_payload, live_raw)
    return DiffOut(
        snapshot_id=snapshot_id,
        live_etag=live_etag,
        snapshot_etag=snap_etag,
        diff=diff,
    )


async def diff_snapshot_ab(snapshot_a_id: str, snapshot_b_id: str) -> DiffABOut:
    """Compare two stored snapshots against each other (client-side diff request)."""
    a = await get_snapshot(snapshot_a_id)
    b = await get_snapshot(snapshot_b_id)

    _exclude = {"description"} | _API_ONLY_KEYS
    a_payload = {k: v for k, v in a.payload.items() if k not in _exclude}
    b_payload = {k: v for k, v in b.payload.items() if k not in _exclude}
    diff = _diff_dicts(a_payload, b_payload)
    return DiffABOut(snapshot_a_id=snapshot_a_id, snapshot_b_id=snapshot_b_id, diff=diff)


# ═══════════════════════════════════════════════════════════════════════════════
# Restore
# ═══════════════════════════════════════════════════════════════════════════════

async def restore_snapshot(
    snapshot_id: str,
    etag: str,
    vm_name_confirm: str,
    create_pre_restore_snapshot: bool,
    restart_after_restore: bool,
    username: str,
    user_id: Optional[int],
) -> dict:
    """Apply a snapshot to the live VM.

    Steps (spec §J):
    1. Load snapshot
    2. Verify VM name confirmation token
    3. Fetch live config + compute live ETag
    4. If live_etag != etag → 409 (stale, client must re-diff)
    5. Optionally create pre-restore snapshot (source='pre_restore')
    6. Compute diff (changed/added/removed)
    7. Apply via single bulk PUT
    8. Optionally restart VM (power_action reboot)
    """
    detail = await get_snapshot(snapshot_id)

    if detail.is_orphan:
        raise HTTPException(status_code=409, detail="cannot_restore_orphan")

    portal_node_id = detail.portal_node_id
    proxmox_node = detail.proxmox_node
    vmid = detail.vmid
    kind = detail.kind

    # Verify VM name confirmation token
    vm_type = "qemu" if kind == "qemu" else "lxc"
    node = await _get_node_or_404(portal_node_id)
    client, auth = _admin_auth(node)

    try:
        live_raw = await client.get_vm_config(auth, proxmox_node, vmid, vm_type=vm_type)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"proxmox_unreachable: {exc}") from exc

    live_name = live_raw.get("name") or live_raw.get("hostname") or ""
    if live_name.lower() != vm_name_confirm.lower():
        raise HTTPException(status_code=422, detail="vm_name_confirm_mismatch")

    # ETag re-check (EC-14): reject if live config changed since diff was computed
    live_for_etag = {k: v for k, v in live_raw.items() if k not in {"description"} | _API_ONLY_KEYS}
    live_etag = _etag_of(live_for_etag)
    if live_etag != etag:
        raise HTTPException(
            status_code=409,
            detail="live_config_changed",
            headers={"X-Live-ETag": live_etag},
        )

    lock_key = (portal_node_id, proxmox_node, vmid, kind)
    lock = await _get_restore_lock(lock_key)

    if lock.locked():
        raise HTTPException(status_code=409, detail="restore_in_progress")
    await lock.acquire()

    try:
        if create_pre_restore_snapshot:
            try:
                await create_snapshot(
                    portal_node_id=portal_node_id,
                    proxmox_node=proxmox_node,
                    vmid=vmid,
                    kind=kind,
                    note="Automatisch vor Restore erstellt",
                    name=None,
                    created_by_user_id=user_id,
                    username=username,
                    source="pre_restore",
                    payload_override=live_raw.copy(),
                )
            except Exception:
                pass  # pre-restore snapshot failure must not block the restore

        # Compute what to set/delete
        snap_payload = {k: v for k, v in detail.payload.items() if k not in {"description"} | _API_ONLY_KEYS}
        live_keys = set(live_for_etag)
        snap_keys = set(snap_payload)

        updates: dict[str, Any] = {}
        for k in snap_keys:
            if snap_payload[k] != live_for_etag.get(k):
                updates[k] = snap_payload[k]

        delete_keys = [k for k in live_keys if k not in snap_keys]

        if updates or delete_keys:
            try:
                await client.put_vm_config(
                    auth, proxmox_node, vmid,
                    updates=updates,
                    delete_keys=delete_keys or None,
                    vm_type=vm_type,
                )
            except Exception as exc:
                raise HTTPException(status_code=502, detail=f"proxmox_restore_failed: {exc}") from exc

        if restart_after_restore:
            try:
                status = await client.get_vm_status_current(auth, proxmox_node, vmid, vm_type=vm_type)
                if status.get("status") == "running":
                    await client.vm_power_action(auth, proxmox_node, vmid, "reboot", vm_type=vm_type)
            except Exception:
                pass  # restart failure is best-effort, not fatal

    finally:
        lock.release()

    await write_audit_log(
        "config_snapshot_restored",
        username=username,
        detail=f"snapshot_id={snapshot_id} kind={kind} vmid={vmid} node={proxmox_node}",
    )

    return {"status": "ok", "snapshot_id": snapshot_id}


async def restore_selected_keys(
    snapshot_id: str,
    keys: list[str],
    etag: str,
    username: str,
    user_id: Optional[int],
) -> dict:
    """Apply a user-selected subset of keys from a snapshot to the live VM.

    Unlike full restore, no vm_name_confirm or pre-restore snapshot is needed –
    the selection is explicit. ETag re-check still guards against stale diffs.
    """
    detail = await get_snapshot(snapshot_id)

    if detail.is_orphan:
        raise HTTPException(status_code=409, detail="cannot_restore_orphan")

    portal_node_id = detail.portal_node_id
    proxmox_node = detail.proxmox_node
    vmid = detail.vmid
    kind = detail.kind

    node = await _get_node_or_404(portal_node_id)
    client, auth = _admin_auth(node)
    vm_type = "qemu" if kind == "qemu" else "lxc"

    try:
        live_raw = await client.get_vm_config(auth, proxmox_node, vmid, vm_type=vm_type)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"proxmox_unreachable: {exc}") from exc

    live_for_etag = {k: v for k, v in live_raw.items() if k not in {"description"} | _API_ONLY_KEYS}
    live_etag = _etag_of(live_for_etag)
    if live_etag != etag:
        raise HTTPException(
            status_code=409,
            detail="live_config_changed",
            headers={"X-Live-ETag": live_etag},
        )

    lock_key = (portal_node_id, proxmox_node, vmid, kind)
    lock = await _get_restore_lock(lock_key)

    if lock.locked():
        raise HTTPException(status_code=409, detail="restore_in_progress")
    await lock.acquire()

    snap_payload = {k: v for k, v in detail.payload.items() if k not in {"description"} | _API_ONLY_KEYS}

    updates: dict[str, Any] = {}
    delete_keys: list[str] = []

    try:
        for key in keys:
            if key in snap_payload:
                updates[key] = snap_payload[key]
            elif key in live_for_etag:
                delete_keys.append(key)

        if updates or delete_keys:
            try:
                await client.put_vm_config(
                    auth, proxmox_node, vmid,
                    updates=updates,
                    delete_keys=delete_keys or None,
                    vm_type=vm_type,
                )
            except Exception as exc:
                raise HTTPException(status_code=502, detail=f"proxmox_restore_failed: {exc}") from exc
    finally:
        lock.release()

    await write_audit_log(
        "config_snapshot_keys_restored",
        username=username,
        detail=(
            f"snapshot_id={snapshot_id} keys={','.join(keys)} "
            f"kind={kind} vmid={vmid} node={proxmox_node}"
        ),
    )

    return {
        "status": "ok",
        "restored_keys": list(updates.keys()),
        "deleted_keys": delete_keys,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Download
# ═══════════════════════════════════════════════════════════════════════════════

async def download_snapshot_conf(snapshot_id: str) -> tuple[str, str]:
    """Return (filename, conf_text) for a single snapshot download."""
    detail = await get_snapshot(snapshot_id)
    _exclude = {"description"} | _API_ONLY_KEYS
    snap_keys = {k: v for k, v in detail.payload.items() if k not in _exclude}
    conf_text = render_conf(snap_keys, detail.description or "")
    filename = f"{detail.name}.conf"
    return filename, conf_text


async def bulk_download_snapshots(ids: list[str], username: str) -> bytes:
    """Build a ZIP archive (BytesIO) of up to 200 .conf files."""
    if len(ids) > _BULK_DOWNLOAD_CAP:
        raise HTTPException(status_code=422, detail=f"bulk_cap_exceeded:{_BULK_DOWNLOAD_CAP}")

    buf = io.BytesIO()
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    count = 0

    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for snap_id in ids:
            try:
                detail = await get_snapshot(snap_id)
            except HTTPException:
                continue
            _exclude = {"description"} | _API_ONLY_KEYS
            snap_keys = {k: v for k, v in detail.payload.items() if k not in _exclude}
            conf_text = render_conf(snap_keys, detail.description or "")
            safe_name = f"{detail.name}_{detail.id[:8]}.conf"
            zf.writestr(safe_name, conf_text)
            count += 1

    if count == 0:
        raise HTTPException(status_code=404, detail="no_snapshots_found")

    await write_audit_log(
        "config_snapshot_bulk_downloaded",
        username=username,
        detail=f"count={count}",
    )
    return buf.getvalue()


# ═══════════════════════════════════════════════════════════════════════════════
# Upload
# ═══════════════════════════════════════════════════════════════════════════════

async def upload_snapshot_conf(
    portal_node_id: int,
    proxmox_node: str,
    vmid: int,
    kind: str,
    file: UploadFile,
    note: str,
    username: str,
    user_id: Optional[int],
) -> UploadOut:
    """Upload a .conf file and store it as a snapshot.

    Applies 4-layer hardening (transport/encoding/parser/semantics).
    """
    # Layer 1 – transport limits
    filename = file.filename or ""
    if not _UPLOAD_FILENAME_RE.match(filename):
        raise HTTPException(status_code=422, detail="invalid_filename")

    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in _UPLOAD_ALLOWED_MIME:
        raise HTTPException(status_code=422, detail="unsupported_content_type")

    raw_bytes = await file.read(_UPLOAD_MAX_BYTES + 1)
    if len(raw_bytes) > _UPLOAD_MAX_BYTES:
        raise HTTPException(status_code=413, detail="file_too_large")

    # Layer 2 – encoding
    try:
        raw_text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=422, detail="invalid_encoding") from None

    # BOM strip
    if raw_text.startswith("﻿"):
        raw_text = raw_text[1:]

    lines = raw_text.splitlines()
    if len(lines) > _UPLOAD_MAX_LINES:
        raise HTTPException(status_code=422, detail="too_many_lines")
    for ln in lines:
        if len(ln) > _UPLOAD_MAX_LINE_CHARS:
            raise HTTPException(status_code=422, detail="line_too_long")

    # Layer 3 – parser (key whitelist + control-char check)
    node = await _get_node_or_404(portal_node_id)
    # fetch live VM name for Layer 4 mismatch warning
    vm_type = "qemu" if kind == "qemu" else "lxc"
    live_name: Optional[str] = None
    try:
        client, auth = _admin_auth(node)
        live_cfg = await client.get_vm_config(auth, proxmox_node, vmid, vm_type=vm_type)
        live_name = live_cfg.get("name") or live_cfg.get("hostname")
    except Exception:
        pass

    try:
        parsed = parse_conf_text(raw_text, kind=kind, expected_name=live_name)
    except UnsafeConfValue as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Layer 4 – semantics (vmid/meta already dropped in parser, name-mismatch in warnings)
    keys_before = len(lines)  # approximate — real count is in parser
    keys_dropped = sum(1 for w in parsed.warnings if w.startswith("unknown_key:"))

    snap_out = await create_snapshot(
        portal_node_id=portal_node_id,
        proxmox_node=proxmox_node,
        vmid=vmid,
        kind=kind,
        note=note,
        name=None,
        created_by_user_id=user_id,
        username=username,
        source="upload",
        payload_override=parsed.keys,
    )

    await write_audit_log(
        "config_snapshot_uploaded",
        username=username,
        detail=f"snapshot_id={snap_out.id} kind={kind} vmid={vmid} node={proxmox_node}",
    )

    return UploadOut(
        snapshot_id=snap_out.id,
        warnings=parsed.warnings,
        keys_dropped=keys_dropped,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Delete
# ═══════════════════════════════════════════════════════════════════════════════

async def delete_snapshot(snapshot_id: str, username: str) -> None:
    async with get_db() as db:
        result = await db.execute(
            text("SELECT id FROM vm_config_snapshots WHERE id = :id"),
            {"id": snapshot_id},
        )
        if not result.fetchone():
            raise HTTPException(status_code=404, detail="snapshot_not_found")
        await db.execute(
            text("DELETE FROM vm_config_snapshots WHERE id = :id"),
            {"id": snapshot_id},
        )
        await db.commit()

    await write_audit_log(
        "config_snapshot_deleted",
        username=username,
        detail=f"snapshot_id={snapshot_id}",
    )


async def bulk_delete_snapshots(ids: list[str], username: str) -> int:
    deleted = 0
    async with get_db() as db:
        for snap_id in ids:
            result = await db.execute(
                text("DELETE FROM vm_config_snapshots WHERE id = :id"),
                {"id": snap_id},
            )
            deleted += result.rowcount
        await db.commit()

    await write_audit_log(
        "config_snapshot_deleted",
        username=username,
        detail=f"bulk_delete count={deleted}",
    )
    return deleted


# ═══════════════════════════════════════════════════════════════════════════════
# Orphan management
# ═══════════════════════════════════════════════════════════════════════════════

async def list_orphans() -> list[OrphanOut]:
    async with get_db() as db:
        result = await db.execute(
            text(
                "SELECT * FROM vm_config_snapshots "
                "WHERE is_orphan = 1 "
                "ORDER BY orphaned_at DESC"
            )
        )
        rows = result.mappings().fetchall()
    return [
        OrphanOut(
            id=r["id"],
            proxmox_node=r["proxmox_node"],
            vmid=r["vmid"],
            kind=r["kind"],
            name=r["name"],
            note=r["note"],
            source=r["source"],
            created_at=r["created_at"],
            orphaned_at=r["orphaned_at"],
            vm_name_at_delete=r["vm_name_at_delete"],
        )
        for r in rows
    ]


async def delete_orphan(snapshot_id: str, username: str) -> None:
    async with get_db() as db:
        result = await db.execute(
            text(
                "SELECT id FROM vm_config_snapshots "
                "WHERE id = :id AND is_orphan = 1"
            ),
            {"id": snapshot_id},
        )
        if not result.fetchone():
            raise HTTPException(status_code=404, detail="orphan_not_found")
        await db.execute(
            text("DELETE FROM vm_config_snapshots WHERE id = :id"),
            {"id": snapshot_id},
        )
        await db.commit()

    await write_audit_log(
        "config_snapshot_orphan_deleted",
        username=username,
        detail=f"snapshot_id={snapshot_id}",
    )
