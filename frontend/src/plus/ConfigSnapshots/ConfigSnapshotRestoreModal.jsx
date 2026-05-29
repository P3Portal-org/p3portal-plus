// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-74: Restore-Modal mit Diff-Vorschau, ETag-Re-Check, VM-Name-Confirm (AC-RESTORE-*).
import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchDiffLive, restoreSnapshot } from './api'

function DiffSummary({ entries, t }) {
  const added = entries.filter(e => e.change === 'added').length
  const removed = entries.filter(e => e.change === 'removed').length
  const changed = entries.filter(e => e.change === 'changed').length
  if (added + removed + changed === 0) {
    return <p className="text-sm text-gray-500 dark:text-zinc-400">{t('config_snapshots.diff_identical')}</p>
  }
  return (
    <div className="space-y-1">
      <div className="flex gap-3 text-xs mb-2">
        {added > 0 && <span className="text-portal-success font-medium">+{added} {t('config_snapshots.diff_added')}</span>}
        {removed > 0 && <span className="text-portal-danger font-medium">−{removed} {t('config_snapshots.diff_removed')}</span>}
        {changed > 0 && <span className="text-portal-warn font-medium">~{changed} {t('config_snapshots.diff_changed')}</span>}
      </div>
      <div className="max-h-48 overflow-auto rounded-md border border-gray-200 dark:border-zinc-700">
        <table className="w-full text-xs font-mono">
          <tbody className="divide-y divide-gray-100 dark:divide-zinc-800">
            {entries.filter(e => e.change !== 'unchanged').map(e => {
              const rowCls = {
                added:   'bg-green-50 dark:bg-green-900/20 text-green-800 dark:text-green-300',
                removed: 'bg-red-50 dark:bg-red-900/20 text-red-800 dark:text-red-300',
                changed: 'bg-yellow-50 dark:bg-yellow-900/20 text-yellow-800 dark:text-yellow-300',
              }[e.change] ?? ''
              return (
                <tr key={e.key} className={rowCls}>
                  <td className="px-2 py-1 font-semibold whitespace-nowrap w-1/3">{e.key}</td>
                  <td className="px-2 py-1 whitespace-pre-wrap break-all">{e.snapshot_value ?? '—'} → {e.live_value ?? '—'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default function ConfigSnapshotRestoreModal({ snapshot, vmName, vmStatus, onClose, onRestored }) {
  const { t } = useTranslation()
  const [diffEntries, setDiffEntries] = useState(null)
  const [etag, setEtag] = useState(null)
  const [diffLoading, setDiffLoading] = useState(true)
  const [diffError, setDiffError] = useState(null)
  const [vmNameConfirm, setVmNameConfirm] = useState('')
  const [createPreRestore, setCreatePreRestore] = useState(true)
  const [restartAfter, setRestartAfter] = useState(vmStatus === 'running')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    fetchDiffLive(snapshot.id)
      .then(d => {
        if (cancelled) return
        setDiffEntries(d.entries ?? d)
        setEtag(d.etag ?? null)
      })
      .catch(err => { if (!cancelled) setDiffError(err?.response?.data?.detail ?? t('common.error_generic')) })
      .finally(() => { if (!cancelled) setDiffLoading(false) })
    return () => { cancelled = true }
  }, [snapshot.id, t])

  const nameMatch = vmNameConfirm.trim() === (vmName ?? '')

  const handleRestore = async () => {
    if (!nameMatch) return
    setBusy(true)
    setError(null)
    try {
      await restoreSnapshot(snapshot.id, {
        vmNameConfirm: vmNameConfirm.trim(),
        createPreRestoreSnapshot: createPreRestore,
        restartAfterRestore: restartAfter,
        etag,
      })
      onRestored()
    } catch (err) {
      const detail = err?.response?.data?.detail
      if (err?.response?.status === 409 && detail?.etag_mismatch) {
        setError(t('config_snapshots.restore_etag_mismatch'))
        // Reload diff to show new state
        setDiffLoading(true)
        fetchDiffLive(snapshot.id)
          .then(d => { setDiffEntries(d.entries ?? d); setEtag(d.etag ?? null) })
          .catch(() => {})
          .finally(() => setDiffLoading(false))
      } else {
        setError(typeof detail === 'string' ? detail : t('config_snapshots.restore_error'))
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-700 rounded-lg w-full max-w-xl mx-4 shadow-xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200 dark:border-zinc-700">
          <h2 className="text-sm font-semibold text-gray-900 dark:text-zinc-100">{t('config_snapshots.restore_title')}</h2>
          <button onClick={onClose} className="btn-ghost text-gray-400 hover:text-gray-600 dark:text-zinc-500 dark:hover:text-zinc-300" aria-label={t('common.close')}>✕</button>
        </div>

        <div className="p-5 space-y-4">
          {/* Diff preview */}
          <div>
            <p className="text-xs font-medium text-gray-700 dark:text-zinc-300 mb-2">{t('config_snapshots.restore_diff_preview')}</p>
            {diffLoading && <p className="text-sm text-gray-400 dark:text-zinc-500">{t('common.loading')}</p>}
            {diffError && <p className="text-sm text-red-500">{diffError}</p>}
            {diffEntries && <DiffSummary entries={diffEntries} t={t} />}
          </div>

          {/* Options */}
          <div className="space-y-2">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={createPreRestore}
                onChange={e => setCreatePreRestore(e.target.checked)}
              />
              <span className="text-xs text-gray-700 dark:text-zinc-300">{t('config_snapshots.restore_opt_pre_snapshot')}</span>
            </label>
            {vmStatus === 'running' && (
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={restartAfter}
                  onChange={e => setRestartAfter(e.target.checked)}
                />
                <span className="text-xs text-gray-700 dark:text-zinc-300">{t('config_snapshots.restore_opt_restart')}</span>
              </label>
            )}
          </div>

          {/* VM name confirm */}
          <div>
            <label htmlFor="vm-name-confirm" className="block text-xs font-medium text-gray-700 dark:text-zinc-300 mb-1">
              {t('config_snapshots.restore_confirm_label', { name: vmName })} <span className="text-red-500">*</span>
            </label>
            <input
              id="vm-name-confirm"
              type="text"
              value={vmNameConfirm}
              onChange={e => setVmNameConfirm(e.target.value)}
              placeholder={vmName}
              className="w-full text-sm bg-white dark:bg-zinc-800 border border-gray-300 dark:border-zinc-600 rounded-md px-3 py-2 text-gray-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-orange-500"
            />
            {vmNameConfirm && !nameMatch && (
              <p className="mt-1 text-xs text-red-500">{t('config_snapshots.restore_confirm_mismatch')}</p>
            )}
          </div>

          {error && <p className="text-xs text-red-500">{error}</p>}
        </div>

        <div className="flex justify-end gap-2 px-5 py-4 border-t border-gray-200 dark:border-zinc-700">
          <button type="button" onClick={onClose} className="btn-secondary">{t('common.cancel')}</button>
          <button
            type="button"
            onClick={handleRestore}
            disabled={busy || !nameMatch || diffLoading}
            className="btn-danger"
          >
            {busy ? t('common.saving') : t('config_snapshots.restore_submit')}
          </button>
        </div>
      </div>
    </div>
  )
}
