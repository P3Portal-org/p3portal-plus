// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-74: Diff-Modal (Snapshot vs. Live oder Snapshot A vs. B).
import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchDiffLive, fetchDiffAB, restoreKeys } from './api'

const CHANGE_ROW_STYLES = {
  added:     'bg-portal-success/10',
  removed:   'bg-portal-danger/10',
  changed:   'bg-portal-warn/10',
  unchanged: '',
}

function StatusBadge({ change, t }) {
  if (change === 'unchanged') {
    return <span className="text-[10px] font-bold uppercase text-portal-success">✓ {t('config_snapshots.diff_status_ok')}</span>
  }
  if (change === 'changed') {
    return <span className="text-[10px] font-bold uppercase text-portal-warn">~ {t('config_snapshots.diff_changed')}</span>
  }
  if (change === 'added') {
    return <span className="text-[10px] font-bold uppercase text-portal-success">+ {t('config_snapshots.diff_added')}</span>
  }
  if (change === 'removed') {
    return <span className="text-[10px] font-bold uppercase text-portal-danger">− {t('config_snapshots.diff_removed')}</span>
  }
  return null
}

function DiffRow({ entry, showSelect, selected, onToggle, t }) {
  const rowStyle = CHANGE_ROW_STYLES[entry.change] ?? ''
  return (
    <tr className={`text-xs font-mono border-b border-gray-100 dark:border-zinc-800 ${rowStyle}`}>
      {showSelect && (
        <td className="px-2 py-1.5 align-middle text-center w-8">
          <input
            type="checkbox"
            checked={selected}
            onChange={() => onToggle(entry.key)}
            className="accent-[var(--accent)] cursor-pointer"
            aria-label={entry.key}
          />
        </td>
      )}
      <td className="px-3 py-1.5 align-top font-semibold whitespace-nowrap text-gray-700 dark:text-zinc-300">
        {entry.key}
      </td>
      <td className="px-3 py-1.5 align-top whitespace-pre-wrap break-all text-gray-600 dark:text-zinc-400">
        {entry.snapshot_value ?? <span className="italic text-gray-400 dark:text-zinc-600">—</span>}
      </td>
      <td className="px-3 py-1.5 align-top whitespace-pre-wrap break-all text-gray-600 dark:text-zinc-400">
        {entry.live_value ?? <span className="italic text-gray-400 dark:text-zinc-600">—</span>}
      </td>
      <td className="px-3 py-1.5 align-top whitespace-nowrap">
        <StatusBadge change={entry.change} t={t} />
      </td>
    </tr>
  )
}

