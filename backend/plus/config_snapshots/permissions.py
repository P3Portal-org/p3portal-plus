# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""Permission resolver for PROJ-74 Config-Snapshots.

Policy (AC-PERM-1a):
  Allowed = Admin role  OR  active Owner of the VM/LXC (PROJ-48)
  Operator on VM (PROJ-12 resource_assignments) is explicitly NOT included.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import text

from backend.db.database import get_db


# kind 'qemu' maps to resource_type 'vm' in vm_owners
_KIND_TO_RESOURCE_TYPE = {"qemu": "vm", "lxc": "lxc"}


async def can_user_manage_config_snapshot(
    user_id: Optional[int],
    user_role: str,
    portal_node_id: Optional[int],
    vmid: int,
    kind: str,
) -> bool:
    """Return True if the user may create/restore/delete this VM's snapshots.

    Admin role → always True.
    Otherwise look for an active ownership record in vm_owners.

    ``portal_node_id`` may be None (orphan snapshot). In that case only
    admins are permitted (no node to look up owners for).
    """
    if user_role == "admin":
        return True

    if user_id is None:
        return False

    if portal_node_id is None:
        return False

    resource_type = _KIND_TO_RESOURCE_TYPE.get(kind)
    if resource_type is None:
        return False

    async with get_db() as session:
        row = await session.execute(
            text(
                "SELECT id FROM vm_owners "
                "WHERE user_id = :uid "
                "  AND resource_type = :rt "
                "  AND node_id = :nid "
                "  AND vmid = :vmid "
                "  AND deleted_at IS NULL "
                "LIMIT 1"
            ),
            {
                "uid": user_id,
                "rt": resource_type,
                "nid": portal_node_id,
                "vmid": vmid,
            },
        )
        return row.first() is not None


async def can_user_manage_orphan_snapshots(user_role: str) -> bool:
    """Only admins (or users with manage_config_snapshots_orphans) may list/delete orphans."""
    return user_role == "admin"
