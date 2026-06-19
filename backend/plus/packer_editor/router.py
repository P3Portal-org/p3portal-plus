# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-92: FastAPI router for the Packer Visual Editor.

Prefix /api/packer-editor. Plus-gate: 404 in Core / unlicensed Plus
(AC-RBAC-2). Every endpoint is admin-only (AC-RBAC-3, analogous to the existing
admin-only Packer ZIP upload). The editor reads/writes only editor-managed
definitions (Sidecar marker); foreign ZIP/Git definitions are never touched.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, status
from backend.features.api_surface.deps import require_scope_for_upk  # PROJ-97

from backend.core.deps import CurrentUser, require_admin
from backend.core.plus_protocol import plus_behavior

from . import service
from .schemas import (
    DefinitionSummary,
    PackerEditorModel,
    PreviewResult,
    ValidationResult,
)
from .service import DefinitionExists, DefinitionNotFound, ForeignDefinition
from .validation import semantic_warnings

router = APIRouter(prefix="/api/packer-editor", tags=["packer-editor"])

# PROJ-97: upk_-Scope-Gates (No-Op für JWT). Edition-Gate (_check_plus → 404) bleibt orthogonal.
_SCOPE_READ = Depends(require_scope_for_upk("packer_editor:read"))
_SCOPE_WRITE = Depends(require_scope_for_upk("packer_editor:write"))


def _check_plus() -> None:
    if not plus_behavior.can_use_packer_editor():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")


@router.get("/definitions", response_model=list[DefinitionSummary], dependencies=[_SCOPE_READ])
async def list_definitions(
    current_user: CurrentUser = Depends(require_admin),
) -> list[DefinitionSummary]:
    _check_plus()
    return service.list_definitions()


@router.get("/definitions/{definition_id}", response_model=PackerEditorModel, dependencies=[_SCOPE_READ])
async def get_definition(
    definition_id: str,
    current_user: CurrentUser = Depends(require_admin),
) -> PackerEditorModel:
    _check_plus()
    model = service.get_definition(definition_id)
    if model is None:
        raise HTTPException(status_code=404, detail="definition_not_found")
    return model


@router.post("/definitions", response_model=DefinitionSummary, status_code=201, dependencies=[_SCOPE_WRITE])
async def create_definition(
    model: PackerEditorModel = Body(...),
    current_user: CurrentUser = Depends(require_admin),
) -> DefinitionSummary:
    _check_plus()
    try:
        saved = service.save_definition(model, is_update=False)
    except DefinitionExists:
        raise HTTPException(status_code=409, detail="definition_exists")
    except ForeignDefinition:
        raise HTTPException(status_code=409, detail="foreign_definition_exists")
    return DefinitionSummary(
        id=saved.id, name=saved.name, description=saved.description,
        required_role=saved.required_role, source_type=saved.source.type,
    )


@router.put("/definitions/{definition_id}", response_model=DefinitionSummary, dependencies=[_SCOPE_WRITE])
async def update_definition(
    definition_id: str,
    model: PackerEditorModel = Body(...),
    current_user: CurrentUser = Depends(require_admin),
) -> DefinitionSummary:
    _check_plus()
    if model.id != definition_id:
        raise HTTPException(status_code=400, detail="id_mismatch")
    try:
        saved = service.save_definition(model, is_update=True)
    except DefinitionNotFound:
        raise HTTPException(status_code=404, detail="definition_not_found")
    return DefinitionSummary(
        id=saved.id, name=saved.name, description=saved.description,
        required_role=saved.required_role, source_type=saved.source.type,
    )


@router.delete("/definitions/{definition_id}", status_code=204, dependencies=[_SCOPE_WRITE])
async def delete_definition(
    definition_id: str,
    current_user: CurrentUser = Depends(require_admin),
) -> None:
    _check_plus()
    try:
        deleted = service.delete_definition(definition_id)
    except ForeignDefinition:
        raise HTTPException(status_code=409, detail="foreign_definition")
    if not deleted:
        raise HTTPException(status_code=404, detail="definition_not_found")


@router.post("/validate", response_model=ValidationResult, dependencies=[_SCOPE_WRITE])
async def validate_definition(
    model: PackerEditorModel = Body(...),
    current_user: CurrentUser = Depends(require_admin),
) -> ValidationResult:
    _check_plus()
    # Pydantic already enforced hard validation (422); only semantic warnings here.
    return ValidationResult(ok=True, warnings=semantic_warnings(model))


@router.post("/preview", response_model=PreviewResult, dependencies=[_SCOPE_WRITE])
async def preview_definition(
    model: PackerEditorModel = Body(...),
    current_user: CurrentUser = Depends(require_admin),
) -> PreviewResult:
    _check_plus()
    warnings = semantic_warnings(model)
    hcl_text, files, meta_yaml = service.build_preview(model)
    return PreviewResult(hcl=hcl_text, files=files, meta_yaml=meta_yaml, warnings=warnings)