export default function ConfigSnapshotDiffModal({ mode, snapshotId, snapshotIdB, snapshotNameA, snapshotNameB, onClose }) {
  // mode: 'live' | 'ab'
  const { t } = useTranslation()
  const [entries, setEntries] = useState(null)
  const [liveEtag, setLiveEtag] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  // Checkbox selection (only relevant in mode='live')
  const [selected, setSelected] = useState(new Set())
  const [restoring, setRestoring] = useState(false)
  const [restoreMsg, setRestoreMsg] = useState(null)   // { type: 'ok'|'err', text }

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    setSelected(new Set())
    setRestoreMsg(null)
    const fetch = mode === 'ab'
      ? fetchDiffAB(snapshotId, snapshotIdB)
      : fetchDiffLive(snapshotId)
    fetch
      .then(d => {
        if (cancelled) return
        setEntries(d.diff ?? [])
        if (d.live_etag) setLiveEtag(d.live_etag)
      })
      .catch(err => { if (!cancelled) setError(err?.response?.data?.detail ?? t('common.error_generic')) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [mode, snapshotId, snapshotIdB, t])

  const toggleKey = useCallback((key) => {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(key) ? next.delete(key) : next.add(key)
      return next
    })
  }, [])

  const toggleAll = useCallback(() => {
    if (!entries) return
    const allKeys = entries.map(e => e.key)
    setSelected(prev => prev.size === allKeys.length ? new Set() : new Set(allKeys))
  }, [entries])

  const handleRestore = useCallback(async () => {
    if (!liveEtag || selected.size === 0) return
    setRestoring(true)
    setRestoreMsg(null)
    try {
      const result = await restoreKeys(snapshotId, { keys: [...selected], etag: liveEtag })
      const count = (result.restored_keys?.length ?? 0) + (result.deleted_keys?.length ?? 0)
      setRestoreMsg({ type: 'ok', text: t('config_snapshots.diff_restore_success', { count }) })
    } catch (err) {
      const detail = err?.response?.data?.detail
      if (detail === 'live_config_changed') {
        setRestoreMsg({ type: 'err', text: t('config_snapshots.diff_restore_stale') })
      } else {
        setRestoreMsg({ type: 'err', text: detail ?? t('common.error_generic') })
      }
    } finally {
      setRestoring(false)
    }
  }, [liveEtag, selected, snapshotId, t])

  const showSelect = mode === 'live'
  const colLeft = mode === 'ab'
    ? (snapshotNameA ?? t('config_snapshots.diff_col_snapshot_a'))
    : t('config_snapshots.diff_col_snapshot')
  const colRight = mode === 'ab'
    ? (snapshotNameB ?? t('config_snapshots.diff_col_snapshot_b'))
    : t('config_snapshots.diff_col_live')

  const changedCount = entries?.filter(e => e.change !== 'unchanged').length ?? 0
  const totalCount = entries?.length ?? 0
  const summaryText = entries == null
    ? null
    : changedCount === 0
      ? t('config_snapshots.diff_summary_identical', { count: totalCount })
      : t('config_snapshots.diff_summary_changes', { changed: changedCount, total: totalCount })

  const allSelected = entries != null && entries.length > 0 && selected.size === entries.length

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-700 rounded-lg w-full max-w-4xl mx-4 shadow-xl flex flex-col max-h-[85vh]">

        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200 dark:border-zinc-700 shrink-0">
          <div>
            <h2 className="text-sm font-semibold text-gray-900 dark:text-zinc-100">
              {mode === 'ab' ? t('config_snapshots.diff_title_ab') : t('config_snapshots.diff_title_live')}
            </h2>
            {summaryText && (
              <p className={`text-xs mt-0.5 ${changedCount === 0 ? 'text-portal-success' : 'text-portal-warn'}`}>
                {summaryText}
              </p>
            )}
          </div>
          <button onClick={onClose} className="btn-ghost text-gray-400 hover:text-gray-600 dark:text-zinc-500 dark:hover:text-zinc-300" aria-label={t('common.close')}>✕</button>
        </div>

        {/* Body */}
        <div className="overflow-auto flex-1">
          {loading && <p className="p-5 text-sm text-gray-500 dark:text-zinc-400">{t('common.loading')}</p>}
          {error && <p className="p-5 text-sm text-portal-danger">{error}</p>}
          {entries && entries.length === 0 && (
            <p className="p-5 text-sm text-gray-500 dark:text-zinc-400">{t('config_snapshots.diff_no_keys')}</p>
          )}
          {entries && entries.length > 0 && (
            <table className="w-full">
              <thead className="sticky top-0 z-10 bg-gray-50 dark:bg-zinc-800/90">
                <tr className="text-xs text-gray-500 dark:text-zinc-400 border-b border-gray-200 dark:border-zinc-700">
                  {showSelect && (
                    <th className="px-2 py-2 w-8 text-center">
                      <input
                        type="checkbox"
                        checked={allSelected}
                        onChange={toggleAll}
                        className="accent-[var(--accent)] cursor-pointer"
                        title={t('config_snapshots.diff_col_select')}
                      />
                    </th>
                  )}
                  <th className="px-3 py-2 text-left font-medium">{t('config_snapshots.diff_col_key')}</th>
                  <th className="px-3 py-2 text-left font-medium">{colLeft}</th>
                  <th className="px-3 py-2 text-left font-medium">{colRight}</th>
                  <th className="px-3 py-2 text-left font-medium">{t('config_snapshots.diff_col_status')}</th>
                </tr>
              </thead>
              <tbody>
                {entries.map(e => (
                  <DiffRow
                    key={e.key}
                    entry={e}
                    showSelect={showSelect}
                    selected={selected.has(e.key)}
                    onToggle={toggleKey}
                    t={t}
                  />
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between gap-3 px-5 py-4 border-t border-gray-200 dark:border-zinc-700 shrink-0">
          <div className="flex items-center gap-3 min-w-0">
            {showSelect && selected.size > 0 && !restoreMsg && (
              <span className="text-xs text-gray-500 dark:text-zinc-400 shrink-0">
                {t('config_snapshots.diff_restore_hint', { count: selected.size })}
              </span>
            )}
            {restoreMsg && (
              <span className={`text-xs font-medium ${restoreMsg.type === 'ok' ? 'text-portal-success' : 'text-portal-danger'}`}>
                {restoreMsg.text}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {showSelect && (
              <button
                type="button"
                onClick={handleRestore}
                disabled={restoring || selected.size === 0 || restoreMsg?.type === 'ok'}
                className="btn-primary"
              >
                {restoring ? t('common.loading') : t('config_snapshots.diff_restore_btn')}
              </button>
            )}
            <button type="button" onClick={onClose} className="btn-secondary">{t('common.close')}</button>
          </div>
        </div>
      </div>
    </div>
  )
}
