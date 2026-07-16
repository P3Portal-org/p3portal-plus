# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-42 Phase 2: Allocation-Lebenszyklus des internen Plus-IPAM.

Zustandsbehaftete Ebene über dem best-effort Core-Simple-IPAM (Phase 1). „Frei"
wird verlässlich gegen ``ip_allocations`` berechnet (nicht nur live aus Proxmox);
Reservierungen sind race-sicher über den Unique-Constraint ``(pool_id, ip)``.

Lebenszyklus: pending (reserviert beim Deploy-Start) → confirmed (Deploy ok) →
Freigabe (Job-Fehler / VM-Löschen) bzw. orphaned (VM außerhalb P3 verschwunden).
Nie bestätigte ``pending`` verfallen (Lazy-Sweep, TTL 30 Min) → keine Pool-Leaks.

Alle zustandsbehafteten Operationen respektieren den ``global_enabled``-Toggle:
ist IPAM global AUS, reserviert nichts (Phase-1-best-effort bleibt) – kein
Upgrade-Bruch (Tech-Design P2.B).
"""
from __future__ import annotations

import ipaddress
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from backend.db.database import get_db
from backend.features.ipam import service as core_pools
from backend.features.ipam.schemas import IpPoolResponse

from . import config_service
from .schemas import AllocationResponse, PoolUsageResponse

logger = logging.getLogger(__name__)

# Verfall nie bestätigter Reservierungen (Lazy-Sweep beim nächsten Zugriff).
PENDING_TTL_MINUTES = 30

# Status, die eine IP als belegt zählen (frei = alles außerhalb dieser Menge).
_ACTIVE = ("pending", "confirmed", "orphaned")


class IpamReservationConflict(Exception):
    """Die gewünschte IP ist bereits reserviert/belegt (Unique-Constraint (pool_id, ip))."""

    def __init__(self, ip: str, pool_id: int):
        self.ip = ip
        self.pool_id = pool_id
        super().__init__(f"IP {ip} in Pool {pool_id} bereits belegt")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _expiry() -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=PENDING_TTL_MINUTES)).isoformat()


def _row_to_alloc(row) -> AllocationResponse:
    return AllocationResponse(
        id=row["id"],
        pool_id=row["pool_id"],
        ip=row["ip"],
        status=row["status"],
        source=row["source"],
        vmid=row["vmid"],
        portal_node_id=row["portal_node_id"],
        owner_username=row["owner_username"],
        job_id=row["job_id"],
        stack_deployment_id=row["stack_deployment_id"],
        note=row["note"],
        created_at=row["created_at"],
        confirmed_at=row["confirmed_at"],
        pending_expires_at=row["pending_expires_at"],
    )


# ── Lazy-Sweep abgelaufener pending ──────────────────────────────────────────

async def sweep_expired_pending() -> int:
    """Gibt abgelaufene ``pending``-Reservierungen frei (verhindert Pool-Leaks)."""
    async with get_db() as db:
        result = await db.execute(
            text(
                "DELETE FROM ip_allocations "
                "WHERE status = 'pending' AND pending_expires_at IS NOT NULL "
                "AND pending_expires_at < :now"
            ),
            {"now": _now()},
        )
        count = result.rowcount
        await db.commit()
    if count:
        logger.debug("PROJ-42: %d abgelaufene pending-Reservierungen freigegeben", count)
    return count


# ── belegte IPs (für Core-suggest + Free-IP-Berechnung) ──────────────────────

async def reserved_ips(pool_id: int) -> set[str]:
    """Alle in ``ip_allocations`` belegten IPs eines Pools (aktive Status).

    Respektiert ``global_enabled``: AUS → leere Menge (Phase-1-best-effort bleibt,
    keine Reservierungssicht). Wird lazy-sweep-bereinigt.
    """
    if not await config_service.is_global_enabled():
        return set()
    await sweep_expired_pending()
    async with get_db() as db:
        result = await db.execute(
            text(
                "SELECT ip FROM ip_allocations "
                "WHERE pool_id = :pid AND status IN ('pending', 'confirmed', 'orphaned')"
            ),
            {"pid": pool_id},
        )
        rows = result.mappings().fetchall()
    return {r["ip"] for r in rows}


# ── Reservierung (pending) ───────────────────────────────────────────────────

async def reserve_specific(
    pool_id: int,
    ip: str,
    owner_username: Optional[str],
    source: str,
    job_id: Optional[str] = None,
    stack_deployment_id: Optional[int] = None,
    vmid: Optional[int] = None,
    portal_node_id: Optional[int] = None,
) -> AllocationResponse:
    """Reserviert eine KONKRETE IP als ``pending`` (race-sicher via Unique).

    Kollision → ``IpamReservationConflict`` (die IP steckt bereits in ExtraVars/
    Cloud-Init → nicht still umschreiben, Deploy scheitert früh).
    """
    await sweep_expired_pending()
    payload = {
        "pool_id": pool_id,
        "ip": ip,
        "status": "pending",
        "source": source,
        "owner_username": owner_username,
        "job_id": job_id,
        "stack_deployment_id": stack_deployment_id,
        "vmid": vmid,
        "portal_node_id": portal_node_id,
        "created_at": _now(),
        "pending_expires_at": _expiry(),
    }
    async with get_db() as db:
        try:
            result = await db.execute(
                text(
                    "INSERT INTO ip_allocations "
                    "(pool_id, ip, status, source, owner_username, job_id, "
                    " stack_deployment_id, vmid, portal_node_id, created_at, pending_expires_at) "
                    "VALUES (:pool_id, :ip, :status, :source, :owner_username, :job_id, "
                    " :stack_deployment_id, :vmid, :portal_node_id, :created_at, :pending_expires_at) "
                    "RETURNING id"
                ),
                payload,
            )
            new_id = result.fetchone()[0]
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise IpamReservationConflict(ip, pool_id)
    return await get_allocation(new_id)


# ── Bestätigung / Freigabe ───────────────────────────────────────────────────

async def confirm_by_job(job_id: str, vmid: Optional[int] = None,
                         portal_node_id: Optional[int] = None) -> int:
    """pending → confirmed für die zu ``job_id`` gehörende Reservierung."""
    sets = ["status = 'confirmed'", "confirmed_at = :now", "pending_expires_at = NULL"]
    params: dict = {"now": _now(), "jid": job_id}
    if vmid is not None:
        sets.append("vmid = :vmid")
        params["vmid"] = vmid
    if portal_node_id is not None:
        sets.append("portal_node_id = :pnid")
        params["pnid"] = portal_node_id
    async with get_db() as db:
        result = await db.execute(
            text(
                f"UPDATE ip_allocations SET {', '.join(sets)} "
                "WHERE job_id = :jid AND status = 'pending'"
            ),
            params,
        )
        count = result.rowcount
        await db.commit()
    return count


async def release_pending_by_job(job_id: str) -> int:
    """Job fehlgeschlagen → ``pending``-Reservierung freigeben (confirmed bleibt)."""
    async with get_db() as db:
        result = await db.execute(
            text("DELETE FROM ip_allocations WHERE job_id = :jid AND status = 'pending'"),
            {"jid": job_id},
        )
        count = result.rowcount
        await db.commit()
    return count


async def confirm_by_stack(stack_deployment_id: int, vmid: Optional[int] = None,
                           portal_node_id: Optional[int] = None) -> int:
    sets = ["status = 'confirmed'", "confirmed_at = :now", "pending_expires_at = NULL"]
    params: dict = {"now": _now(), "sid": stack_deployment_id}
    if vmid is not None:
        sets.append("vmid = :vmid")
        params["vmid"] = vmid
    if portal_node_id is not None:
        sets.append("portal_node_id = :pnid")
        params["pnid"] = portal_node_id
    async with get_db() as db:
        result = await db.execute(
            text(
                f"UPDATE ip_allocations SET {', '.join(sets)} "
                "WHERE stack_deployment_id = :sid AND status = 'pending'"
            ),
            params,
        )
        count = result.rowcount
        await db.commit()
    return count


async def release_pending_by_stack(stack_deployment_id: int) -> int:
    async with get_db() as db:
        result = await db.execute(
            text(
                "DELETE FROM ip_allocations "
                "WHERE stack_deployment_id = :sid AND status = 'pending'"
            ),
            {"sid": stack_deployment_id},
        )
        count = result.rowcount
        await db.commit()
    return count


async def release_by_id(alloc_id: int) -> bool:
    async with get_db() as db:
        result = await db.execute(
            text("DELETE FROM ip_allocations WHERE id = :id"), {"id": alloc_id}
        )
        await db.commit()
    return result.rowcount > 0


# ── manuelle Fremd-IP ────────────────────────────────────────────────────────

async def add_manual(pool_id: int, ip: str, note: Optional[str],
                     owner_username: Optional[str]) -> AllocationResponse:
    """Eine Fremd-IP (Nicht-Proxmox) direkt als ``confirmed`` eintragen."""
    payload = {
        "pool_id": pool_id,
        "ip": ip,
        "status": "confirmed",
        "source": "manual",
        "owner_username": owner_username,
        "note": note,
        "created_at": _now(),
        "confirmed_at": _now(),
    }
    async with get_db() as db:
        try:
            result = await db.execute(
                text(
                    "INSERT INTO ip_allocations "
                    "(pool_id, ip, status, source, owner_username, note, created_at, confirmed_at) "
                    "VALUES (:pool_id, :ip, :status, :source, :owner_username, :note, "
                    " :created_at, :confirmed_at) RETURNING id"
                ),
                payload,
            )
            new_id = result.fetchone()[0]
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise IpamReservationConflict(ip, pool_id)
    return await get_allocation(new_id)


# ── Abfragen ─────────────────────────────────────────────────────────────────

async def get_allocation(alloc_id: int) -> AllocationResponse:
    async with get_db() as db:
        result = await db.execute(
            text("SELECT * FROM ip_allocations WHERE id = :id"), {"id": alloc_id}
        )
        row = result.mappings().fetchone()
    return _row_to_alloc(row)


async def list_allocations(pool_id: Optional[int] = None,
                           status: Optional[str] = None) -> list[AllocationResponse]:
    await sweep_expired_pending()
    clauses = []
    params: dict = {}
    if pool_id is not None:
        clauses.append("pool_id = :pid")
        params["pid"] = pool_id
    if status is not None:
        clauses.append("status = :st")
        params["st"] = status
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    async with get_db() as db:
        result = await db.execute(
            text(f"SELECT * FROM ip_allocations{where} ORDER BY pool_id, ip"), params
        )
        rows = result.mappings().fetchall()
    return [_row_to_alloc(r) for r in rows]


async def get_allocation_for_vm(portal_node_id: int, vmid: int) -> Optional[dict]:
    """IPAM-Allocation einer VM (VM/LXC-Detailseite). Best-effort neueste zuerst."""
    async with get_db() as db:
        result = await db.execute(
            text(
                "SELECT * FROM ip_allocations "
                "WHERE portal_node_id = :pnid AND vmid = :vmid "
                "AND status IN ('confirmed', 'orphaned') "
                "ORDER BY id DESC LIMIT 1"
            ),
            {"pnid": portal_node_id, "vmid": vmid},
        )
        row = result.mappings().fetchone()
    return dict(row) if row else None


def _pool_total_hosts(pool: IpPoolResponse) -> int:
    """Anzahl nutzbarer Host-IPs im Pool (CIDR/Range, ohne Gateway)."""
    net = ipaddress.ip_network(pool.cidr, strict=False)
    gw = ipaddress.ip_address(pool.gateway) if pool.gateway else None
    lo = ipaddress.ip_address(pool.range_start) if pool.range_start else None
    hi = ipaddress.ip_address(pool.range_end) if pool.range_end else None
    count = 0
    for host in net.hosts():
        if lo is not None and host < lo:
            continue
        if hi is not None and host > hi:
            continue
        if gw is not None and host == gw:
            continue
        count += 1
    return count


async def pool_usage(pool_id: int) -> Optional[PoolUsageResponse]:
    pool = await core_pools.get_pool(pool_id)
    if pool is None:
        return None
    allocs = await list_allocations(pool_id=pool_id)
    used = sum(1 for a in allocs if a.status in _ACTIVE)
    total = _pool_total_hosts(pool)
    return PoolUsageResponse(
        pool_id=pool_id,
        total=total,
        used=used,
        free=max(0, total - used),
        allocations=allocs,
    )


# ── Pool-Auflösung für die Deploy-Reservierung (CIDR-Match) ──────────────────

async def find_pool_for_ip(
    ip: str, bridge: Optional[str] = None, node: Optional[str] = None
) -> Optional[IpPoolResponse]:
    """Findet den Pool, dessen CIDR/Range die ``ip`` enthält.

    Eingrenzung über Netz (bridge/node) wenn bekannt: bevorzugt exakten Bridge-
    Match, sonst den ersten passenden CIDR-Match. 0 Treffer → None (kein IPAM).
    """
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return None
    if addr.version != 4:
        return None
    pools = await core_pools.list_pools()

    def _contains(p: IpPoolResponse) -> bool:
        try:
            net = ipaddress.ip_network(p.cidr, strict=False)
        except ValueError:
            return False
        if addr not in net:
            return False
        if p.range_start and addr < ipaddress.ip_address(p.range_start):
            return False
        if p.range_end and addr > ipaddress.ip_address(p.range_end):
            return False
        return True

    candidates = [p for p in pools if _contains(p)]
    if not candidates:
        return None
    # bevorzugt exakter Bridge/Node-Match (VNet: node egal)
    if bridge:
        for p in candidates:
            if p.kind == "bridge" and p.network_name == bridge and (
                node is None or p.node == node
            ):
                return p
        for p in candidates:
            if p.kind == "vnet" and p.network_name == bridge:
                return p
    return candidates[0]
