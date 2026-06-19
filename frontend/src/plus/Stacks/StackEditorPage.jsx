// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-76 Phase 1: Stack-Editor (Neu + Bearbeiten) mit Tab-Toggle YAML/Formular
// und bidirektionalem Live-Sync via js-yaml (AC-UI-2/3/4/5/6/7/12).
import { useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import jsyaml from 'js-yaml'
import { useCapability } from '../../hooks/useCapability'
import { formatApiError } from '../../api/errors'
import { getNodes, getProxmoxTemplates } from '../../api/cluster'
import { useInvalidateStacks, useStackCloudInit, useStackFirewallRefs } from './hooks'
import {
  createStack,
  updateStack,
  fetchStack,
  validateStack,
  previewNewStack,
} from './api'
import StackYamlEditor from './StackYamlEditor'
import StackFormEditor from './StackFormEditor'
import StackPreviewModal from './StackPreviewModal'
import StackEtagConflictModal from './StackEtagConflictModal'
import StackCloudInitTab from './StackCloudInitTab'
import CloudInitHintBanner from './CloudInitHintBanner'
import Watermark from '../../components/common/Watermark'
import HelpButton from '../../features/help/components/HelpButton'

const NEW_TEMPLATE = `name: my-stack
version: "1.0.0"
description: ""
resources: []
`

function stripUndefined(obj) {
  if (Array.isArray(obj)) return obj.map(stripUndefined)
  if (obj && typeof obj === 'object') {
    const out = {}
    for (const [k, v] of Object.entries(obj)) {
      if (v === undefined || v === null || v === '') continue
      out[k] = stripUndefined(v)
    }
    return out
  }
  return obj
}

function modelFromYaml(text) {
  const obj = jsyaml.load(text)
  if (!obj || typeof obj !== 'object') return { name: '', description: '', version: '1.0.0', resources: [], networks: [] }
  return {
    name: obj.name ?? '',
    description: obj.description ?? '',
    version: obj.version ?? '1.0.0',
    resources: Array.isArray(obj.resources) ? obj.resources : [],
    // PROJ-87: stack-owned Netze (Bridge/VNet) – ohne Sonderfall durch den Sync.
    networks: Array.isArray(obj.networks) ? obj.networks : [],
    // PROJ-91: stack-eigene Security-Groups – ebenfalls durch den Sync getragen.
    security_groups: Array.isArray(obj.security_groups) ? obj.security_groups : [],
  }
}

function yamlFromModel(model) {
  const networks = (model.networks || []).map(stripUndefined)
  const securityGroups = (model.security_groups || []).map(stripUndefined)
  const clean = {
    name: model.name || '',
    version: model.version || '1.0.0',
    ...(model.description ? { description: model.description } : {}),
    resources: (model.resources || []).map(stripUndefined),
    // Nur emittieren, wenn vorhanden → reine VM/LXC-Stacks bleiben byte-genau.
    ...(networks.length ? { networks } : {}),
    ...(securityGroups.length ? { security_groups: securityGroups } : {}),
  }
  return jsyaml.dump(clean, { lineWidth: 120, noRefs: true })
}

export default function StackEditorPage() {
  const { t } = useTranslation()
  const canUseStacks = useCapability('stacks')
  const navigate = useNavigate()
  const location = useLocation()
  const { id } = useParams()
  const isEdit = !!id
  // VMID-Vorschläge aus dem Plan-Modal ("Nächste freie IDs wählen") – einmal anwenden.
  const vmidSuggestionsRef = useRef(location.state?.vmidSuggestions || null)

  const [mode, setMode] = useState('form')          // 'form' | 'yaml' | 'cloudinit' — Formular ist Default (AC-UI-3)
  const [yamlText, setYamlText] = useState(isEdit ? '' : NEW_TEMPLATE)
  const [loading, setLoading] = useState(isEdit)
  const [loadError, setLoadError] = useState(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState(null)
  const [pending, setPending] = useState(null)      // pending_approval response
  const [conflict, setConflict] = useState(null)    // EtagConflictResponse

  const [validation, setValidation] = useState(null) // { valid, errors, warnings }
  const [validating, setValidating] = useState(false)

  const [previewOpen, setPreviewOpen] = useState(false)
  const [preview, setPreview] = useState(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState(null)

  const [nodeOptions, setNodeOptions] = useState([])
  const [templateOptions, setTemplateOptions] = useState([])

  const invalidate = useInvalidateStacks()

  // PROJ-85: Cloud-Init-Konfig (eigener Store, nur Edit) — für Tab + Hinweis-Banner.
  const { data: cloudInit } = useStackCloudInit(isEdit ? id : null)

  // PROJ-91: Firewall-Editor-Daten (Aliases/IPSets/Macros/Cluster-SGs) für die
  // Regel-Dropdowns. Best-effort, leer → Freitext-Fallback.
  const { data: fwData } = useStackFirewallRefs()

  // ETag-Concurrency-State (Edit-Modus).
  const expectedEtagRef = useRef(null)   // ETag, mit dem der Editor geöffnet wurde
  const baseYamlRef = useRef('')         // YAML-Stand beim Öffnen (Pass-Through im 409-Body)
  const [changeSummary, setChangeSummary] = useState('')

  // Load nodes/templates for form dropdown suggestions (best-effort).
  useEffect(() => {
    getNodes().then((rows) => {
      const names = (rows || []).map((n) => n.node || n.name).filter(Boolean)
      setNodeOptions([...new Set(names)])
    }).catch(() => {})
    // Rohe Template-Objekte ({name, vmid, node}) — die VM-Karte filtert node-abhängig.
    getProxmoxTemplates().then((rows) => {
      setTemplateOptions(Array.isArray(rows) ? rows : [])
    }).catch(() => {})
  }, [])

  // Load existing stack on edit.
  useEffect(() => {
    if (!isEdit) return
    let cancelled = false
    setLoading(true)
    fetchStack(id)
      .then((s) => {
        if (cancelled) return
        let text = s.yaml_text || ''
        // VMID-Vorschläge aus dem Plan-Modal einmalig auf die geladene Definition anwenden.
        const sugg = vmidSuggestionsRef.current
        if (Array.isArray(sugg) && sugg.length) {
          vmidSuggestionsRef.current = null
          try {
            const m = modelFromYaml(text)
            sugg.forEach(({ index, new_vmid }) => {
              if (m.resources[index]) m.resources[index].vmid = new_vmid
            })
            text = yamlFromModel(m)
          } catch { /* bei Parse-Fehler Original behalten */ }
        }
        setYamlText(text)
        expectedEtagRef.current = s.current_etag
        baseYamlRef.current = s.yaml_text || ''
      })
      .catch((err) => { if (!cancelled) setLoadError(formatApiError(err, t('common.error_generic'))) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [id, isEdit, t])

  // Parse current YAML → model (for form mode). Track parse errors.
  const { model, parseError } = useMemo(() => {
    try {
      return { model: modelFromYaml(yamlText), parseError: null }
    } catch (e) {
      return { model: { name: '', description: '', version: '1.0.0', resources: [] }, parseError: e.message }
    }
  }, [yamlText])

  // Form → YAML (Live-Sync).
  const handleModelChange = (next) => {
    try {
      setYamlText(yamlFromModel(next))
    } catch {
      /* keep last valid yaml */
    }
  }

  const buildBody = (extra = {}) => {
    // YAML ist Single Source of Truth – wir senden immer yaml_text.
    return { yaml_text: yamlText, source_kind: 'structured', ...extra }
  }

  const handleValidate = async () => {
    setValidating(true)
    setValidation(null)
    try {
      const res = await validateStack(buildBody())
      setValidation(res)
    } catch (err) {
      setValidation({ valid: false, errors: [formatApiError(err, t('common.error_generic'))], warnings: [] })
    } finally {
      setValidating(false)
    }
  }

  const handlePreview = async () => {
    setPreviewOpen(true)
    setPreviewLoading(true)
    setPreviewError(null)
    setPreview(null)
    try {
      const res = await previewNewStack(buildBody())
      setPreview(res)
    } catch (err) {
      setPreviewError(formatApiError(err, t('common.error_generic')))
    } finally {
      setPreviewLoading(false)
    }
  }

  const doSave = async (overrideEtag) => {
    setSaving(true)
    setSaveError(null)
    setPending(null)
    try {
      if (isEdit) {
        const body = buildBody({
          expected_etag: overrideEtag || expectedEtagRef.current,
          base_yaml: baseYamlRef.current,
          change_summary: changeSummary || undefined,
        })
        const { kind, data } = await updateStack(id, body, changeSummary || undefined)
        if (kind === 'pending') { setPending(data); return }
        invalidate(Number(id))
        navigate(`/stacks/${id}`)
      } else {
        const created = await createStack(buildBody())
        invalidate()
        navigate(`/stacks/${created.id}`)
      }
    } catch (err) {
      if (err?.response?.status === 409 && err.response.data?.current_etag) {
        setConflict(err.response.data)
      } else {
        setSaveError(formatApiError(err, t('common.error_generic')))
      }
    } finally {
      setSaving(false)
    }
  }

  const handleOverride = (currentEtag) => {
    setConflict(null)
    expectedEtagRef.current = currentEtag
    doSave(currentEtag)
  }

  const handleReloadConflict = () => {
    if (conflict?.current_yaml != null) {
      setYamlText(conflict.current_yaml)
      expectedEtagRef.current = conflict.current_etag
      baseYamlRef.current = conflict.current_yaml
    }
    setConflict(null)
  }

  if (!canUseStacks) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <p className="text-sm text-portal-text2">{t('stacks.not_available')}</p>
      </div>
    )
  }

  const tabCls = (m) =>
    `px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
      mode === m
        ? 'border-portal-accent text-portal-white'
        : 'border-transparent text-portal-text2 hover:text-portal-white'
    }`

  return (
    <div className="flex flex-col flex-1 min-h-0">
      <header className="h-12 flex items-center justify-between px-6 border-b border-gray-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 shrink-0">
        <div className="flex items-center gap-2">
          <button onClick={() => navigate('/stacks')} className="btn-table" aria-label={t('common.back')}>←</button>
          <h1 className="text-sm font-semibold text-gray-900 dark:text-zinc-100">
            {isEdit ? t('stacks.editor.title_edit') : t('stacks.editor.title_new')}
          </h1>
          <HelpButton helpKey="stacks.editor" />
        </div>
      </header>
      <main className="flex-1 overflow-y-auto px-6 py-6 space-y-4 bg-transparent">
        {loading ? (
          <p className="text-sm text-portal-text2">{t('common.loading')}</p>
        ) : loadError ? (
          <p className="text-sm text-portal-danger">{loadError}</p>
        ) : (
          <>
            {/* Tab toggle */}
            <div className="flex border-b border-portal-border">
              <button className={tabCls('form')} onClick={() => setMode('form')}>{t('stacks.editor.tab_form')}</button>
              <button className={tabCls('yaml')} onClick={() => setMode('yaml')}>{t('stacks.editor.tab_yaml')}</button>
              <button className={tabCls('cloudinit')} onClick={() => setMode('cloudinit')}>{t('stacks.editor.tab_cloudinit')}</button>
            </div>

            {mode === 'cloudinit' ? (
              <StackCloudInitTab
                stackId={isEdit ? Number(id) : null}
                resources={(model.resources || [])
                  .filter((r) => r?.name)
                  .map((r) => ({ name: r.name, type: r.type === 'lxc' ? 'lxc' : 'vm' }))}
              />
            ) : (
            <>
            {/* PROJ-85: Hinweis, dass der Login im Cloud-Init-Tab liegt (AC-UI-2) */}
            <CloudInitHintBanner data={cloudInit} />

            {/* Editor body */}
            <div className="bg-white dark:bg-zinc-900 rounded-lg border border-gray-200 dark:border-zinc-700">
              {mode === 'yaml' ? (
                <div className="h-[420px]">
                  <StackYamlEditor value={yamlText} onChange={setYamlText} />
                </div>
              ) : parseError ? (
                <div className="p-4">
                  <p className="text-sm text-portal-danger mb-2">{t('stacks.editor.yaml_parse_error')}</p>
                  <pre className="text-xs font-mono text-portal-text2 whitespace-pre-wrap">{parseError}</pre>
                </div>
              ) : (
                <div className="p-1">
                  <StackFormEditor
                    model={model}
                    onChange={handleModelChange}
                    nodeOptions={nodeOptions}
                    templateOptions={templateOptions}
                    fwRefs={fwData?.refs || []}
                    fwMacros={fwData?.macros || []}
                    clusterSgNames={fwData?.clusterSgNames || []}
                  />
                </div>
              )}
            </div>

            {/* Validation result */}
            {validation && (
              <div className={`rounded-md border p-3 text-xs space-y-1 ${
                validation.valid && validation.errors.length === 0
                  ? 'border-portal-success/40 bg-portal-success/10'
                  : 'border-portal-danger/40 bg-portal-danger/10'
              }`}>
                <p className={`font-semibold ${validation.valid && validation.errors.length === 0 ? 'text-portal-success' : 'text-portal-danger'}`}>
                  {validation.valid && validation.errors.length === 0 ? t('stacks.validation.ok') : t('stacks.validation.errors')}
                </p>
                {validation.errors?.map((e, i) => <p key={`e${i}`} className="text-portal-danger">• {e}</p>)}
                {validation.warnings?.map((w, i) => <p key={`w${i}`} className="text-portal-warn">⚠ {w}</p>)}
              </div>
            )}

            {pending && (
              <div className="rounded-md border border-portal-warn/40 bg-portal-warn/10 p-3 text-xs text-portal-warn">
                {t('stacks.approval.pending')}{' '}
                {pending.poll_url && (
                  <a href={pending.poll_url} className="underline" onClick={(e) => { e.preventDefault(); navigate(`/account?tab=workflow&sub=antraege`) }}>
                    {t('stacks.approval.view_request')}
                  </a>
                )}
              </div>
            )}

            {saveError && <p className="text-sm text-portal-danger">{saveError}</p>}

            {/* Optional change summary (edit only) */}
            {isEdit && (
              <label className="flex flex-col gap-1 text-xs max-w-md">
                <span className="text-portal-text2 font-medium">{t('stacks.editor.change_summary')}</span>
                <input
                  className="w-full px-2 py-1.5 text-sm rounded-md border border-portal-border bg-portal-bg2 text-portal-text focus:outline-none focus:ring-1 focus:ring-portal-accent"
                  value={changeSummary}
                  onChange={(e) => setChangeSummary(e.target.value)}
                  placeholder={t('stacks.editor.change_summary_ph')}
                />
              </label>
            )}

            {/* Actions */}
            <div className="flex flex-wrap items-center gap-2 pt-2">
              <button onClick={handleValidate} disabled={validating} className="btn-secondary">
                {validating ? t('common.loading') : t('stacks.editor.validate_btn')}
              </button>
              <button onClick={handlePreview} className="btn-secondary">{t('stacks.editor.preview_btn')}</button>
              <div className="flex-1" />
              <button onClick={() => navigate(isEdit ? `/stacks/${id}` : '/stacks')} className="btn-secondary">
                {t('common.cancel')}
              </button>
              <button onClick={() => doSave()} disabled={saving} className="btn-primary">
                {saving ? t('common.loading') : t('stacks.editor.save_btn')}
              </button>
            </div>
            </>
            )}
          </>
        )}

        <Watermark />
      </main>

      {previewOpen && (
        <StackPreviewModal
          preview={preview}
          loading={previewLoading}
          error={previewError}
          onClose={() => setPreviewOpen(false)}
        />
      )}

      {conflict && (
        <StackEtagConflictModal
          conflict={conflict}
          onReload={handleReloadConflict}
          onOverride={handleOverride}
          onClose={() => setConflict(null)}
        />
      )}
    </div>
  )
}
