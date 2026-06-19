# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-93: FastAPI router for the Ansible Visual Editor.

Prefix /api/ansible-editor. Plus-gate: 404 in Core / unlicensed Plus
(AC-RBAC-1). Every endpoint is admin-only (AC-RBAC-2, analogous to the existing
admin-only ZIP upload + packer_editor). The editor reads/writes only
editor-managed definitions (Sidecar marker); foreign ZIP/Git definitions are
never touched (§ J).

Unlike PROJ-92, ``hard_validate`` runs against the dynamic schema cache: the
save path (POST/PUT) enforces it (400 with the error list before writing); the
``/validate`` endpoint surfaces errors + warnings (200) for the editor to show.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException, status
from backend.features.api_surface.deps import require_scope_for_upk  # PROJ-97

from backend.core.deps import CurrentUser, require_admin
from backend.core.plus_protocol import plus_behavior

from . import doc_cache, service
from .doc_cache import ModuleNotFound, ModuleSchemaUnavailable
from .schemas import (
    AnsibleEditorModel,
    DefinitionSummary,
    ModuleSchema,
    ModuleSummary,
    PreviewResult,
    ValidationResult,
)
from .service import DefinitionExists, DefinitionNotFound, ForeignDefinition
from .validation import hard_validate, semantic_warnings

router = APIRouter(prefix="/api/ansible-editor", tags=["ansible-editor"])

# PROJ-97: upk_-Scope-Gates (No-Op für JWT). Edition-Gate (_check_plus → 404) bleibt orthogonal.
_SCOPE_READ = Depends(require_scope_for_upk("ansible_editor:read"))
_SCOPE_WRITE = Depends(require_scope_for_upk("ansible_editor:write"))


def _check_plus() -> None:
    if not plus_behavior.can_use_ansible_editor():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")


def _enforce_hard_validate(model: AnsibleEditorModel) -> None:
    errors = hard_validate(model)
    if errors:
        raise HTTPException(
            status_code=400,
            detail={"error": "validation_failed", "errors": errors},
        )


# ── Definitions CRUD ──────────────────────────────────────────────────────────


@router.get("/definitions", response_model=list[DefinitionSummary], dependencies=[_SCOPE_READ])
async def list_definitions(
    current_user: CurrentUser = Depends(require_admin),
) -> list[DefinitionSummary]:
    _check_plus()
    return service.list_definitions()


@router.get("/definitions/{definition_id}", response_model=AnsibleEditorModel, dependencies=[_SCOPE_READ])
async def get_definition(
    definition_id: str,
    current_user: CurrentUser = Depends(require_admin),
) -> AnsibleEditorModel:
    _check_plus()
    model = service.get_definition(definition_id)
    if model is None:
        raise HTTPException(status_code=404, detail="definition_not_found")
    return model


@router.post("/definitions", response_model=DefinitionSummary, status_code=201, dependencies=[_SCOPE_WRITE])
async def create_definition(
    model: AnsibleEditorModel = Body(...),
    current_user: CurrentUser = Depends(require_admin),
) -> DefinitionSummary:
    _check_plus()
    _enforce_hard_validate(model)
    try:
        saved = service.save_definition(model, is_update=False)
    except DefinitionExists:
        raise HTTPException(status_code=409, detail="definition_exists")
    except ForeignDefinition:
        raise HTTPException(status_code=409, detail="foreign_definition_exists")
    return service._summary(saved)


@router.put("/definitions/{definition_id}", response_model=DefinitionSummary, dependencies=[_SCOPE_WRITE])
async def update_definition(
    definition_id: str,
    model: AnsibleEditorModel = Body(...),
    current_user: CurrentUser = Depends(require_admin),
) -> DefinitionSummary:
    _check_plus()
    if model.id != definition_id:
        raise HTTPException(status_code=400, detail="id_mismatch")
    _enforce_hard_validate(model)
    try:
        saved = service.save_definition(model, is_update=True)
    except DefinitionNotFound:
        raise HTTPException(status_code=404, detail="definition_not_found")
    return service._summary(saved)


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


# ── Modules & schema (dynamic ansible-doc cache) ──────────────────────────────


@router.get("/modules", response_model=list[ModuleSummary], dependencies=[_SCOPE_READ])
async def list_modules(
    current_user: CurrentUser = Depends(require_admin),
) -> list[ModuleSummary]:
    _check_plus()
    try:
        return doc_cache.list_modules()
    except ModuleSchemaUnavailable:
        raise HTTPException(status_code=503, detail="module_schema_unavailable")


@router.get("/modules/{name}/schema", response_model=ModuleSchema, dependencies=[_SCOPE_READ])
async def module_schema(
    name: str,
    current_user: CurrentUser = Depends(require_admin),
) -> ModuleSchema:
    _check_plus()
    try:
        return doc_cache.module_schema(name)
    except ModuleNotFound:
        raise HTTPException(status_code=404, detail="module_not_found")
    except ModuleSchemaUnavailable:
        raise HTTPException(status_code=503, detail="module_schema_unavailable")


# ── Validate / preview ────────────────────────────────────────────────────────


@router.post("/validate", response_model=ValidationResult, dependencies=[_SCOPE_WRITE])
async def validate_definition(
    syntax_check: bool = False,
    model: AnsibleEditorModel = Body(...),
    current_user: CurrentUser = Depends(require_admin),
) -> ValidationResult:
    _check_plus()
    errors = hard_validate(model)
    warnings = semantic_warnings(model)
    if syntax_check and not errors:
        warnings.extend(_syntax_check(model))
    return ValidationResult(ok=not errors, errors=errors, warnings=warnings)


@router.post("/preview", response_model=PreviewResult, dependencies=[_SCOPE_WRITE])
async def preview_definition(
    model: AnsibleEditorModel = Body(...),
    current_user: CurrentUser = Depends(require_admin),
) -> PreviewResult:
    _check_plus()
    warnings = semantic_warnings(model)
    yaml_text, files, meta_yaml = service.build_preview(model)
    return PreviewResult(yaml=yaml_text, meta_yaml=meta_yaml, files=files, warnings=warnings)


# ── Optional ansible-playbook --syntax-check (best-effort, § K) ────────────────


def _syntax_check(model: AnsibleEditorModel) -> list[str]:
    """Run ``ansible-playbook --syntax-check`` on the generated playbook in a
    throwaway dir (no inventory/run). Best-effort: any failure/timeout/absence is
    swallowed and reported as a warning. Primarily a /qa anchor (AC-YAML-2)."""
    import subprocess

    yaml_text, _files, _meta = service.build_preview(model)
    out: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        pb = Path(tmp) / f"{model.id}.yml"
        pb.write_text(yaml_text)
        try:
            proc = subprocess.run(  # noqa: S603 (fixed arg-list, no shell)
                ["ansible-playbook", "--syntax-check", str(pb)],
                capture_output=True, text=True, timeout=20,
            )
        except (FileNotFoundError, subprocess.SubprocessError):
            return out  # ansible-playbook unavailable → skip silently
        if proc.returncode != 0:
            msg = (proc.stderr or proc.stdout or "").strip().splitlines()
            tail = " ".join(msg[-3:]) if msg else "unbekannter Fehler"
            out.append(f"ansible-playbook --syntax-check meldete einen Fehler: {tail}")
    return out
