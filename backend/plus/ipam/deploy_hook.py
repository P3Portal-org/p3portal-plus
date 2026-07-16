# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-42 Phase 2: Playbook-Deploy-Reservierung (Job-Lebenszyklus-Hooks).

- ``on_playbook_job_started``  – reserviert die im ``ip_config``-Feld gewählte
  statische IP als ``pending`` (race-sicher). Kollision → HTTPException 409
  (Deploy scheitert früh, die IP wird NICHT still umgeschrieben).
- ``on_job_finished``          – Erfolg → confirmed, Fehler → Freigabe.

Die Param-Auflösung nutzt die Playbook-``meta.yaml`` (stabile Param-*Typen*
``ip_config`` / ``proxmox_bridge`` / ``proxmox_node`` / integer ``vm_id``);
die Param-IDs selbst variieren je Playbook.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from fastapi import HTTPException, status

from . import config_service, service
from .service import IpamReservationConflict

logger = logging.getLogger(__name__)

# ip=<ipv4>/<prefix>[,gw=...]  – "ip=dhcp" matcht bewusst nicht.
_IP_RE = re.compile(r"^ip=(\d{1,3}(?:\.\d{1,3}){3})/\d{1,2}(?:,gw=.*)?$")


def _extract_deploy_fields(playbook: str, params: dict) -> tuple[
    Optional[str], Optional[str], Optional[str], Optional[int]
]:
    """(ip, bridge, node, vmid) aus params anhand der Param-Typen der meta.yaml.

    Rückgabe (None, …) wenn kein statisches ip_config-Feld gesetzt ist.
    """
    try:
        from backend.services.playbook_service import get_playbook
        detail = get_playbook(playbook)
    except Exception:
        detail = None
    if detail is None:
        return None, None, None, None

    ip = bridge = node = None
    vmid: Optional[int] = None
    for p in detail.parameters:
        val = params.get(p.id)
        if val is None:
            continue
        if p.type == "ip_config":
            m = _IP_RE.match(str(val).strip())
            if m:
                ip = m.group(1)
        elif p.type == "proxmox_bridge":
            bridge = str(val) or None
        elif p.type == "proxmox_node":
            node = str(val) or None
        elif p.type == "integer" and p.id in ("vm_id", "vmid", "new_vmid"):
            try:
                vmid = int(val)
            except (ValueError, TypeError):
                pass
    return ip, bridge, node, vmid


async def on_playbook_job_started(
    job_id: str, playbook: str, params: dict, username: str
) -> int:
    """Reserviert die gewählte statische IP als ``pending`` beim Deploy-Start.

    Nur aktiv bei ``global_enabled``. Ohne IPAM-Feld / ohne passenden Pool = no-op.
    Kollision → HTTPException 409 (propagiert bis zum Client). Andere Fehler werden
    best-effort verschluckt (ein IPAM-Fehler blockt nie einen Deploy außer bei
    echter IP-Kollision – „es darf nicht kaputt gehen").
    """
    try:
        if not await config_service.is_global_enabled():
            return 0
        ip, bridge, node, vmid = _extract_deploy_fields(playbook, params)
        if not ip:
            return 0
        pool = await service.find_pool_for_ip(ip, bridge=bridge, node=node)
        if pool is None:
            return 0  # IP gehört zu keinem verwalteten Pool → kein IPAM im Spiel
        portal_node_id = None
        if node:
            try:
                from backend.services.nodes_service import get_node_for_proxmox_name
                node_row = await get_node_for_proxmox_name(node)
                portal_node_id = node_row.id if node_row else None
            except Exception:
                portal_node_id = None
        await service.reserve_specific(
            pool.id, ip, owner_username=username, source="proxmox",
            job_id=job_id, vmid=vmid, portal_node_id=portal_node_id,
        )
        return 1
    except IpamReservationConflict as conflict:
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
    except Exception as exc:  # best-effort: IPAM-Fehler blockt keinen Deploy
        logger.warning("PROJ-42: playbook reserve für Job %s fehlgeschlagen: %s", job_id, exc)
        return 0


async def on_job_finished(job_id: str, success: bool) -> int:
    """Erfolg → confirmed, Fehler → Freigabe der ``pending``-Reservierung."""
    try:
        if success:
            return await service.confirm_by_job(job_id)
        return await service.release_pending_by_job(job_id)
    except Exception as exc:
        logger.warning("PROJ-42: job_finished-Hook für Job %s fehlgeschlagen: %s", job_id, exc)
        return 0
