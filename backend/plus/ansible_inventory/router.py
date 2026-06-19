# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-83 Plus: Key-Management-Endpoints (Pool-/Global-Keypair).

Prefix /api/ansible-inventory/keys. 404 in Pure Core (can_use_ansible_inventory).
RBAC: manage_ansible_inventory (Plus, delegierbar) ODER admin. Private Keys werden
NIE ausgegeben – nur Public Keys.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text

from backend.core.deps import CurrentUser, get_current_user
from backend.core.plus_protocol import plus_behavior
from backend.db.database import get_db
from backend.features.ansible_inventory import host_state, inventory as _inv
from backend.features.ansible_inventory.onboarding import render_onboarding_block
from backend.features.ansible_inventory.permissions import has_manage_inventory
from backend.features.api_surface.deps import require_scope_for_upk  # PROJ-97
from backend.plus.ansible_inventory import keys_plus
from backend.services.audit_service import write_audit_log

# PROJ-97: upk_-Scope-Gates (No-Op für JWT). Geteilt von keys- und discovery-Router.
# Edition-Gate (_check_plus → 404) bleibt orthogonal und greift im Funktionskörper.
_SCOPE_READ = Depends(require_scope_for_upk("ansible_inventory:read"))
_SCOPE_WRITE = Depends(require_scope_for_upk("ansible_inventory:write"))

router = APIRouter(prefix="/api/ansible-inventory/keys", tags=["ansible-inventory"])


class PublicKeyOut(BaseModel):
    public_key: str


def _check_plus() -> None:
    if not plus_behavior.can_use_ansible_inventory():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")


