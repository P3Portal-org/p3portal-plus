// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-92: Orchestrator des SoT-Formulars (AC-EDIT). Hält das strukturierte
// Modell, schaltet Formular/JSON-Tab, ruft Validate/Save/Preview. Das Modell ist
// die Eingabe-Wahrheit; die generierte .pkr.json ist eine Projektion (/preview).
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { formatApiError } from '../../api/errors'
import { useQueryClient } from '@tanstack/react-query'
import {
  newModel, emptyCloneSource, emptyIsoSource, emptyInstaller, buildPayload, defaultBootCommand, OS_PRESETS,
} from './model'
import { createDefinition, updateDefinition, validateDefinition, previewDefinition } from './api'
import MetaSection from './MetaSection'
import SourceSection from './SourceSection'
import InstallerBuilder from './InstallerBuilder'
import ProvisionerList from './ProvisionerList'
import SideFilesPanel from './SideFilesPanel'
import JsonProjection from './JsonProjection'
import ConfirmModal from '../../components/common/ConfirmModal'

const BASE_KEYS = [
  'cores', 'memory_mb', 'disk_size_gb', 'network_bridge', 'network_model',
  'network_firewall', 'scsi_controller', 'qemu_agent', 'cloud_init',
  'template_description', 'ssh_username', 'ssh_timeout', 'ssh_private_key_name',
]

function pickBase(source) {
  const out = {}
  for (const k of BASE_KEYS) out[k] = source?.[k]
  return out
}

/** Map a 409-detail string to a friendly i18n key. */
function conflictMessage(detail, t) {
  if (detail === 'definition_exists') return t('packer_editor.err_exists')
  if (detail === 'foreign_definition_exists' || detail === 'foreign_definition') return t('packer_editor.err_foreign')
  return null
}

