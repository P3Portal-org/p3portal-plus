// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-76 Phase 2b: Drift-Report-Modal (AC-2B-DRIFT, AC-2B-UI-5).
// Read-only `tofu plan` über NUR die Stack-eigenen VMs (State-Isolation).
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { formatApiError } from '../../api/errors'
import { useStackDrift } from './hooks'

const ITEM_STYLES = {
  in_sync: 'text-portal-success',
  changed: 'text-portal-warn',
  missing: 'text-portal-danger',
}

export default function StackDriftModal({ stackId, onClose, onChecked }) {
  const { t } = useTranslation()
  const driftMut = useStackDrift()
  const [report, setReport] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    setError(null)
    driftMut.mutateAsync(stackId)
      .then((d) => { if (!cancelled) { setReport(d); onChecked?.() } })
      .catch((err) => { if (!cancelled) setError(formatApiError(err, t('common.error_generic'))) })
    return () => { cancelled = true }
    // einmalig beim Öffnen; driftMut/t/onChecked stabil genug.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stackId])

  const items = report?.items ?? []

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-700 rounded-lg w-full max-w-2xl mx-4 shadow-xl flex flex-col max-h-[85vh]">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200 dark:border-zinc-700 shrink-0">
          <div>
            <h2 className="text-sm font-semibold text-gray-900 dark:text-zinc-100">{t('stacks.drift.title')}</h2>
            {report && (
              <p className={`text-xs mt-0.5 ${report.drift_state === 'in_sync' ? 'text-portal-success' : 'text-portal-warn'}`}>
                {report.drift_state === 'in_sync' ? t('stacks.drift.in_sync_summary') : t('stacks.drift.out_of_sync_summary')}
              </p>
            )}
          </div>
          <button onClick={onClose} className="btn-ghost text-gray-400 hover:text-gray-600" aria-label={t('common.close')}>✕</button>
        </div>

        <div className="overflow-auto flex-1 px-5 py-4">
          {driftMut.isPending && !report && <p className="text-sm text-portal-text2">{t('stacks.drift.checking')}</p>}
          {error && <p className="text-sm text-portal-danger">{error}</p>}
          {report && (
            <>
              <div className="flex flex-wrap items-center gap-2 mb-3">
                <span className="px-2 py-0.5 rounded-full text-[11px] font-medium bg-portal-success/15 text-portal-success">{report.in_sync} {t('stacks.drift.state.in_sync')}</span>
                {report.changed > 0 && <span className="px-2 py-0.5 rounded-full text-[11px] font-medium bg-portal-warn/15 text-portal-warn">{report.changed} {t('stacks.drift.state.changed')}</span>}
                {report.missing > 0 && <span className="px-2 py-0.5 rounded-full text-[11px] font-medium bg-portal-danger/15 text-portal-danger">{report.missing} {t('stacks.drift.state.missing')}</span>}
              </div>
              {items.length === 0 ? (
                <p className="text-sm text-portal-text2">{t('stacks.drift.no_resources')}</p>
              ) : (
                <div className="rounded-md border border-portal-border overflow-auto">
                  <table className="w-full text-xs">
                    <thead className="bg-portal-bg2">
                      <tr className="text-portal-text3 border-b border-portal-border text-left">
                        <th className="px-3 py-1.5 font-medium">{t('stacks.drift.col_resource')}</th>
                        <th className="px-3 py-1.5 font-medium">{t('stacks.drift.col_vmid')}</th>
                        <th className="px-3 py-1.5 font-medium">{t('stacks.drift.col_state')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {items.map((it, i) => (
                        <tr key={i} className="border-b border-portal-border/50 last:border-0">
                          <td className="px-3 py-1.5 font-mono text-portal-text">{it.resource_name}</td>
                          <td className="px-3 py-1.5 font-mono text-portal-text2">{it.vmid ?? '—'}</td>
                          <td className={`px-3 py-1.5 font-medium ${ITEM_STYLES[it.state] ?? 'text-portal-text2'}`}>
                            {t(`stacks.drift.state.${it.state}`, it.state)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {report.drift_state !== 'in_sync' && (
                <p className="text-xs text-portal-text3 mt-3">{t('stacks.drift.redeploy_hint')}</p>
              )}
            </>
          )}
        </div>

        <div className="flex justify-end px-5 py-4 border-t border-gray-200 dark:border-zinc-700 shrink-0">
          <button type="button" onClick={onClose} className="btn-secondary">{t('common.close')}</button>
        </div>
      </div>
    </div>
  )
}
