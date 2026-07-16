# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-101: FastAPI-Router für die Template-Replikation.

Prefix /api/template-replication.
Plus-Gate: 404 für Core-/unlizenzierte Instanzen (AC-EDITION-1).
RBAC: Admin ODER Träger der delegierbaren Plus-Permission ``replicate_templates`` (AC-RBAC-1).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.core.deps import CurrentUser, require_admin_or
from backend.core.plus_protocol import plus_behavior
from backend.models.jobs import JobResponse

from . import service
from .schemas import PreflightResponse, ReplicateRequest

router = APIRouter(prefix="/api/template-replication", tags=["template-replication"])

_require_replicate = require_admin_or("replicate_templates")


def _check_plus() -> None:
    if not plus_behavior.can_use_template_replication():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")


@router.get("/preflight", response_model=PreflightResponse)
async def preflight(
    source_node: str = Query(..., min_length=1),
    source_vmid: int = Query(..., ge=100),
    current_user: CurrentUser = Depends(_require_replicate),
) -> PreflightResponse:
    """Quell-Storage-Status (shared?) + verfügbare Ziel-Nodes samt Datastores."""
    _check_plus()
    return await service.preflight(source_node, source_vmid)


@router.post("/replicate", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
async def replicate(
    body: ReplicateRequest,
    current_user: CurrentUser = Depends(_require_replicate),
) -> JobResponse:
    """Startet die Replikation als Job (Live-Log über den bestehenden WS-Viewer)."""
    _check_plus()
    return await service.start_replication(current_user, body)
