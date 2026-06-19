# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-85: Stacks Cloud-Init-Login store + resolver (Tech-Design B/H/K).

The cloud-init data lives in its own encrypted table (``stack_cloud_init``),
deliberately **outside** the stack YAML / version history / diff / approval
(AC-STORE-1/3). One row per target: ``vm_name = ''`` = stack default,
``vm_name = <resource_name>`` = per-VM override.

  * ``get_cloud_init``        : read default + overrides (password NEVER in the
                                clear — only ``password_set``, AC-STORE-4).
  * ``put_cloud_init``        : full replace + write-only password merge (EC-6)
                                + lockout (AC-ACT-4) + static+count>1 (AC-IP-3)
                                gates → 422.
  * ``resolve_for_transpile`` : decrypt + resolve (override > disabled-override
                                suppresses > default > none, Tech-Design H) into
                                a ``{resolved_vm_name: CloudInitResolved}`` map
                                that the (pure) transpiler injects as bpg
                                ``initialization{}``. Re-runs the gates (the spec
                                may have changed since the cloud-init save).

The password is Fernet-encrypted at rest (``config_service.encrypt_secret``,
same mechanism as Node-Tokens — SECRET_KEY-derived, so a SECRET_KEY rotation
means re-entering the password). It is decrypted only here, transiently, when
``main.tf.json`` is written (Tech-Design E).
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import text

from backend.db.database import get_db
from backend.services.audit_service import write_audit_log
from backend.services.config_service import decrypt_secret, encrypt_secret

from . import service, transpile, validation
from .schemas import (
    CloudInitBlock,
    CloudInitBlockOut,
    CloudInitConfigRequest,
    CloudInitConfigResponse,
    StackCreateRequest,
)

logger = logging.getLogger(__name__)

_DEFAULT_SENTINEL = ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Resolved (decrypted) block handed to the pure transpiler ─────────────────

@dataclass
class CloudInitResolved:
    """One fully-resolved + decrypted cloud-init block for a single VM."""
    username: str
    password: Optional[str]            # decrypted plaintext or None
    ssh_keys: list[str] = field(default_factory=list)
    ip_mode: Optional[str] = None      # 'dhcp' | 'static' | None
    ip_address_cidr: Optional[str] = None
    ip_gateway: Optional[str] = None
    dns_servers: list[str] = field(default_factory=list)
    dns_domain: Optional[str] = None


def _split_dns(raw: Optional[str]) -> list[str]:
    if not raw:
        return []
    return [s for s in re.split(r"[,\s]+", raw.strip()) if s]


# ── Spec helpers ──────────────────────────────────────────────────────────────

async def _load_spec(stack_id: int):
    """Parse the stack's stored yaml_text into a StackSpec (None if corrupt)."""
    row = await service._get_stack_row(stack_id)
    try:
        spec, _canonical, errors, _warnings = await validation.validate_request(
            StackCreateRequest(yaml_text=row["yaml_text"])
        )
        return spec
    except Exception:  # pragma: no cover – defensive
        return None


def _resource_by_name(spec) -> dict[str, object]:
    """Map base resource name → VMResource (the override key, AC-TRANS-2)."""
    if spec is None:
        return {}
    return {r.name: r for r in spec.resources}


# ── Validation gates (lockout + static+count>1) ───────────────────────────────

@dataclass
class _NormBlock:
    """Normalized view for the gates (works for PUT input and DB rows alike)."""
    vm_name: str
    enabled: bool
    username: Optional[str]
    has_password: bool
    has_ssh_keys: bool
    ip_mode: Optional[str]


