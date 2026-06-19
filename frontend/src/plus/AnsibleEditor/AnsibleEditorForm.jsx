// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-93: Orchestrator des SoT-Formulars (AC-EDIT). Hält das strukturierte
// Modell, schaltet Formular/YAML-Tab, ruft Validate/Save/Preview. Das Modell ist
// die Eingabe-Wahrheit; das generierte <id>.yml ist eine read-only Projektion.
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import { formatApiError } from '../../api/errors'
import { newModel, buildPayload } from './model'
import { createDefinition, updateDefinition, validateDefinition, previewDefinition } from './api'
import MetaSection from './MetaSection'
import AnsibleEditorCanvas from './AnsibleEditorCanvas'
import SideFilesPanel from './SideFilesPanel'
import YamlProjection from './YamlProjection'

/** Map a 409-detail string to a friendly i18n key. */
function conflictMessage(detail, t) {
  if (detail === 'definition_exists') return t('ansible_editor.err_exists')
  if (detail === 'foreign_definition_exists' || detail === 'foreign_definition') return t('ansible_editor.err_foreign')
  return null
}

export default function AnsibleEditorForm({ initialModel, isEdit, onClose, onSaved }) {
  const { t } = useTranslation()
  const qc = useQueryClient()

  const [model, setModel] = useState(() => initialModel || newModel())
  const [mode, setMode] = useState('form')        // 'form' | 'yaml'
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState(null)
  const [validation, setValidation] = useState(null) // { ok, errors[], warnings[] }
  const [validating, setValidating] = useState(false)

  const patchModel = (partial) => setModel((m) => ({ ...m, ...partial }))

  // Vorschau: id/name sind nur Metadaten; für die generierte YAML nicht
  // inhaltsrelevant → Platzhalter NUR für die Vorschau, falls noch leer.
  const previewFn = useMemo(
    () => () => {
      const payload = buildPayload(model)
      if (!payload.id) payload.id = 'preview'
      if (!payload.name) payload.name = 'Preview'
      return previewDefinition(payload)
    },
    [model],
  )

  const handleValidate = async () => {
    setValidating(true)
    setValidation(null)
    try {
      const res = await validateDefinition(buildPayload(model))
      setValidation({ ok: !!res.ok, errors: res.errors || [], warnings: res.warnings || [] })
    } catch (err) {
      setValidation({ ok: false, errors: [formatApiError(err, t('common.error_generic'))], warnings: [] })
    } finally {
      setValidating(false)
    }
  }

  const handleSave = async () => {
    setSaving(true)
    setSaveError(null)
    try {
      const payload = buildPayload(model)
      if (isEdit) await updateDefinition(model.id, payload)
      else await createDefinition(payload)
      qc.invalidateQueries({ queryKey: ['ansible-editor-definitions'] })
      // Die Playbook-Liste auffrischen — die Definition erscheint dort als
      // startbares Playbook (AC-HOST-3).
      qc.invalidateQueries({ queryKey: ['playbooks'] })
      onSaved?.()
    } catch (err) {
      const status = err?.response?.status
      const detail = err?.response?.data?.detail
      if (status === 400 && detail?.error === 'validation_failed') {
        setValidation({ ok: false, errors: detail.errors || [], warnings: [] })
        setSaveError(t('ansible_editor.save_validation_failed'))
      } else if (status === 409) {
        setSaveError(conflictMessage(detail, t) || formatApiError(err, t('common.error_generic')))
      } else {
        setSaveError(formatApiError(err, t('common.error_generic')))
      }
    } finally {
      setSaving(false)
    }
  }

  const tabCls = (m) =>
    `px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
      mode === m ? 'border-portal-accent text-portal-text' : 'border-transparent text-portal-text2 hover:text-portal-text'
    }`

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2">
        <button type="button" className="btn-table" onClick={onClose}>← {t('common.back')}</button>
        <h3 className="text-sm font-semibold text-portal-text">
          {isEdit ? t('ansible_editor.title_edit') : t('ansible_editor.title_new')}
        </h3>
        <div className="w-16" />
      </div>

      {!isEdit && (
        <p className="text-xs text-portal-text2 leading-snug rounded-md border border-portal-info/30 bg-portal-info/5 px-3 py-2">
          {t('ansible_editor.editor_intro')}
        </p>
      )}

      {/* Tab toggle */}
      <div className="flex border-b border-portal-border">
        <button type="button" className={tabCls('form')} onClick={() => setMode('form')}>{t('ansible_editor.tab_form')}</button>
        <button type="button" className={tabCls('yaml')} onClick={() => setMode('yaml')}>{t('ansible_editor.tab_yaml')}</button>
      </div>

      {mode === 'yaml' ? (
        <div className="rounded-lg border border-portal-border bg-portal-bg2/40">
          <YamlProjection previewFn={previewFn} />
        </div>
      ) : (
        <div className="space-y-4">
          <MetaSection model={model} isEdit={isEdit} onChange={patchModel} />
          <AnsibleEditorCanvas model={model} onModelChange={setModel} />
          <SideFilesPanel sideFiles={model.side_files} onChange={(v) => patchModel({ side_files: v })} />
        </div>
      )}

      {/* Validation result */}
      {validation && (
        <div className={`rounded-md border p-3 text-xs space-y-1 ${
          validation.ok && validation.errors.length === 0
            ? 'border-portal-success/40 bg-portal-success/10'
            : 'border-portal-danger/40 bg-portal-danger/10'
        }`}>
          <p className={`font-semibold ${validation.ok && validation.errors.length === 0 ? 'text-portal-success' : 'text-portal-danger'}`}>
            {validation.ok && validation.errors.length === 0 ? t('ansible_editor.validation_ok') : t('ansible_editor.validation_errors')}
          </p>
          {validation.errors?.map((e, i) => <p key={`e${i}`} className="text-portal-danger">• {e}</p>)}
          {validation.warnings?.map((w, i) => <p key={`w${i}`} className="text-portal-warn">⚠ {w}</p>)}
        </div>
      )}

      {saveError && <p className="text-sm text-portal-danger">{saveError}</p>}

      {/* Actions */}
      <div className="flex flex-wrap items-center gap-2 pt-2 border-t border-portal-border">
        <button type="button" onClick={handleValidate} disabled={validating} className="btn-secondary">
          {validating ? t('common.loading') : t('ansible_editor.validate_btn')}
        </button>
        <div className="flex-1" />
        <button type="button" onClick={onClose} className="btn-secondary">{t('common.cancel')}</button>
        <button type="button" onClick={handleSave} disabled={saving} className="btn-primary">
          {saving ? t('common.loading') : t('ansible_editor.save_btn')}
        </button>
      </div>
    </div>
  )
}
