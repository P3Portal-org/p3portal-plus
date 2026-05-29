// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-74: Detail-Modal für Config-Snapshot (rekonstruiertes .conf anzeigen).
import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchSnapshotDetail, downloadSnapshot } from './api'

export default function ConfigSnapshotDetailModal({ snapshotId, onClose }) {
  const { t } = useTranslation()
  const [detail, setDetail] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    fetchSnapshotDetail(snapshotId)
      .then(d => { if (!cancelled) setDetail(d) })
      .catch(err => { if (!cancelled) setError(err?.response?.data?.detail ?? t('common.error_generic')) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [snapshotId, t])

  const renderConf = payload => {
    if (!payload || typeof payload !== 'object') return ''
    const lines = []
    const description = payload.description
    if (description) {
      description.split('\n').forEach(l => lines.push(`# ${l}`))
    }
    Object.keys(payload).sort().forEach(k => {
      if (k === 'description') return
      lines.push(`${k}: ${payload[k]}`)
    })
    return lines.join('\n')
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-700 rounded-lg w-full max-w-2xl mx-4 shadow-xl flex flex-col max-h-[80vh]">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200 dark:border-zinc-700 shrink-0">
          <div>
            <h2 className="text-sm font-semibold text-gray-900 dark:text-zinc-100">
              {detail?.name ?? t('config_snapshots.detail_title')}
            </h2>
            {detail && (
              <p className="text-xs text-gray-400 dark:text-zinc-500 mt-0.5">
                {detail.kind?.toUpperCase()} · {detail.proxmox_node}/{detail.vmid} · {new Date(detail.created_at).toLocaleString()}
              </p>
            )}
          </div>
          <button onClick={onClose} className="btn-ghost text-gray-400 hover:text-gray-600 dark:text-zinc-500 dark:hover:text-zinc-300" aria-label={t('common.close')}>✕</button>
        </div>

        <div className="overflow-auto flex-1 p-5">
          {loading && <p className="text-sm text-gray-500 dark:text-zinc-400">{t('common.loading')}</p>}
          {error && <p className="text-sm text-red-500">{error}</p>}
          {detail && (
            <div className="space-y-4">
              {detail.note && (
                <div className="bg-[var(--portal-bg2)] rounded-md px-3 py-2">
                  <p className="text-xs text-gray-500 dark:text-zinc-400 font-medium mb-1">{t('config_snapshots.field_note')}</p>
                  <p className="text-sm text-gray-700 dark:text-zinc-300 whitespace-pre-wrap">{detail.note}</p>
                </div>
              )}
              <div>
                <p className="text-xs text-gray-500 dark:text-zinc-400 font-medium mb-1">{t('config_snapshots.detail_config')}</p>
                <pre className="text-xs font-mono bg-gray-50 dark:bg-zinc-800 border border-gray-200 dark:border-zinc-700 rounded-md p-3 overflow-auto whitespace-pre-wrap text-gray-800 dark:text-zinc-200">
                  {renderConf(detail.payload)}
                </pre>
              </div>
            </div>
          )}
        </div>

        <div className="flex justify-end gap-2 px-5 py-4 border-t border-gray-200 dark:border-zinc-700 shrink-0">
          {detail && (
            <button
              type="button"
              className="btn-secondary"
              onClick={() => downloadSnapshot(detail.id, detail.name + '.conf')}
            >
              {t('config_snapshots.btn_download')}
            </button>
          )}
          <button type="button" onClick={onClose} className="btn-secondary">{t('common.close')}</button>
        </div>
      </div>
    </div>
  )
}