def _validate_blocks(
    default: _NormBlock,
    overrides: list[_NormBlock],
    resource_by_name: dict[str, object],
) -> list[str]:
    """Lockout (AC-ACT-4) + static+count>1 (AC-IP-3). Returns error strings.

    ``resource_by_name`` may be empty (corrupt/unparseable spec) → the count
    check is skipped (best-effort), the lockout check still runs.

    PROJ-86: the lockout is typ-aware — a key OR a password is required for
    every active block (VM **and** LXC), but ``username`` is required **only**
    when the block covers at least one VM target (an LXC logs in as root,
    AC-GUEST-3). When the spec can't be parsed (empty ``resource_by_name``) we
    conservatively require username (legacy VM-only behavior).
    """
    errors: list[str] = []

    def _lockout(b: _NormBlock, label: str, targets) -> None:
        if not b.enabled:
            return
        if not b.has_ssh_keys and not b.has_password:
            errors.append(
                f"{label}: an SSH key or a password is required "
                f"(lockout protection)"
            )
        # username only matters for VM targets (LXC = root). Unknown targets
        # (corrupt spec) → conservatively require it.
        covers_vm = (not resource_by_name) or any(
            getattr(t, "type", "vm") == "vm" for t in targets
        )
        if covers_vm and not (b.username and b.username.strip()):
            errors.append(f"{label}: username is required when cloud-init is enabled")

    def _static_count(b: _NormBlock, label: str, targets) -> None:
        if not b.enabled or b.ip_mode != "static" or not resource_by_name:
            return
        offenders = [getattr(r, "name") for r in targets if getattr(r, "count", 1) > 1]
        if offenders:
            errors.append(
                f"{label}: static IP cannot be combined with count>1 "
                f"({', '.join(offenders)}); use DHCP or count=1"
            )

    active_override_names = {b.vm_name for b in overrides if b.enabled}
    disabled_override_names = {b.vm_name for b in overrides if not b.enabled}

    # Default applies to every resource that is neither actively overridden nor
    # explicitly suppressed by a disabled override.
    covered = [
        r for name, r in resource_by_name.items()
        if name not in active_override_names and name not in disabled_override_names
    ]
    _lockout(default, "default", covered)
    _static_count(default, "default", covered)

    for b in overrides:
        if resource_by_name and b.vm_name not in resource_by_name:
            continue  # orphan override → ignored (EC-4)
        target = [resource_by_name[b.vm_name]] if b.vm_name in resource_by_name else []
        _lockout(b, f"override '{b.vm_name}'", target)
        _static_count(b, f"override '{b.vm_name}'", target)

    return errors


# ── Read ──────────────────────────────────────────────────────────────────────

async def _read_rows(stack_id: int) -> dict[str, dict]:
    """All cloud-init rows of a stack keyed by vm_name ('' = default)."""
    async with get_db() as db:
        result = await db.execute(
            text("SELECT * FROM stack_cloud_init WHERE stack_id = :sid"),
            {"sid": stack_id},
        )
        rows = result.mappings().fetchall()
    return {r["vm_name"]: dict(r) for r in rows}


def _row_to_out(row: Optional[dict], vm_name: str, orphan: bool = False) -> CloudInitBlockOut:
    if row is None:
        return CloudInitBlockOut(vm_name=vm_name, enabled=False)
    return CloudInitBlockOut(
        vm_name=vm_name,
        enabled=bool(row["enabled"]),
        username=row.get("username"),
        password_set=bool(row.get("password_enc")),
        ssh_keys=json.loads(row["ssh_keys_json"]) if row.get("ssh_keys_json") else [],
        ip_mode=row.get("ip_mode"),
        ip_address_cidr=row.get("ip_address_cidr"),
        ip_gateway=row.get("ip_gateway"),
        dns_servers=row.get("dns_servers"),
        dns_domain=row.get("dns_domain"),
        orphan=orphan,
    )


async def get_cloud_init(stack_id: int) -> CloudInitConfigResponse:
    """Read the default + overrides; password never in the clear (AC-STORE-4)."""
    await service._get_stack_row(stack_id)  # 404 if missing/deleted
    rows = await _read_rows(stack_id)
    spec = await _load_spec(stack_id)
    current_names = set(_resource_by_name(spec).keys())

    default_out = _row_to_out(rows.get(_DEFAULT_SENTINEL), _DEFAULT_SENTINEL)
    overrides_out: list[CloudInitBlockOut] = []
    for vm_name, row in rows.items():
        if vm_name == _DEFAULT_SENTINEL:
            continue
        # If we could parse the spec, flag overrides whose name vanished (EC-4).
        orphan = bool(current_names) and vm_name not in current_names
        overrides_out.append(_row_to_out(row, vm_name, orphan=orphan))
    overrides_out.sort(key=lambda b: b.vm_name)
    return CloudInitConfigResponse(default=default_out, overrides=overrides_out)


