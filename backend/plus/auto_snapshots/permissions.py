# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-77 – Permission-Resolver (Admin OR Owner aller Targets).

Operator-auf-VM (PROJ-12) ist explizit NICHT zugelassen (AC-PERM-4):
Auto-Snapshots sind destruktiv-by-default durch Rotation.
"""
from __future__ import annotations

import logging
from typing import Iterable

logger = logging.getLogger(__name__)

# kind 'qemu' → vm_owners.resource_type 'vm', 'lxc' bleibt 'lxc'
_KIND_TO_RESOURCE_TYPE = {"qemu": "vm", "lxc": "lxc"}


async def is_owner_of(
    user_id: int,
    portal_node_id: int,
    vmid: int,
    kind: str,
) -> bool:
    """Prüft, ob ``user_id`` aktiver Owner einer VM/LXC ist (PROJ-48)."""
    rt = _KIND_TO_RESOURCE_TYPE.get(kind)
    if rt is None:
        return False
    try:
        from backend.features.owners.service import is_owner
        return await is_owner(user_id, rt, portal_node_id, vmid)
    except Exception as exc:  # pragma: no cover
        logger.warning("PROJ-77 is_owner_of: %s", exc)
        return False


async def filter_owned_targets(
    user_id: int,
    targets: Iterable[tuple[int, int, str]],
) -> tuple[list[tuple[int, int, str]], list[tuple[int, int, str]]]:
    """Trennt Targets in (owned, not_owned).

    ``targets``: Iterable von ``(portal_node_id, vmid, kind)``.
    """
    owned: list[tuple[int, int, str]] = []
    not_owned: list[tuple[int, int, str]] = []
    for nid, vmid, kind in targets:
        if await is_owner_of(user_id, nid, vmid, kind):
            owned.append((nid, vmid, kind))
        else:
            not_owned.append((nid, vmid, kind))
    return owned, not_owned


async def require_admin_or_all_targets_owned(
    user_id: int | None,
    user_role: str,
    targets: list[tuple[int, int, str]],
) -> bool:
    """Job-Anlage/-Edit-Gate (AC-PERM-1).

    True wenn Admin ODER (user_role 'user' + Owner aller Targets).
    Operator/viewer/restricted: immer False.
    """
    if user_role == "admin":
        return True
    if user_role != "user":
        return False
    if user_id is None or not targets:
        return False
    owned, not_owned = await filter_owned_targets(user_id, targets)
    return len(not_owned) == 0
