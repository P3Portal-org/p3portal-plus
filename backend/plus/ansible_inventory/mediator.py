# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-83 Plus: Mediator-Mixin – Pool-/Global-Scope-Auflösung + Injektions-Pubkeys."""
from __future__ import annotations

import logging

from sqlalchemy import text

from backend.core.plus_protocol import GuestScope
from backend.db.database import get_db

logger = logging.getLogger(__name__)


class AnsibleInventoryPlusBehavior:
    """Plus-Implementierung der PROJ-83-Mediator-Hooks."""

    async def resolve_guest_scope(
        self, scope: str, scope_ref: int | None, user_id: int
    ) -> GuestScope | None:
        from backend.plus.ansible_inventory import keys_plus

        if scope == "pool":
            if scope_ref is None:
                return None
            # Mitgliedschaft prüfen (Member/Manager) über die bestehende Pool-Berechtigung.
            try:
                grants = await self.get_pool_permissions(user_id)  # type: ignore[attr-defined]
                pool_ids = {g.pool_id for g in grants}
            except Exception:
                pool_ids = set()
            if scope_ref not in pool_ids:
                return None
            candidates: list[tuple[int, int, str]] = []
            async with get_db() as db:
                rows = (await db.execute(
                    text("SELECT node_id, vmid, resource_type FROM pool_members WHERE pool_id = :pid"),
                    {"pid": scope_ref},
                )).mappings().fetchall()
            for r in rows:
                kind = "lxc" if r["resource_type"] == "lxc" else "qemu"
                candidates.append((int(r["node_id"]), int(r["vmid"]), kind))
            priv = await keys_plus.get_pool_private_key(scope_ref)
            return GuestScope(
                scope="pool", scope_ref=scope_ref,
                private_key=priv or "", candidate_hosts=candidates,
            )

        if scope == "global":
            candidates = []
            async with get_db() as db:
                rows = (await db.execute(
                    text(
                        "SELECT portal_node_id, vmid, kind FROM ansible_managed_hosts "
                        "WHERE global_opt_in = 1"
                    )
                )).mappings().fetchall()
            for r in rows:
                candidates.append((int(r["portal_node_id"]), int(r["vmid"]), str(r["kind"])))
            priv = await keys_plus.get_global_private_key()
            return GuestScope(
                scope="global", scope_ref=None,
                private_key=priv or "", candidate_hosts=candidates,
            )

        return None

    async def get_injection_public_keys_extra(
        self, pool_id: int | None, global_opt_in: bool
    ) -> list[str]:
        from backend.plus.ansible_inventory import keys_plus

        out: list[str] = []
        if pool_id is not None:
            try:
                pub = await keys_plus.get_pool_public_key(pool_id)
                if pub:
                    out.append(pub)
            except Exception as exc:
                logger.warning("PROJ-83: pool pubkey lookup failed (pool=%s): %s", pool_id, exc)
        if global_opt_in:
            try:
                pub = await keys_plus.get_global_public_key()
                if pub:
                    out.append(pub)
            except Exception as exc:
                logger.warning("PROJ-83: global pubkey lookup failed: %s", exc)
        return out