export default function PackerEditorForm({ initialModel, isEdit, onClose, onSaved }) {
  const { t } = useTranslation()
  const qc = useQueryClient()

  const [model, setModel] = useState(() => initialModel || newModel())
  const [mode, setMode] = useState('form')        // 'form' | 'json'
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState(null)
  const [validation, setValidation] = useState(null) // ValidationResult or {errors}
  const [validating, setValidating] = useState(false)
  const [confirmPreset, setConfirmPreset] = useState(null) // pending OS-Preset (P3 ConfirmModal)

  const isIso = model.source?.type === 'proxmox-iso'

  // ── Model patch helpers ─────────────────────────────────────────────────────
  const patchModel = (partial) => setModel((m) => ({ ...m, ...partial }))
  const patchSource = (partial) => setModel((m) => ({ ...m, source: { ...m.source, ...partial } }))
  const patchInstaller = (partial) => setModel((m) => ({ ...m, installer: { ...(m.installer || emptyInstaller()), ...partial } }))

  const handleTypeChange = (newType) => {
    setModel((m) => {
      if (m.source?.type === newType) return m
      const base = pickBase(m.source)
      if (newType === 'proxmox-iso') {
        const tmpl = emptyIsoSource()
        const profile = m.installer?.os_profile || 'debian-preseed'
        return {
          ...m,
          source: {
            type: 'proxmox-iso',
            ...tmpl,
            ...base,
            boot_command: m.source?.boot_command || defaultBootCommand(profile),
            boot_wait: m.source?.boot_wait || '5s',
            http_port: m.source?.http_port || 8103,
          },
          installer: m.installer || emptyInstaller(),
        }
      }
      const tmpl = emptyCloneSource()
      return {
        ...m,
        source: {
          type: 'proxmox-clone',
          ...tmpl,
          ...base,
          clone_template: m.source?.clone_template || '',
          full_clone: m.source?.full_clone ?? true,
        },
        // installer bleibt im State erhalten; buildPayload strippt es bei clone.
      }
    })
  }

  // ── Preview (shared by InstallerBuilder + JsonProjection) ───────────────────
  // Die Vorschau soll auch bei einer noch unbenannten neuen Definition die HCL
  // zeigen: id/name sind nur Metadaten (Verzeichnisname) und für die generierte
  // HCL nicht inhaltsrelevant. Daher Platzhalter NUR für die Vorschau einsetzen,
  // wenn die Felder noch leer sind — „Validieren"/„Speichern" erzwingen die
  // echten Pflichtwerte unverändert.
  const previewFn = useMemo(
    () => () => {
      const payload = buildPayload(model)
      if (!payload.id) payload.id = 'preview'
      if (!payload.name) payload.name = 'Preview'
      return previewDefinition(payload)
    },
    [model],
  )

  // ── Prefill (OS-Vorlage) ────────────────────────────────────────────────────
  const doApplyPreset = (preset) => {
    setModel(preset.build())
    setMode('form')
    setValidation(null)
    setSaveError(null)
  }

  const applyPreset = (preset) => {
    // Schutz vor versehentlichem Überschreiben begonnener Eingaben — P3-ConfirmModal
    // statt nativem window.confirm (themed, konsistent mit dem Portal-Design).
    if (model.name) {
      setConfirmPreset(preset)
      return
    }
    doApplyPreset(preset)
  }

  // ── Actions ─────────────────────────────────────────────────────────────────
  const handleValidate = async () => {
    setValidating(true)
    setValidation(null)
    try {
      const res = await validateDefinition(buildPayload(model))
      setValidation({ ok: true, warnings: res.warnings || [], errors: [] })
    } catch (err) {
      setValidation({ ok: false, warnings: [], errors: [formatApiError(err, t('common.error_generic'))] })
    } finally {
      setValidating(false)
    }
  }

  const handleSave = async () => {
    setSaving(true)
    setSaveError(null)
    try {
      const payload = buildPayload(model)
      if (isEdit) {
        await updateDefinition(model.id, payload)
      } else {
        await createDefinition(payload)
      }
      qc.invalidateQueries({ queryKey: ['packer-editor-definitions'] })
      // Auch die VM-Images-Liste (PROJ-6, usePackerTemplates) auffrischen, da die
      // Definition dort als baubar erscheint (AC-HOST-3).
      qc.invalidateQueries({ queryKey: ['packer', 'templates'] })
      onSaved?.()
    } catch (err) {
      const status = err?.response?.status
      const detail = err?.response?.data?.detail
      const conflict = status === 409 ? conflictMessage(detail, t) : null
      setSaveError(conflict || formatApiError(err, t('common.error_generic')))
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
          {isEdit ? t('packer_editor.title_edit') : t('packer_editor.title_new')}
        </h3>
        <div className="w-16" />
      </div>

      {/* Kurz-Einführung (nur beim Erstellen) — holt Unerfahrene ab, verweist auf die (i)-Hilfe. */}
      {!isEdit && (
        <p className="text-xs text-portal-text2 leading-snug rounded-md border border-portal-info/30 bg-portal-info/5 px-3 py-2">
          {t('packer_editor.editor_intro')}
        </p>
      )}

      {/* Prefill: OS-Vorlagen (nur beim Erstellen) */}
      {!isEdit && (
        <div className="flex flex-wrap items-center gap-2 rounded-md border border-portal-border bg-portal-bg2/40 px-3 py-2">
          <span className="text-xs text-portal-text2 font-medium">{t('packer_editor.prefill_label')}</span>
          {OS_PRESETS.map((p) => (
            <button key={p.key} type="button" className="btn-table" onClick={() => applyPreset(p)}>{p.label}</button>
          ))}
        </div>
      )}

      {/* Tab toggle */}
      <div className="flex border-b border-portal-border">
        <button type="button" className={tabCls('form')} onClick={() => setMode('form')}>{t('packer_editor.tab_form')}</button>
        <button type="button" className={tabCls('json')} onClick={() => setMode('json')}>{t('packer_editor.tab_hcl')}</button>
      </div>

      {mode === 'json' ? (
        <div className="rounded-lg border border-portal-border bg-portal-bg2/40">
          <JsonProjection previewFn={previewFn} model={model} onChange={patchModel} />
        </div>
      ) : (
        <div className="space-y-4">
          {model.hcl_override && (
            <div className="rounded-md border border-portal-warn/40 bg-portal-warn/10 p-2 text-[11px] text-portal-warn">
              {t('packer_editor.hcl_form_banner')}
            </div>
          )}
          <MetaSection model={model} isEdit={isEdit} onChange={patchModel} />
          <SourceSection
            source={model.source}
            osProfile={model.installer?.os_profile || 'debian-preseed'}
            onChange={patchSource}
            onTypeChange={handleTypeChange}
          />
          {isIso && (
            <InstallerBuilder
              installer={model.installer || emptyInstaller()}
              onChange={patchInstaller}
              previewFn={previewFn}
            />
          )}
          <ProvisionerList provisioners={model.provisioners} onChange={(v) => patchModel({ provisioners: v })} />
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
            {validation.ok && validation.errors.length === 0 ? t('packer_editor.validation_ok') : t('packer_editor.validation_errors')}
          </p>
          {validation.errors?.map((e, i) => <p key={`e${i}`} className="text-portal-danger">• {e}</p>)}
          {validation.warnings?.map((w, i) => <p key={`w${i}`} className="text-portal-warn">⚠ {w}</p>)}
        </div>
      )}

      {saveError && <p className="text-sm text-portal-danger">{saveError}</p>}

      {/* Actions */}
      <div className="flex flex-wrap items-center gap-2 pt-2 border-t border-portal-border">
        <button type="button" onClick={handleValidate} disabled={validating} className="btn-secondary">
          {validating ? t('common.loading') : t('packer_editor.validate_btn')}
        </button>
        <div className="flex-1" />
        <button type="button" onClick={onClose} className="btn-secondary">{t('common.cancel')}</button>
        <button type="button" onClick={handleSave} disabled={saving} className="btn-primary">
          {saving ? t('common.loading') : t('packer_editor.save_btn')}
        </button>
      </div>

      {confirmPreset && (
        <ConfirmModal
          title={t('packer_editor.prefill_confirm_title')}
          body={t('packer_editor.prefill_confirm')}
          confirmLabel={t('common.confirm')}
          cancelLabel={t('common.cancel')}
          onConfirm={() => doApplyPreset(confirmPreset)}
          onClose={() => setConfirmPreset(null)}
        />
      )}
    </div>
  )
}
