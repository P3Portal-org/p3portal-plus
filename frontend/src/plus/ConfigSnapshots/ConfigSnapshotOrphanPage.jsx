// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-74: Admin-Seite für verwaiste Config-Snapshots (AC-ORPHAN-4..7).
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useOrphans, useDeleteOrphan } from './hooks'
import ConfigSnapshotDetailModal from './ConfigSnapshotDetailModal'

function formatDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString()
}

export default function ConfigSnapshotOrphanPage({ embedded }) {
  const { t } = useTranslation()
  const { data: orphans, isLoading, error, refetch } = useOrphans()
  const deleteMutation = useDeleteOrphan()
  const [detailId, setDetailId] = useState(null)
  const [deleteConfirmId, setDeleteConfirmId] = useState(null)
  const [deleteError, setDeleteError] = useState(null)

  const handleDelete = async id => {
    setDeleteError(null)
    try {
      await deleteMutation.mutateAsync(id)
      setDeleteConfirmId(null)
    } catch (err) {
      setDeleteError(err?.response?.data?.detail ?? t('config_snapshots.delete_error'))
    }
  }

  const list = orphans ?? []

  const content = (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-gray-900 dark:text-zinc-100">{t('config_snapshots.orphan_title')}</h2>
          <p className="text-xs text-gray-500 dark:text-zinc-400 mt-0.5">{t('config_snapshots.orphan_desc')}</p>
        </div>
        <span className="text-xs text-gray-400 dark:text-zinc-500">{list.length} {t('config_snapshots.snapshots_count')}</span>
      </div>

      {isLoading && <p className="text-sm text-gray-500 dark:text-zinc-400">{t('common.loading')}</p>}
      {error && (
        <div className="flex items-center gap-2">
          <p className="text-sm text-red-500">{error?.response?.data?.detail ?? t('common.error_generic')}</p>
          <button type="button" className="btn-secondary text-xs" onClick={() => refetch()}>{t('common.retry')}</button>
        </div>
      )}

      {!isLoading && !error && list.length === 0 && (
        <p className="text-sm text-gray-400 dark:text-zinc-500 py-6 text-center">{t('config_snapshots.orphan_empty')}</p>
      )}

      {list.length > 0 && (
        <div className="overflow-x-auto rounded-md border border-gray-200 dark:border-zinc-700">
          <table className="w-full text-xs">
            <thead className="text-gray-500 dark:text-zinc-400 bg-gray-50 dark:bg-zinc-800/60">
              <tr>
                <th className="px-3 py-2 text-left font-medium">{t('config_snapshots.col_name')}</th>
                <th className="px-3 py-2 text-left font-medium">VM/LXC</th>
                <th className="px-3 py-2 text-left font-medium">{t('config_snapshots.col_note')}</th>
                <th className="px-3 py-2 text-left font-medium">{t('config_snapshots.orphan_col_orphaned')}</th>
                <th className="px-3 py-2 text-right font-medium">{t('common.actions')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-zinc-800">
              {list.map(snap => (
                <tr key={snap.id} className="hover:bg-gray-50 dark:hover:bg-zinc-800/30">
                  <td className="px-3 py-2 font-mono text-gray-700 dark:text-zinc-300 max-w-[160px] truncate" title={snap.name}>{snap.name}</td>
                  <td className="px-3 py-2 text-gray-500 dark:text-zinc-500 whitespace-nowrap">
                    <span className="uppercase text-[10px] mr-1">{snap.kind}</span>{snap.proxmox_node}/{snap.vmid}
                  </td>
                  <td className="px-3 py-2 text-gray-600 dark:text-zinc-400 max-w-[160px] truncate" title={snap.note}>{snap.note || '—'}</td>
                  <td className="px-3 py-2 text-gray-500 dark:text-zinc-500 whitespace-nowrap">{formatDate(snap.orphaned_at)}</td>
                  <td className="px-3 py-2">
                    <div className="flex justify-end gap-1">
                      <button type="button" className="btn-table" onClick={() => setDetailId(snap.id)}>
                        {t('common.view')}
                      </button>
                      {deleteConfirmId === snap.id ? (
                        <>
                          <button type="button" className="btn-table-danger" onClick={() => handleDelete(snap.id)} disabled={deleteMutation.isPending}>
                            {t('common.confirm')}
                          </button>
                          <button type="button" className="btn-table" onClick={() => setDeleteConfirmId(null)}>{t('common.cancel')}</button>
                        </>
                      ) : (
                        <button type="button" className="btn-table-danger" onClick={() => setDeleteConfirmId(snap.id)}>
                          {t('common.delete')}
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {deleteError && <p className="text-xs text-red-500">{deleteError}</p>}

      {detailId && (
        <ConfigSnapshotDetailModal
          snapshotId={detailId}
          onClose={() => setDetailId(null)}
        />
      )}
    </div>
  )

  if (embedded) return content

  return (
    <div className="flex flex-col flex-1 min-h-0">
      <header className="h-12 flex items-center px-6 border-b border-gray-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 shrink-0">
        <h1 className="text-sm font-semibold text-gray-900 dark:text-zinc-100">{t('config_snapshots.orphan_page_title')}</h1>
      </header>
      <main className="flex-1 overflow-y-auto px-6 py-6">
        {content}
      </main>
    </div>
  )
}