# ── Write (full replace + password merge) ─────────────────────────────────────

def _norm_from_input(b: CloudInitBlock, existing_pw: bool) -> _NormBlock:
    return _NormBlock(
        vm_name=b.vm_name,
        enabled=b.enabled,
        username=b.username,
        has_password=bool(b.password) or existing_pw,
        has_ssh_keys=bool(b.ssh_keys),
        ip_mode=b.ip_mode,
    )


async def put_cloud_init(
    stack_id: int, req: CloudInitConfigRequest, username: str,
) -> CloudInitConfigResponse:
    """Full replace of the cloud-init config + write-only password merge (EC-6).

    Validates lockout + static+count>1 (422) against the *current* spec before
    writing. Empty/omitted password = keep the stored one. Audits without secrets
    (AC-SEC-3).
    """
    await service._get_stack_row(stack_id)  # 404 if missing/deleted
    spec = await _load_spec(stack_id)
    resource_by_name = _resource_by_name(spec)

    existing = await _read_rows(stack_id)

    # Build normalized views for the gates (existing password counts, EC-6).
    default_norm = _norm_from_input(
        req.default, bool(existing.get(_DEFAULT_SENTINEL, {}).get("password_enc"))
    )
    override_norms = [
        _norm_from_input(o, bool(existing.get(o.vm_name, {}).get("password_enc")))
        for o in req.overrides
    ]
    errors = _validate_blocks(default_norm, override_norms, resource_by_name)
    if errors:
        raise HTTPException(status_code=422, detail={"errors": errors})

    # Reject two overrides for the same vm_name (UNIQUE would also catch it).
    seen: set[str] = set()
    for o in req.overrides:
        if not o.vm_name:
            raise HTTPException(status_code=422, detail="override requires a vm_name")
        if o.vm_name in seen:
            raise HTTPException(status_code=422, detail=f"duplicate override for '{o.vm_name}'")
        seen.add(o.vm_name)

    now = _now()
    blocks: list[tuple[str, CloudInitBlock]] = [(_DEFAULT_SENTINEL, req.default)]
    blocks += [(o.vm_name, o) for o in req.overrides]

    async with get_db() as db:
        # Full replace: drop all rows, re-insert default + overrides.
        await db.execute(
            text("DELETE FROM stack_cloud_init WHERE stack_id = :sid"),
            {"sid": stack_id},
        )
        for vm_name, b in blocks:
            # Password merge: non-empty = (re)encrypt; empty/None = keep existing.
            if b.password:
                pw_enc = encrypt_secret(b.password)
            else:
                pw_enc = existing.get(vm_name, {}).get("password_enc")
            await db.execute(
                text(
                    "INSERT INTO stack_cloud_init "
                    "(stack_id, vm_name, enabled, username, password_enc, ssh_keys_json, "
                    " ip_mode, ip_address_cidr, ip_gateway, dns_servers, dns_domain, "
                    " created_at, updated_at) "
                    "VALUES (:sid, :vm, :en, :user, :pw, :keys, :ipm, :cidr, :gw, "
                    " :dnss, :dnsd, :now, :now)"
                ),
                {
                    "sid": stack_id,
                    "vm": vm_name,
                    "en": b.enabled,
                    "user": b.username,
                    "pw": pw_enc,
                    "keys": json.dumps(b.ssh_keys) if b.ssh_keys else None,
                    "ipm": b.ip_mode,
                    "cidr": b.ip_address_cidr,
                    "gw": b.ip_gateway,
                    "dnss": b.dns_servers,
                    "dnsd": b.dns_domain,
                    "now": now,
                },
            )
        await db.commit()

    changed = sorted(vm or "default" for vm, _ in blocks)
    any_pw = any(b.password for _, b in blocks) or any(
        e.get("password_enc") for e in existing.values()
    )
    await write_audit_log(
        "stack_cloudinit_updated", username=username,
        detail=(
            f"stack_id={stack_id} targets={','.join(changed)} "
            f"password_set={'true' if any_pw else 'false'}"
        ),
    )
    return await get_cloud_init(stack_id)


# ── Resolve for transpile (decrypt + apply default/override logic) ────────────

