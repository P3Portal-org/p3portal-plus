# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-101: Router-Tests — Plus-Gate 404 (Core) + Durchreichen in Plus."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from backend.plus.template_replication import router as tr_router
from backend.plus.template_replication.schemas import ReplicateRequest, ReplicationTarget

pytestmark = pytest.mark.plus_only


def _user():
    return SimpleNamespace(username="admin", role="admin", user_id=1)


def _gate(value):
    return SimpleNamespace(can_use_template_replication=lambda: value)


def _req():
    return ReplicateRequest(source_node="pve1", source_vmid=100,
                            targets=[ReplicationTarget(node="pve2", storage="local-lvm")])


# ── 404 in Core ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_preflight_404_in_core(monkeypatch):
    monkeypatch.setattr(tr_router, "plus_behavior", _gate(False))
    with pytest.raises(HTTPException) as exc:
        await tr_router.preflight(source_node="pve1", source_vmid=100, current_user=_user())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_replicate_404_in_core(monkeypatch):
    monkeypatch.setattr(tr_router, "plus_behavior", _gate(False))
    with pytest.raises(HTTPException) as exc:
        await tr_router.replicate(body=_req(), current_user=_user())
    assert exc.value.status_code == 404


# ── pass-through in Plus ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_preflight_passthrough_in_plus(monkeypatch):
    monkeypatch.setattr(tr_router, "plus_behavior", _gate(True))
    monkeypatch.setattr(tr_router.service, "preflight", AsyncMock(return_value="PF"))
    res = await tr_router.preflight(source_node="pve1", source_vmid=100, current_user=_user())
    assert res == "PF"


@pytest.mark.asyncio
async def test_replicate_passthrough_in_plus(monkeypatch):
    monkeypatch.setattr(tr_router, "plus_behavior", _gate(True))
    monkeypatch.setattr(tr_router.service, "start_replication", AsyncMock(return_value="JOB"))
    res = await tr_router.replicate(body=_req(), current_user=_user())
    assert res == "JOB"
