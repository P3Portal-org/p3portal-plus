# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-76 Phase 2b: serverside mutations-block guard (vms.py, AC-2B-MUT-6)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from backend.routers import vms

pytestmark = pytest.mark.plus_only


@pytest.mark.asyncio
async def test_block_when_stack_managed():
    node = SimpleNamespace(id=3)
    with patch("backend.services.nodes_service.get_node_for_proxmox_name",
               AsyncMock(return_value=node)), \
         patch("backend.core.plus_protocol.plus_behavior") as pb, \
         patch.object(vms, "write_audit_log", AsyncMock()) as audit:
        pb.get_stack_for_vm = AsyncMock(return_value={"stack_id": 9, "stack_name": "web"})
        with pytest.raises(HTTPException) as ei:
            await vms._assert_not_stack_managed("pve", 101, "alice", "local")
    assert ei.value.status_code == 409
    assert ei.value.detail["error"] == "vm_managed_by_stack"
    assert ei.value.detail["stack_id"] == 9
    audit.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_block_when_not_managed():
    node = SimpleNamespace(id=3)
    with patch("backend.services.nodes_service.get_node_for_proxmox_name",
               AsyncMock(return_value=node)), \
         patch("backend.core.plus_protocol.plus_behavior") as pb:
        pb.get_stack_for_vm = AsyncMock(return_value=None)
        # no raise
        await vms._assert_not_stack_managed("pve", 101, "alice", "local")


@pytest.mark.asyncio
async def test_no_block_when_node_unknown():
    with patch("backend.services.nodes_service.get_node_for_proxmox_name",
               AsyncMock(return_value=None)):
        # node not resolvable → guard is a no-op (no raise)
        await vms._assert_not_stack_managed("ghost", 101, "alice", "local")


@pytest.mark.asyncio
async def test_core_mode_no_op():
    """Core get_stack_for_vm returns None → guard never blocks (AC-2B-CORE-2)."""
    node = SimpleNamespace(id=3)
    from backend.core.plus_protocol import CorePlusBehavior
    core = CorePlusBehavior()
    with patch("backend.services.nodes_service.get_node_for_proxmox_name",
               AsyncMock(return_value=node)), \
         patch("backend.core.plus_protocol.plus_behavior", core):
        await vms._assert_not_stack_managed("pve", 101, "alice", "local")
