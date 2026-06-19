# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-76: Plus-Mixin für Stacks.

Stellt can_use_stacks() + Lifecycle-/Approval-Hooks bereit.
"""
from __future__ import annotations


class StacksPlusBehavior:
    """Plus-Mixin: aktiviert das Stacks-Feature (PROJ-76 Phase 1)."""

    def can_use_stacks(self) -> bool:
        return True

    async def on_user_deleted_stacks(self, user_id: int) -> int:
        """Orphan all stacks of a deleted user (Edge 12)."""
        from backend.plus.stacks.cleanup import on_user_deleted_stacks
        return await on_user_deleted_stacks(user_id)

    def get_stack_approval_action_types(self) -> list[str]:
        """Action-Types für die Approval-Discovery/Regel-UI (PROJ-50).

        Phase 2b ergänzt stack_deploy/stack_destroy (AC-2B-APPR-5).
        """
        return ["stack_edit", "stack_delete", "stack_deploy", "stack_destroy"]

    async def on_stack_deleted_cancel_approvals(self, stack_id: int) -> int:
        """Cancel pending stack_edit/stack_delete approvals for a deleted stack."""
        from backend.plus.stacks.cleanup import on_stack_deleted_cancel_approvals
        return await on_stack_deleted_cancel_approvals(stack_id)

    # ── PROJ-76 Phase 2b: Mutations-Block-Lookup ─────────────────────────────

    async def get_stack_for_vm(self, portal_node_id: int, vmid: int) -> dict | None:
        """Return {stack_id, stack_name} if a real VM is stack-managed, else None.

        Drives the serverside mutations-block + the VM-detail badge
        (AC-2B-MUT-1/6, AC-2B-CORE-2). Core returns None (no-op).
        """
        from backend.plus.stacks.deployments import get_stack_for_vm
        return await get_stack_for_vm(portal_node_id, vmid)

    def cancel_stack_job(self, stack_id: int) -> bool:
        """SIGINT a running tofu apply/destroy for a stack (AC-2B-LOCK/Cancel)."""
        from backend.plus.stacks.engine import cancel_tofu
        return cancel_tofu(str(stack_id))

    # ── PROJ-91: stack-firewall mutations-block lookup ───────────────────────

    async def get_stack_firewall_for_vm(self, portal_node_id: int, vmid: int) -> dict | None:
        """Return {stack_id, stack_name} if a VM's firewall is stack-managed (AC-MUT-1).

        Stricter than get_stack_for_vm: only blocks the PROJ-90 firewall mutation
        when the stack resource has an active firewall block. Core returns None.
        """
        from backend.plus.stacks.deployments import get_stack_firewall_for_vm
        return await get_stack_firewall_for_vm(portal_node_id, vmid)
