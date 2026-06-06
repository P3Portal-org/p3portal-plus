# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""Permission helper for PROJ-76 Stacks.

Policy (AC-RBAC-2/3):
  - Admin role → sees/edits/deletes all stacks.
  - Otherwise → only the owner (stacks.owner_user_id == user_id).

Stack-Ownership ist eine einfache Spalte (Tech-Design B-3), NICHT die
PROJ-48 vm_owners-Tabelle (ein Stack ist keine VM).
"""
from __future__ import annotations

from typing import Optional


def can_manage_stack(
    user_role: str,
    user_id: Optional[int],
    owner_user_id: Optional[int],
) -> bool:
    """Return True if the user may view/edit/delete this stack."""
    if user_role == "admin":
        return True
    if user_id is None:
        return False
    return owner_user_id is not None and owner_user_id == user_id


async def can_deploy_stack(
    user_role: str,
    user_id: Optional[int],
    owner_user_id: Optional[int],
    target_node_id: int,
) -> bool:
    """Return True if the user may deploy/destroy this stack (AC-2B-RBAC-2).

    Admin OR (Owner AND ``node:stack_deploy`` on the target node, PROJ-47).
    A stack deploys against exactly one Portal-Node (one provider endpoint),
    so a single node-scope check covers all referenced resources.
    """
    if user_role == "admin":
        return True
    if user_id is None:
        return False
    if not (owner_user_id is not None and owner_user_id == user_id):
        return False
    from backend.services.permissions_resolver import resolve_node_action
    return await resolve_node_action(user_id, target_node_id, "node:stack_deploy")
