// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-93: YAML-Tab (AC-YAML). Zeigt das generierte <id>.yml + meta.yaml +
// Nebendatei-Liste über POST /preview — **read-only** (structured-SoT, kein
// YAML-Rück-Parser, AC-ROUND-3). Anders als PROJ-92 keine Direktbearbeitung.
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { formatApiError } from '../../api/errors'
import PlainCodeEditor from './PlainCodeEditor'

export default function YamlProjection({ previewFn }) {
  const { t } = useTranslation()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const load = () => {
    setLoading(true)
    setError(null)
    return previewFn()
      .then((res) => setData(res))
      .catch((err) => setError(formatApiError(err, t('ansible_editor.preview_error'))))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    previewFn()
      .then((res) => { if (!cancelled) setData(res) })
      .catch((err) => { if (!cancelled) setError(formatApiError(err, t('ansible_editor.preview_error'))) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const files = data?.files || {}
  const fileNames = Object.keys(files)

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between gap-2">
        <h5 className="text-xs font-semibold text-portal-text2">&lt;id&gt;.yml</h5>
        <button type="button" className="btn-table" disabled={loading} onClick={load}>
          {loading ? '…' : t('ansible_editor.yaml_refresh')}
        </button>
      </div>

      {error && <p className="text-sm text-portal-danger">{error}</p>}

      {data && (
        <>
          <PlainCodeEditor value={data.yaml} onChange={() => {}} readOnly minHeight="260px" />

          {data.warnings?.length > 0 && (
            <div className="rounded-md border border-portal-warn/40 bg-portal-warn/10 p-2 text-[11px] space-y-1">
              {data.warnings.map((w, i) => <p key={i} className="text-portal-warn">⚠ {w}</p>)}
            </div>
          )}

          <div>
            <h5 className="text-xs font-semibold text-portal-text2 mb-1">meta.yaml</h5>
            <PlainCodeEditor value={data.meta_yaml} onChange={() => {}} readOnly minHeight="120px" />
          </div>

          {fileNames.length > 0 && (
            <div>
              <h5 className="text-xs font-semibold text-portal-text2 mb-1">{t('ansible_editor.yaml_files')}</h5>
              <ul className="text-[11px] font-mono text-portal-text2 space-y-0.5">
                {fileNames.map((n) => <li key={n}>files/{n}</li>)}
              </ul>
            </div>
          )}
        </>
      )}
    </div>
  )
}