def _row_to_resolved(row: dict) -> CloudInitResolved:
    pw: Optional[str] = None
    if row.get("password_enc"):
        try:
            pw = decrypt_secret(row["password_enc"])
        except Exception:  # pragma: no cover – key rotated / corrupt blob
            logger.warning(
                "PROJ-85: cloud-init password decrypt failed for stack row id=%s "
                "(SECRET_KEY rotated?) — deploying without a password",
                row.get("id"),
            )
            pw = None
    keys = json.loads(row["ssh_keys_json"]) if row.get("ssh_keys_json") else []
    return CloudInitResolved(
        username=row.get("username") or "",
        password=pw,
        ssh_keys=keys,
        ip_mode=row.get("ip_mode"),
        ip_address_cidr=row.get("ip_address_cidr"),
        ip_gateway=row.get("ip_gateway"),
        dns_servers=_split_dns(row.get("dns_servers")),
        dns_domain=row.get("dns_domain"),
    )


def _norm_from_row(vm_name: str, row: dict) -> _NormBlock:
    return _NormBlock(
        vm_name=vm_name,
        enabled=bool(row.get("enabled")),
        username=row.get("username"),
        has_password=bool(row.get("password_enc")),
        has_ssh_keys=bool(row.get("ssh_keys_json") and json.loads(row["ssh_keys_json"])),
        ip_mode=row.get("ip_mode"),
    )


async def resolve_for_transpile(
    stack_id: int, spec, *, gate: bool = True,
) -> dict[str, CloudInitResolved]:
    """Resolve the cloud-init config for every expanded VM name (Tech-Design H).

    Returns ``{resolved_vm_name: CloudInitResolved}`` — only VMs that get an
    active block appear. The resolution per resource ``r``:

      1. active override for ``r.name``        → use it
      2. disabled override for ``r.name``      → no block (suppress, AC-ACT-3)
      3. else stack default active             → use default
      4. else                                  → no block (template inheritance)

    ``gate=True`` re-runs the lockout + static+count>1 gates (the spec may have
    changed since the save) and raises 422 on violation — done **before** any
    tofu run. ``gate=False`` (destroy) skips the gates (IP is irrelevant; a
    valid-at-save config must not block a teardown).
    """
    rows = await _read_rows(stack_id)
    if not rows:
        return {}

    default_row = rows.get(_DEFAULT_SENTINEL)
    override_rows = {n: r for n, r in rows.items() if n != _DEFAULT_SENTINEL}

    if gate:
        resource_by_name = _resource_by_name(spec)
        default_norm = (
            _norm_from_row(_DEFAULT_SENTINEL, default_row)
            if default_row else
            _NormBlock(_DEFAULT_SENTINEL, False, None, False, False, None)
        )
        override_norms = [_norm_from_row(n, r) for n, r in override_rows.items()]
        errors = _validate_blocks(default_norm, override_norms, resource_by_name)
        if errors:
            raise HTTPException(status_code=422, detail={"errors": errors})

    out: dict[str, CloudInitResolved] = {}
    for r in spec.resources:
        ov = override_rows.get(r.name)
        if ov is not None:
            if not bool(ov.get("enabled")):
                continue  # disabled override suppresses (AC-ACT-3)
            chosen, label = ov, f"override '{r.name}'"
        elif default_row is not None and bool(default_row.get("enabled")):
            chosen, label = default_row, "default"
        else:
            continue  # no block → template inheritance (Weg 1)
        resolved = _row_to_resolved(chosen)
        # OBS-2 (/qa S629): the save-gate enforced username + (key OR password),
        # but at deploy time a stored password can be undecryptable (most likely a
        # SECRET_KEY rotation; ``_row_to_resolved`` then sets password=None). If
        # neither a decrypted password nor an SSH key survives, deploying would
        # create a locked-out VM → block with a clear 422 instead of silently
        # shipping it. A block that still has a key deploys fine (no lockout).
        if gate and not resolved.password and not resolved.ssh_keys:
            raise HTTPException(
                status_code=422,
                detail={"errors": [
                    f"{label}: cloud-init credential unavailable for '{r.name}' "
                    f"— the stored password is not decryptable (SECRET_KEY rotated?) "
                    f"and no SSH key is set. Re-enter the password in the Cloud-Init tab."
                ]},
            )
        for name in transpile._expanded_names(r):
            out[name] = resolved
    return out