def _require_manage(current_user: CurrentUser) -> None:
    if not has_manage_inventory(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")


@router.get("/global/public", response_model=PublicKeyOut, dependencies=[_SCOPE_READ])
async def global_public(current_user: CurrentUser = Depends(get_current_user)) -> PublicKeyOut:
    _check_plus()
    _require_manage(current_user)
    return PublicKeyOut(public_key=await keys_plus.get_global_public_key() or "")


@router.post("/global/rotate", response_model=PublicKeyOut, dependencies=[_SCOPE_WRITE])
async def global_rotate(current_user: CurrentUser = Depends(get_current_user)) -> PublicKeyOut:
    _check_plus()
    _require_manage(current_user)
    pub = await keys_plus.rotate_global_keypair()
    await write_audit_log(
        "ansible_global_key_rotated", current_user.username, current_user.auth_type,
        detail="global ansible keypair rotated",
    )
    return PublicKeyOut(public_key=pub)


@router.get("/pool/{pool_id}/public", response_model=PublicKeyOut, dependencies=[_SCOPE_READ])
async def pool_public(
    pool_id: int, current_user: CurrentUser = Depends(get_current_user)
) -> PublicKeyOut:
    _check_plus()
    _require_manage(current_user)
    return PublicKeyOut(public_key=await keys_plus.get_pool_public_key(pool_id) or "")


@router.post("/pool/{pool_id}/rotate", response_model=PublicKeyOut, dependencies=[_SCOPE_WRITE])
async def pool_rotate(
    pool_id: int, current_user: CurrentUser = Depends(get_current_user)
) -> PublicKeyOut:
    _check_plus()
    _require_manage(current_user)
    pub = await keys_plus.rotate_pool_keypair(pool_id)
    await write_audit_log(
        "ansible_pool_key_rotated", current_user.username, current_user.auth_type,
        detail=f"pool {pool_id} ansible keypair rotated",
    )
    return PublicKeyOut(public_key=pub)


# ══════════════════════════════════════════════════════════════════════════════
# PROJ-84: node-/installations-weite Discovery + Onboarding (ownership-frei).
# Eigener Router unter /api/ansible-inventory (nicht /keys). 404 in Pure Core.
# ══════════════════════════════════════════════════════════════════════════════

discovery_router = APIRouter(prefix="/api/ansible-inventory", tags=["ansible-inventory"])


class DiscoveryHostOut(BaseModel):
    host_ref: str
    portal_node_id: int
    proxmox_node: str | None = None
    vmid: int
    kind: str
    name: str = ""
    status: str = ""
    managed: bool
    in_run_scope: bool
    ip: str | None = None


class DiscoveryOut(BaseModel):
    portal_node_id: int
    error: str | None = None
    hosts: list[DiscoveryHostOut] = []


class OnboardRequest(BaseModel):
    portal_node_id: int
    kind: str
    vmid: int
    include_pool_key: bool = False


class OnboardOut(BaseModel):
    detail: str
    host_ref: str
    block: str
    key_count: int
    skipped_already_managed: bool = False


class BulkOnboardHost(BaseModel):
    portal_node_id: int
    kind: str
    vmid: int


class BulkOnboardRequest(BaseModel):
    hosts: list[BulkOnboardHost]
    include_pool_key: bool = False


class BulkOnboardResult(BaseModel):
    onboarded: int = 0
    skipped: int = 0
    failed: list[dict] = []


async def _host_pool_id(portal_node_id: int, vmid: int, kind: str) -> int | None:
    """Erste Pool-Mitgliedschaft eines Hosts (für optionalen Pool-Key)."""
    resource_type = "lxc" if kind == "lxc" else "vm"
    async with get_db() as db:
        row = (await db.execute(
            text(
                "SELECT pool_id FROM pool_members "
                "WHERE node_id = :nid AND vmid = :vmid AND resource_type = :rt LIMIT 1"
            ),
            {"nid": portal_node_id, "vmid": vmid, "rt": resource_type},
        )).mappings().fetchone()
    return int(row["pool_id"]) if row else None


async def _onboard_one(portal_node_id: int, vmid: int, kind: str, include_pool_key: bool) -> tuple[list[str], bool]:
    """Onboardet einen Host ownership-frei: Global(+optional Pool)-Key + ssh_managed + global_opt_in.
    Gibt (public_keys, already_managed) zurück."""
    pool_id = await _host_pool_id(portal_node_id, vmid, kind) if include_pool_key else None
    pub_keys = await plus_behavior.get_injection_public_keys_extra(pool_id, True)
    prev = await host_state.get_host_state(portal_node_id, vmid, kind)
    already = bool(prev and prev["ssh_managed"] and prev["global_opt_in"])
    await host_state.set_managed(portal_node_id, vmid, kind, global_opt_in=True)
    return pub_keys, already


@discovery_router.get("/discovery", response_model=DiscoveryOut, dependencies=[_SCOPE_READ])
async def discovery(
    node: int,
    current_user: CurrentUser = Depends(get_current_user),
) -> DiscoveryOut:
    """Listet ALLE QEMU+LXC einer Installation mit Managed-/Run-Scope-Status (ownership-unabhängig).
    RBAC: manage_ansible_inventory/Admin; 404 in Pure Core."""
    _check_plus()
    _require_manage(current_user)
    result = await _inv.build_discovery(node)
    return DiscoveryOut(
        portal_node_id=result["portal_node_id"],
        error=result.get("error"),
        hosts=[DiscoveryHostOut(**h) for h in result.get("hosts", [])],
    )


@discovery_router.post("/onboard", response_model=OnboardOut, dependencies=[_SCOPE_WRITE])
async def onboard(
    body: OnboardRequest,
    current_user: CurrentUser = Depends(get_current_user),
) -> OnboardOut:
    """Onboardet einen bestehenden Host ownership-frei (Global-Key) → Global-Scope-ausführbar.
    Liefert den Onboarding-Block zum manuellen Einfügen zurück. Idempotent."""
    _check_plus()
    _require_manage(current_user)
    if body.kind not in ("qemu", "lxc"):
        raise HTTPException(status_code=422, detail="invalid_kind")
    pub_keys, already = await _onboard_one(body.portal_node_id, body.vmid, body.kind, body.include_pool_key)
    await write_audit_log(
        "ansible_host_onboarded", current_user.username, current_user.auth_type,
        detail=(f"node={body.portal_node_id} vmid={body.vmid} kind={body.kind} "
                f"keys={len(pub_keys)} pool_key={body.include_pool_key}"),
    )
    return OnboardOut(
        detail="onboarded",
        host_ref=_inv.host_ref(body.portal_node_id, body.vmid, body.kind),
        block=render_onboarding_block(pub_keys),
        key_count=len(pub_keys),
        skipped_already_managed=already,
    )


@discovery_router.post("/onboard/bulk", response_model=BulkOnboardResult, dependencies=[_SCOPE_WRITE])
async def onboard_bulk(
    body: BulkOnboardRequest,
    current_user: CurrentUser = Depends(get_current_user),
) -> BulkOnboardResult:
    """Bulk-Onboarding mehrerer Hosts (Partial-Success pro Host)."""
    _check_plus()
    _require_manage(current_user)
    res = BulkOnboardResult()
    for h in body.hosts:
        ref = _inv.host_ref(h.portal_node_id, h.vmid, h.kind)
        if h.kind not in ("qemu", "lxc"):
            res.failed.append({"host_ref": ref, "reason": "invalid_kind"})
            continue
        try:
            _keys, already = await _onboard_one(h.portal_node_id, h.vmid, h.kind, body.include_pool_key)
            if already:
                res.skipped += 1
            else:
                res.onboarded += 1
        except Exception as exc:
            res.failed.append({"host_ref": ref, "reason": str(exc)[:120]})
    await write_audit_log(
        "ansible_hosts_onboarded", current_user.username, current_user.auth_type,
        detail=(f"onboarded={res.onboarded} skipped={res.skipped} failed={len(res.failed)} "
                f"pool_key={body.include_pool_key}"),
    )
    return BulkOnboardResult(onboarded=res.onboarded, skipped=res.skipped, failed=res.failed)
