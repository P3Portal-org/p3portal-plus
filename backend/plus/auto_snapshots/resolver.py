# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-77 – Target-Resolver (4 Target-Typen, UNION, Dedup).

Übersetzt eine ``TargetSpec`` zur Run-Zeit in eine deduplizierte Liste
``[(portal_node_id, vmid, kind), …]``:

- ``singles``      – direkte (node, vmid, kind)-Auswahl
- ``pool_ids``     – via pool_members (PROJ-46)
- ``portal_node_ids`` – alle VMs/LXCs eines Nodes via cluster_cache (PROJ-33)
- ``tags``         – Proxmox-Tag-Filter (OR-Verknüpfung) via cluster_cache
- ``kind_filter``  – Nachträglicher Filter auf qemu/lxc/both
"""
from __future__ import annotations

import logging
from typing import Iterable

from sqlalchemy import text

from backend.db.database import get_db

from .schemas import TargetSpec

logger = logging.getLogger(__name__)


# ─── Pool-Resolver ───────────────────────────────────────────────────────────


async def _resolve_pool_members(pool_ids: list[int]) -> list[tuple[int, int, str]]:
    """Lädt VM-Mitglieder der angegebenen Pools.

    Kind wird aus ``pool_members.resource_type`` abgeleitet: 'vm' → 'qemu', 'lxc' → 'lxc'.
    """
    if not pool_ids:
        return []
    out: list[tuple[int, int, str]] = []
    async with get_db() as db:
        placeholders = ",".join(f":p{i}" for i in range(len(pool_ids)))
        params = {f"p{i}": pid for i, pid in enumerate(pool_ids)}
        try:
            result = await db.execute(
                text(
                    f"SELECT node_id, vmid, resource_type FROM pool_members "
                    f"WHERE pool_id IN ({placeholders})"
                ),
                params,
            )
            for nid, vmid, rt in result.fetchall():
                kind = "qemu" if rt == "vm" else "lxc"
                out.append((int(nid), int(vmid), kind))
        except Exception as exc:
            logger.warning("PROJ-77 _resolve_pool_members: %s", exc)
    return out


# ─── Cluster-Cache-Helper (für Node- und Tag-Resolver) ──────────────────────


def _get_cached_cluster_resources(portal_node_id: int) -> list[dict] | None:
    """Holt die zuletzt gecachte VM/LXC-Liste eines Portal-Nodes (PROJ-33).

    Liefert ``None`` falls keine Daten gecacht sind (Resolver muss das tolerieren).
    """
    try:
        from backend.services.cluster_cache_service import cluster_cache
    except Exception:  # pragma: no cover
        return None
    try:
        entries = cluster_cache._entries  # type: ignore[attr-defined]
    except AttributeError:
        return None

    cache_entry = entries.get((portal_node_id, "vms")) or entries.get((portal_node_id, "resources"))
    if not cache_entry:
        return None
    payload = getattr(cache_entry, "payload", None)
    if not isinstance(payload, list):
        return None
    return payload


def _normalize_resource_kind(item: dict) -> str | None:
    rtype = item.get("type") or item.get("kind") or ""
    if rtype in ("qemu", "vm"):
        return "qemu"
    if rtype == "lxc":
        return "lxc"
    return None


async def _resolve_node_targets(portal_node_ids: list[int]) -> list[tuple[int, int, str]]:
    if not portal_node_ids:
        return []
    out: list[tuple[int, int, str]] = []
    for nid in portal_node_ids:
        items = _get_cached_cluster_resources(nid) or []
        for item in items:
            kind = _normalize_resource_kind(item)
            vmid = item.get("vmid") or item.get("id")
            if kind is None or vmid is None:
                continue
            try:
                out.append((int(nid), int(vmid), kind))
            except (TypeError, ValueError):
                continue
    return out


async def _resolve_tag_targets(
    tags: list[str],
    portal_node_ids_known: set[int] | None = None,
) -> list[tuple[int, int, str]]:
    """OR-Verknüpfung über alle Tags. Nutzt cluster_cache aller Portal-Nodes.

    Wenn ``portal_node_ids_known`` gesetzt, nur diese Nodes durchsuchen.
    """
    if not tags:
        return []

    tag_set = {t.lower() for t in tags if t}
    out: list[tuple[int, int, str]] = []

    # alle Portal-Nodes aus DB holen, falls kein Filter
    if portal_node_ids_known is None:
        node_ids: list[int] = []
        async with get_db() as db:
            try:
                result = await db.execute(text("SELECT id FROM nodes"))
                node_ids = [int(r[0]) for r in result.fetchall()]
            except Exception:
                node_ids = []
    else:
        node_ids = list(portal_node_ids_known)

    for nid in node_ids:
        items = _get_cached_cluster_resources(nid) or []
        for item in items:
            kind = _normalize_resource_kind(item)
            vmid = item.get("vmid") or item.get("id")
            if kind is None or vmid is None:
                continue
            raw_tags = item.get("tags") or ""
            # Proxmox liefert Tags als ';'-separierten String, manchmal komma-separiert
            split_tags = {
                t.strip().lower()
                for chunk in raw_tags.replace(",", ";").split(";")
                for t in (chunk,)
                if t.strip()
            }
            if split_tags & tag_set:
                try:
                    out.append((int(nid), int(vmid), kind))
                except (TypeError, ValueError):
                    continue
    return out


# ─── Hauptaufruf ─────────────────────────────────────────────────────────────


async def resolve_targets(spec: TargetSpec) -> list[tuple[int, int, str]]:
    """UNION über alle Selektoren, deduplizieren, kind_filter anwenden (AC-TGT-1..7).

    Returns dedupliziertes ``list[(portal_node_id, vmid, kind)]``.
    """
    union: set[tuple[int, int, str]] = set()

    # 1) singles
    for s in spec.singles:
        union.add((s.portal_node_id, s.vmid, s.kind))

    # 2) pools
    for triple in await _resolve_pool_members(spec.pool_ids):
        union.add(triple)

    # 3) nodes (alle VMs/LXCs des Nodes via cluster_cache)
    for triple in await _resolve_node_targets(spec.portal_node_ids):
        union.add(triple)

    # 4) tags – beschränken auf bekannte Node-IDs, falls bereits angegeben,
    #         sonst alle Portal-Nodes durchsuchen
    if spec.tags:
        for triple in await _resolve_tag_targets(spec.tags):
            union.add(triple)

    # kind_filter anwenden
    if spec.kind_filter == "qemu":
        filtered = {t for t in union if t[2] == "qemu"}
    elif spec.kind_filter == "lxc":
        filtered = {t for t in union if t[2] == "lxc"}
    else:
        filtered = union

    # Sortierung determinisitisch (node, vmid)
    return sorted(filtered, key=lambda t: (t[0], t[1], t[2]))
