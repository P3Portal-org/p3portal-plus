# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-76: Lifecycle cleanup hooks for Stacks.

Hook 1 – on_user_deleted_stacks:
  Orphan-Mode (Tech-Design H, Edge 12). Stacks of a deleted user are NOT removed;
  owner_user_id=NULL, is_orphan=1, orphaned_at=NOW(). Read-only until an admin
  reassigns or purges. No 409 (unlike PROJ-48 vm_owners).

Hook 2 – on_stack_deleted_cancel_approvals:
  Cancel pending stack_edit / stack_delete approvals for a soft-/hard-deleted stack
  (Tech-Design G). action_target == str(stack_id).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import text

from backend.db.database import get_db
from backend.services.audit_service import write_audit_log


async def on_user_deleted_stacks(user_id: int) -> int:
    """Orphan all active stacks of a deleted user. Returns number orphaned."""
    now = datetime.now(timezone.utc).isoformat()
    async with get_db() as db:
        result = await db.execute(
            text(
                "UPDATE stacks SET is_orphan = true, orphaned_at = :now, updated_at = :now "
                "WHERE owner_user_id = :uid AND deleted_at IS NULL AND is_orphan = false"
            ),
            {"now": now, "uid": user_id},
        )
        count = result.rowcount or 0
        await db.commit()

    if count > 0:
        await write_audit_log(
            "stack_orphaned",
            username="system",
            detail=f"ex_owner_user_id={user_id} count={count}",
        )
    return count


async def on_stack_deleted_cancel_approvals(stack_id: int) -> int:
    """Cancel pending stack_edit/stack_delete approvals for this stack."""
    target = str(stack_id)
    now = datetime.now(timezone.utc).isoformat()
    async with get_db() as db:
        # Table only exists when the approval module is migrated; tolerate absence.
        try:
            result = await db.execute(
                text(
                    "UPDATE pending_approvals "
                    "SET status='cancelled', decided_at=:now, payload_secret_blob=NULL, "
                    "    decided_reason='stack_deleted' "
                    "WHERE action_type IN ('stack_edit', 'stack_delete') "
                    "  AND action_target = :tgt "
                    "  AND status IN ('pending', 'suspended')"
                ),
                {"now": now, "tgt": target},
            )
            count = result.rowcount or 0
            await db.commit()
            return count
        except Exception:
            return 0
