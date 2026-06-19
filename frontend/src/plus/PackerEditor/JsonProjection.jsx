// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-92: HCL-Tab. Zeigt die generierte <id>.pkr.hcl + meta.yaml + Nebendateien
// über POST /preview. Zusätzlich **HCL-Direktbearbeiten** (Raw-Override, analog
// zum Installer-Builder): „HCL direkt bearbeiten" übernimmt die generierte HCL als
// Startinhalt und setzt hcl_override=true → die HCL wird verbatim gespeichert
// (kein Rück-Parsen ins Formular). Nebendateien + meta.yaml kommen weiterhin aus
// dem Formular. „Aus Formular neu generieren" verwirft den Override.
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { formatApiError } from '../../api/errors'
import PlainCodeEditor from './PlainCodeEditor'
import ConfirmModal from '../../components/common/ConfirmModal'

export default function JsonProjection({ previewFn, model, onChange }) {
  const { t } = useTranslation()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [confirmOff, setConfirmOff] = useState(false) // HCL-Override-verwerfen (P3 ConfirmModal)

  const override = !!model?.hcl_override

  const load = () => {
    setLoading(true)
    setError(null)
    return previewFn()
      .then((res) => setData(res))
      .catch((err) => setError(formatApiError(err, t('packer_editor.preview_error'))))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    // Einmal beim Öffnen laden: liefert die generierte HCL-Projektion (Nicht-
    // Override) bzw. im Override meta.yaml + Nebendateien. Die HCL-Eingabe im
    // Override stammt aus dem Modell (model.hcl_content), nicht aus /preview.
    let cancelled = false
    setLoading(true)
    setError(null)
    previewFn()
      .then((res) => { if (!cancelled) setData(res) })
      .catch((err) => { if (!cancelled) setError(formatApiError(err, t('packer_editor.preview_error'))) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // In den Override-Modus wechseln: generierte HCL als Startinhalt übernehmen.
  const enableOverride = async () => {
    setBusy(true)
    setError(null)
    try {
      const preview = await previewFn()
      onChange({ hcl_override: true, hcl_content: preview?.hcl || '' })
    } catch (err) {
      // Auch ohne Vorschau Override erlauben (leerer Start).
      onChange({ hcl_override: true, hcl_content: model?.hcl_content || '' })
      setError(formatApiError(err, t('packer_editor.preview_error')))
    } finally {
      setBusy(false)
    }
  }

  const disableOverride = () => setConfirmOff(true)

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between gap-2">
        <h5 className="text-xs font-semibold text-portal-text2">&lt;id&gt;.pkr.hcl</h5>
        <div className="flex gap-2">
          {!override && (
            <>
              <button type="button" className="btn-table" disabled={loading} onClick={load}>
                {loading ? '…' : t('packer_editor.hcl_refresh')}
              </button>
              <button type="button" className="btn-table" disabled={busy} onClick={enableOverride}>
                {t('packer_editor.hcl_edit')}
              </button>
            </>
          )}
          {override && (
            <button type="button" className="btn-table" onClick={disableOverride}>
              {t('packer_editor.hcl_regenerate')}
            </button>
          )}
        </div>
      </div>

      {error && <p className="text-sm text-portal-danger whitespace-pre-wrap">{error}</p>}

      {override ? (
        <>
          <div className="rounded-md border border-portal-warn/40 bg-portal-warn/10 p-2 text-[11px] text-portal-warn">
            {t('packer_editor.hcl_override_active')}
          </div>
          <PlainCodeEditor
            value={model.hcl_content}
            onChange={(v) => onChange({ hcl_content: v })}
            minHeight="360px"
          />
        </>
      ) : loading ? (
        <p className="text-sm text-portal-text2">{t('common.loading')}</p>
      ) : data ? (
        <>
          {data.warnings?.length > 0 && (
            <div className="rounded-md border border-portal-warn/40 bg-portal-warn/10 p-2 text-xs text-portal-warn space-y-1">
              {data.warnings.map((w, i) => <p key={i}>⚠ {w}</p>)}
            </div>
          )}
          <pre className="text-[11px] font-mono text-portal-text bg-portal-bg2 border border-portal-border rounded-md p-3 overflow-auto max-h-[360px] whitespace-pre">
            {data.hcl}
          </pre>
        </>
      ) : null}

      {/* meta.yaml + Nebendateien (immer aus dem Formular generiert) */}
      {data && (
        <>
          <div>
            <h5 className="text-xs font-semibold text-portal-text2 mb-1">meta.yaml</h5>
            <pre className="text-[11px] font-mono text-portal-text bg-portal-bg2 border border-portal-border rounded-md p-3 overflow-auto max-h-[200px] whitespace-pre">
              {data.meta_yaml}
            </pre>
          </div>

          <div>
            <h5 className="text-xs font-semibold text-portal-text2 mb-1">{t('packer_editor.json.files')} ({Object.keys(data.files || {}).length})</h5>
            {Object.keys(data.files || {}).length === 0 ? (
              <p className="text-[11px] text-portal-text3">{t('packer_editor.json.no_files')}</p>
            ) : (
              <div className="space-y-2">
                {Object.keys(data.files).map((name) => (
                  <details key={name} className="rounded-md border border-portal-border bg-portal-bg2">
                    <summary className="cursor-pointer px-3 py-1.5 text-xs font-mono text-portal-text">{name}</summary>
                    <pre className="text-[11px] font-mono text-portal-text2 px-3 pb-2 overflow-auto max-h-[240px] whitespace-pre">{data.files[name]}</pre>
                  </details>
                ))}
              </div>
            )}
          </div>
        </>
      )}

      {confirmOff && (
        <ConfirmModal
          title={t('packer_editor.hcl_override_off_title')}
          body={t('packer_editor.hcl_override_off_confirm')}
          confirmLabel={t('common.confirm')}
          cancelLabel={t('common.cancel')}
          variant="danger"
          onConfirm={() => onChange({ hcl_override: false, hcl_content: '' })}
          onClose={() => setConfirmOff(false)}
        />
      )}
    </div>
  )
}
