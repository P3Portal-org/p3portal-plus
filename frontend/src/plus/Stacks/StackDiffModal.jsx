// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-76 Phase 1: Diff-Modal für Stack-Versionen (AC-UI-10, analog PROJ-74).
import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchDiff } from './api'

// BUG-76-1: portal-* Theme-Tokens statt roher Tailwind-Farben (PROJ-58, AC-UI-10).
const ROW_STYLES = {
  added:     'bg-portal-success/10',
  removed:   'bg-portal-danger/10',
  changed:   'bg-portal-warn/10',
  unchanged: '',
}

function StatusBadge({ change, t }) {
  if (change === 'unchanged') return <span className="text-[10px] font-bold uppercase text-portal-text3">{t('stacks.diff.unchanged')}</span>
  if (change === 'changed') return <span className="text-[10px] font-bold uppercase text-portal-warn">~ {t('stacks.diff.changed')}</span>
  if (change === 'added') return <span className="text-[10px] font-bold uppercase text-portal-success">+ {t('stacks.diff.added')}</span>
  if (change === 'removed') return <span className="text-[10px] font-bold uppercase text-portal-danger">− {t('stacks.diff.removed')}</span>
  return null
}

export default function StackDiffModal({ stackId, from, to, fromLabel, toLabel, onClose }) {
  const { t } = useTranslation()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [hideUnchanged, setHideUnchanged] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true); setError(null)
    fetchDiff(stackId, from, to)
      .then((d) => { if (!cancelled) setData(d) })
      .catch((err) => { if (!cancelled) setError(err?.response?.data?.detail ?? t('common.error_generic')) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [stackId, from, to, t])

  const entries = data?.diff ?? []
  const visible = hideUnchanged ? entries.filter((e) => e.change !== 'unchanged') : entries
  const changedCount = entries.filter((e) => e.change !== 'unchanged').length

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-700 rounded-lg w-full max-w-4xl mx-4 shadow-xl flex flex-col max-h-[85vh]">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200 dark:border-zinc-700 shrink-0">
          <div>
            <h2 className="text-sm font-semibold text-gray-900 dark:text-zinc-100">{t('stacks.diff.title')}</h2>
            <p className="text-xs text-portal-text2 mt-0.5">
              {(fromLabel || data?.from_label)} → {(toLabel || data?.to_label)}
              {data && <> · {changedCount === 0 ? t('stacks.diff.identical') : t('stacks.diff.changes', { count: changedCount })}</>}
            </p>
          </div>
          <button onClick={onClose} className="btn-ghost text-gray-400 hover:text-gray-600" aria-label={t('common.close')}>✕</button>
        </div>

        <div className="px-5 py-2 border-b border-gray-100 dark:border-zinc-800 shrink-0">
          <label className="flex items-center gap-2 text-xs text-portal-text2">
            <input type="checkbox" checked={hideUnchanged} onChange={(e) => setHideUnchanged(e.target.checked)} className="accent-[var(--accent)]" />
            {t('stacks.diff.hide_unchanged')}
          </label>
        </div>

        <div className="overflow-auto flex-1">
          {loading && <p className="p-5 text-sm text-portal-text2">{t('common.loading')}</p>}
          {error && <p className="p-5 text-sm text-portal-danger">{error}</p>}
          {data && visible.length === 0 && <p className="p-5 text-sm text-portal-text2">{t('stacks.diff.no_changes')}</p>}
          {data && visible.length > 0 && (
            <table className="w-full">
              <thead className="sticky top-0 bg-gray-50 dark:bg-zinc-800/90">
                <tr className="text-xs text-portal-text3 border-b border-portal-border text-left">
                  <th className="px-3 py-2 font-medium">{t('stacks.diff.col_key')}</th>
                  <th className="px-3 py-2 font-medium">{fromLabel || data.from_label}</th>
                  <th className="px-3 py-2 font-medium">{toLabel || data.to_label}</th>
                  <th className="px-3 py-2 font-medium">{t('stacks.diff.col_status')}</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((e) => (
                  <tr key={e.key} className={`text-xs font-mono border-b border-gray-100 dark:border-zinc-800 ${ROW_STYLES[e.change] ?? ''}`}>
                    <td className="px-3 py-1.5 align-top font-semibold whitespace-nowrap text-gray-700 dark:text-zinc-300">{e.key}</td>
                    <td className="px-3 py-1.5 align-top whitespace-pre-wrap break-all text-gray-600 dark:text-zinc-400">
                      {e.from_value ?? <span className="italic text-gray-400">—</span>}
                    </td>
                    <td className="px-3 py-1.5 align-top whitespace-pre-wrap break-all text-gray-600 dark:text-zinc-400">
                      {e.to_value ?? <span className="italic text-gray-400">—</span>}
                    </td>
                    <td className="px-3 py-1.5 align-top whitespace-nowrap"><StatusBadge change={e.change} t={t} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="flex justify-end px-5 py-4 border-t border-gray-200 dark:border-zinc-700 shrink-0">
          <button type="button" onClick={onClose} className="btn-secondary">{t('common.close')}</button>
        </div>
      </div>
    </div>
  )
}
