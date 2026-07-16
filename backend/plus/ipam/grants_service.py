# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-42 Phase 2: Netzwerk-Freigaben + Sichtbarkeits-Filter.

Ein Netz (Bridge/VNet) wird an User und/oder Gruppen (PROJ-45) freigegeben.
Eine Zugriffs-Ebene, zwei Wirkungen (Pools sind netz-gebunden): das Netz-Dropdown
zeigt nur freigegebene Netze **und** die IPAM-Pool-Sicht erbt automatisch.

Backend-enforced: der Filter läuft serverseitig am zentralen ``get_node_vm_options``
(alle Konsumenten: Playbook + Stacks) – ein Nicht-Admin kann kein fremdes Netz
erzwingen. Wirkt nur bei ``strict_network_visibility`` + ``global_enabled``;
**Admin sieht immer alles**. Netz-Filter arbeitet auf Namen-Ebene
(kind, network_name, node) – die VLAN-Granularität greift auf Pool-Ebene.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text

from backend.db.database import get_db

from . import config_service
from .schemas import NetworkGrantRequest, NetworkGrantResponse


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _node_db(node: Optional[str]) -> str:
    return node or ""


def _vlan_db(vlan: Optional[int]) -> int:
    return int(vlan) if vlan else 0


def _is_admin(user) -> bool:
    return getattr(user, "role", None) == "admin" or getattr(user, "auth_type", None) == "proxmox"


# ── CRUD ──────────────────────────────────────────────────────────────────────

async def create_grant(body: NetworkGrantRequest, created_by: str) -> NetworkGrantResponse:
    node = None if body.kind == "vnet" else body.node
    payload = {
        "kind": body.kind,
        "network_name": body.network_name,
        "node": _node_db(node),
        "vlan_tag": _vlan_db(body.vlan_tag),
        "grantee_kind": body.grantee_kind,
        "grantee_id": body.grantee_id,
        "created_by": created_by,
        "created_at": _now(),
    }
    async with get_db() as db:
        # idempotent: existierende Freigabe nicht doppeln (Unique-Constraint)
        await db.execute(
            text(
                "INSERT INTO network_grants "
                "(kind, network_name, node, vlan_tag, grantee_kind, grantee_id, created_by, created_at) "
                "VALUES (:kind, :network_name, :node, :vlan_tag, :grantee_kind, :grantee_id, "
                " :created_by, :created_at) ON CONFLICT DO NOTHING"
            ),
            payload,
        )
        await db.commit()
        row = (await db.execute(
            text(
                "SELECT * FROM network_grants WHERE kind=:kind AND network_name=:network_name "
                "AND node=:node AND vlan_tag=:vlan_tag AND grantee_kind=:grantee_kind "
                "AND grantee_id=:grantee_id"
            ),
            payload,
        )).mappings().fetchone()
    return await _to_response(row)


async def list_grants() -> list[NetworkGrantResponse]:
    async with get_db() as db:
        rows = (await db.execute(
            text("SELECT * FROM network_grants ORDER BY kind, network_name, node")
        )).mappings().fetchall()
    return [await _to_response(r) for r in rows]


async def delete_grant(grant_id: int) -> bool:
    async with get_db() as db:
        result = await db.execute(
            text("DELETE FROM network_grants WHERE id = :id"), {"id": grant_id}
        )
        await db.commit()
    return result.rowcount > 0


async def _to_response(row) -> NetworkGrantResponse:
    name = await _resolve_grantee_name(row["grantee_kind"], row["grantee_id"])
    return NetworkGrantResponse(
        id=row["id"],
        kind=row["kind"],
        network_name=row["network_name"],
        node=(row["node"] or None),
        vlan_tag=(row["vlan_tag"] or None),
        grantee_kind=row["grantee_kind"],
        grantee_id=row["grantee_id"],
        grantee_name=name,
        created_by=row["created_by"],
        created_at=row["created_at"],
    )


async def _resolve_grantee_name(kind: str, gid: int) -> Optional[str]:
    table, col = ("local_users", "username") if kind == "user" else ("groups", "name")
    try:
        async with get_db() as db:
            row = (await db.execute(
                text(f"SELECT {col} AS n FROM {table} WHERE id = :id"), {"id": gid}
            )).mappings().fetchone()
        return row["n"] if row else None
    except Exception:
        return None


# ── Sichtbarkeit ──────────────────────────────────────────────────────────────

async def _user_group_ids(user_id: Optional[int]) -> list[int]:
    if user_id is None:
        return []
    async with get_db() as db:
        rows = (await db.execute(
            text("SELECT group_id FROM group_members WHERE user_id = :uid"),
            {"uid": user_id},
        )).fetchall()
    return [r[0] for r in rows]


async def visible_network_keys(user) -> set[tuple[str, str, str]]:
    """Menge freigegebener Netze für den User (Namen-Ebene: kind, network_name, node).

    Vereinigung aus direkten User-Grants + Grants aller Gruppen des Users.
    """
    user_id = getattr(user, "user_id", None)
    group_ids = await _user_group_ids(user_id)
    clauses = []
    params: dict = {}
    if user_id is not None:
        clauses.append("(grantee_kind = 'user' AND grantee_id = :uid)")
        params["uid"] = user_id
    if group_ids:
        gph = ",".join(f":g{i}" for i in range(len(group_ids)))
        clauses.append(f"(grantee_kind = 'group' AND grantee_id IN ({gph}))")
        params.update({f"g{i}": v for i, v in enumerate(group_ids)})
    if not clauses:
        return set()
    async with get_db() as db:
        rows = (await db.execute(
            text(
                "SELECT DISTINCT kind, network_name, node FROM network_grants "
                f"WHERE {' OR '.join(clauses)}"
            ),
            params,
        )).mappings().fetchall()
    return {(r["kind"], r["network_name"], r["node"] or "") for r in rows}


async def filter_networks(user, bridges: list, vnets: list, node: str) -> tuple:
    """Filtert (bridges, vnets) auf die für den User freigegebenen Netze.

    Kein Filter bei ausgeschaltetem strict/global oder für Admins (sieht alles).
    """
    if _is_admin(user):
        return bridges, vnets
    if not await config_service.is_strict_visibility():
        return bridges, vnets
    keys = await visible_network_keys(user)
    node_db = node or ""
    vis_bridges = [b for b in bridges if ("bridge", b, node_db) in keys]
    # VNets sind cluster-weit (node='' im Grant)
    vis_vnets = [v for v in vnets if ("vnet", v, "") in keys]
    return vis_bridges, vis_vnets


async def filter_pools(user, pools: list) -> list:
    """Filtert eine Pool-Liste auf Pools freigegebener Netze (IPAM-Sicht erbt)."""
    if _is_admin(user):
        return pools
    if not await config_service.is_strict_visibility():
        return pools
    keys = await visible_network_keys(user)
    result = []
    for p in pools:
        node_db = (p.node or "") if p.kind == "bridge" else ""
        if (p.kind, p.network_name, node_db) in keys:
            result.append(p)
    return result
