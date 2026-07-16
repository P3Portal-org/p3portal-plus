# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-42 Phase 2: Stacks-IPAM-Integration (Plus→Plus, direkt importiert).

Konsistent mit PROJ-85: die statische IP einer Stack-VM/LXC liegt im
verschlüsselten Cloud-Init-Store (``ip_address_cidr``) und wird beim Deploy in
``initialization.ip_config`` transpiliert. Diese Datei reserviert diese IPs beim
Deploy-Start (``pending``) und bestätigt/gibt sie am Ende frei.

Da ``count>1`` + statische IP im Cloud-Init-Store gesperrt ist (cloud_init.py
``_static_count``), ist der expandierte VM-Name == Ressourcen-Name → die IP↔VMID-
Zuordnung beim confirm läuft über ``stack_deployed_resources.resource_name``, das
beim Reservieren im ``note``-Feld der Allocation abgelegt wird.
"""
from __future__ import annotations

import ipaddress
import logging

from fastapi import HTTPException, status

from . import config_service, service
from .service import IpamReservationConflict

logger = logging.getLogger(__name__)


def _ip_of(cidr: str | None) -> str | None:
    """Extrahiert die IP aus einem ``ip_address_cidr`` (z. B. '192.168.2.50/24')."""
    if not cidr:
        return None
    ip = str(cidr).split("/")[0].strip()
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return None
    return str(addr) if addr.version == 4 else None


async def reserve_stack_ips(
    stack_id: int, deployment_id: int, spec, username: str
) -> int:
    """Reserviert die statischen IPs aller Stack-VMs/LXC als ``pending``.

    Nur bei aktivem IPAM (``global_enabled``). Kollision → HTTPException 409
    (Stack-Deploy scheitert früh). Andere Fehler best-effort (kein Deploy-Block).
    Rückgabe = Anzahl reservierter IPs.
    """
    try:
        if not await config_service.is_global_enabled():
            return 0
        from backend.plus.stacks.cloud_init import (
            _resource_by_name, resolve_for_transpile,
        )
        resolved = await resolve_for_transpile(stack_id, spec, gate=False)
        if not resolved:
            return 0
        by_name = _resource_by_name(spec)
        count = 0
        for vm_name, ci in resolved.items():
            if getattr(ci, "ip_mode", None) != "static":
                continue
            ip = _ip_of(getattr(ci, "ip_address_cidr", None))
            if not ip:
                continue
            res = by_name.get(vm_name)
            bridge = None
            node = None
            if res is not None:
                node = getattr(res, "node", None)
                net = getattr(res, "network", None)
                bridge = getattr(net, "bridge", None) if net is not None else None
            pool = await service.find_pool_for_ip(ip, bridge=bridge, node=node)
            if pool is None:
                continue
            portal_node_id = None
            if node:
                try:
                    from backend.services.nodes_service import get_node_for_proxmox_name
                    node_row = await get_node_for_proxmox_name(node)
                    portal_node_id = node_row.id if node_row else None
                except Exception:
                    portal_node_id = None
            await service.reserve_specific(
                pool.id, ip, owner_username=username, source="stack",
                stack_deployment_id=deployment_id, portal_node_id=portal_node_id,
            )
            # resource_name im note-Feld für die confirm-Zuordnung (IP→VMID)
            await _set_note(deployment_id, ip, vm_name)
            count += 1
        return count
    except IpamReservationConflict as conflict:
        # Teil-Reservierung zurückrollen (die vorher reservierten pending dieses
        # Deploys freigeben), damit keine Leichen bis zum Sweep bleiben.
        await service.release_pending_by_stack(deployment_id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "ipam_reservation_conflict",
                "ip": conflict.ip,
                "pool_id": conflict.pool_id,
            },
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("PROJ-42: Stack-Reservierung (stack %s) fehlgeschlagen: %s", stack_id, exc)
        return 0


async def _set_note(deployment_id: int, ip: str, resource_name: str) -> None:
    from sqlalchemy import text
    from backend.db.database import get_db
    async with get_db() as db:
        await db.execute(
            text(
                "UPDATE ip_allocations SET note = :rn "
                "WHERE stack_deployment_id = :did AND ip = :ip AND status = 'pending'"
            ),
            {"rn": resource_name, "did": deployment_id, "ip": ip},
        )
        await db.commit()


async def confirm_stack_ips(deployment_id: int) -> int:
    """Bestätigt bzw. bereinigt die reservierten IPs nach einem Apply.

    Liest die echten VMID/Node aus ``stack_deployed_resources`` (per
    ``deployment_id``) selbst (die ``resources``-Liste ist im Runner-finally nicht
    sicher im Scope). Die IP↔VMID-Zuordnung läuft über den beim Reservieren im
    ``note``-Feld abgelegten ``resource_name``. pending-Allocations OHNE zugehörige
    deployte Ressource (nicht deployte VM bei partial/failed) werden freigegeben.
    """
    try:
        from datetime import datetime, timezone
        from sqlalchemy import text
        from backend.db.database import get_db
        async with get_db() as db:
            deployed = (await db.execute(
                text(
                    "SELECT resource_name, portal_node_id, vmid FROM stack_deployed_resources "
                    "WHERE deployment_id = :did"
                ),
                {"did": deployment_id},
            )).mappings().fetchall()
            by_name = {r["resource_name"]: r for r in deployed}
            pend = (await db.execute(
                text(
                    "SELECT id, note FROM ip_allocations "
                    "WHERE stack_deployment_id = :did AND status = 'pending'"
                ),
                {"did": deployment_id},
            )).mappings().fetchall()
            confirmed = 0
            released = 0
            for row in pend:
                r = by_name.get(row["note"])
                if r is None:
                    # keine deployte Ressource → Reservierung freigeben
                    await db.execute(
                        text("DELETE FROM ip_allocations WHERE id = :id"), {"id": row["id"]}
                    )
                    released += 1
                    continue
                now = datetime.now(timezone.utc).isoformat()
                await db.execute(
                    text(
                        "UPDATE ip_allocations SET status = 'confirmed', confirmed_at = :now, "
                        "pending_expires_at = NULL, vmid = :vmid, portal_node_id = :pnid "
                        "WHERE id = :id"
                    ),
                    {"id": row["id"], "now": now, "vmid": r["vmid"],
                     "pnid": r["portal_node_id"]},
                )
                confirmed += 1
            await db.commit()
        logger.debug("PROJ-42: Stack-confirm deployment=%s confirmed=%d released=%d",
                     deployment_id, confirmed, released)
        return confirmed
    except Exception as exc:
        logger.warning("PROJ-42: Stack-confirm (deployment %s) fehlgeschlagen: %s",
                       deployment_id, exc)
        return 0


async def release_stack_ips(deployment_id: int) -> int:
    """Gibt die ``pending``-Reservierungen eines Stack-Deploys frei (Start-Fehler)."""
    try:
        return await service.release_pending_by_stack(deployment_id)
    except Exception as exc:
        logger.warning("PROJ-42: Stack-release (deployment %s) fehlgeschlagen: %s",
                       deployment_id, exc)
        return 0


async def release_stack_on_destroy(stack_id: int, username: str = "system") -> int:
    """Beim Stack-Destroy die IP-Allocations der Stack-VMs aktiv freigeben.

    Muss VOR ``clear_deployed_resources`` laufen (danach ist die VMID/Node-Zuordnung
    weg). Liest ``stack_deployed_resources`` des Stacks und gibt pro (node, vmid) die
    Allocation frei (Muster wie ``on_vm_lxc_deleted``). VMs, die außerhalb erfasst
    wurden, fallen ohnehin über den Vanished-Orphan-Mechanismus auf.
    """
    try:
        from sqlalchemy import text
        from backend.db.database import get_db
        from .cleanup import on_vm_lxc_deleted
        async with get_db() as db:
            rows = (await db.execute(
                text(
                    "SELECT portal_node_id, vmid FROM stack_deployed_resources "
                    "WHERE stack_id = :sid"
                ),
                {"sid": stack_id},
            )).mappings().fetchall()
        total = 0
        for r in rows:
            if r["portal_node_id"] is None or r["vmid"] is None:
                continue
            total += await on_vm_lxc_deleted(r["portal_node_id"], r["vmid"], username)
        return total
    except Exception as exc:
        logger.warning("PROJ-42: Stack-destroy-release (stack %s) fehlgeschlagen: %s",
                       stack_id, exc)
        return 0
