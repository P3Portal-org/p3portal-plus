// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-74: VM/LXC Config-Snapshots Tab (AC-LIST-*, AC-DL-*, AC-RESTORE-*, AC-DELETE-*).
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useConfigSnapshots, useDeleteSnapshot } from './hooks'
import { downloadSnapshot } from './api'
import ConfigSnapshotCreateModal from './ConfigSnapshotCreateModal'
import ConfigSnapshotUploadModal from './ConfigSnapshotUploadModal'
import ConfigSnapshotDetailModal from './ConfigSnapshotDetailModal'
import ConfigSnapshotDiffModal from './ConfigSnapshotDiffModal'
// PROJ-77: Auto-Badge für source==='auto'
import AutoBadge from '../AutoSnapshots/AutoBadge'

function formatDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString()
}

function SourceBadge({ source, t }) {
  const styles = {
    manual: 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300',
    upload: 'bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300',
    auto:   'bg-portal-info/10 text-portal-info border border-portal-info/30',
  }
  return (
    <span className={`inline-block text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded ${styles[source] ?? 'bg-gray-100 dark:bg-zinc-700 text-gray-600 dark:text-zinc-300'}`}>
      {t(`config_snapshots.source_${source}`, source)}
    </span>
  )
}

export default function ConfigSnapshotsTab({ portalNodeId, proxmoxNode, vmid, kind }) {
  const { t } = useTranslation()
  const invalidateParams = { portalNodeId, proxmoxNode, vmid, kind }
  const { data: snapshots, isLoading, error, refetch } = useConfigSnapshots({ portalNodeId, proxmoxNode, vmid, kind })
  const deleteMutation = useDeleteSnapshot(invalidateParams)

  const [showCreate, setShowCreate] = useState(false)
  const [showUpload, setShowUpload] = useState(false)
  const [detailId, setDetailId] = useState(null)
  const [diffSnap, setDiffSnap] = useState(null) // { id, name, mode }
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

  const list = snapshots ?? []

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <p className="text-xs text-gray-500 dark:text-zinc-400">
          {list.length} {t('config_snapshots.snapshots_count')}
        </p>
        <div className="flex gap-2">
          <button type="button" className="btn-secondary text-xs" onClick={() => setShowUpload(true)}>
            {t('config_snapshots.btn_upload')}
          </button>
          <button type="button" className="btn-primary text-xs" onClick={() => setShowCreate(true)}>
            + {t('config_snapshots.btn_create')}
          </button>
        </div>
      </div>

      {/* Loading / Error */}
      {isLoading && <p className="text-sm text-gray-500 dark:text-zinc-400">{t('common.loading')}</p>}
      {error && (
        <div className="flex items-center gap-2">
          <p className="text-sm text-red-500">{error?.response?.data?.detail ?? t('common.error_generic')}</p>
          <button type="button" className="btn-secondary text-xs" onClick={() => refetch()}>{t('common.retry')}</button>
        </div>
      )}

      {/* Empty */}
      {!isLoading && !error && list.length === 0 && (
        <p className="text-sm text-gray-400 dark:text-zinc-500 py-6 text-center">{t('config_snapshots.empty_tab')}</p>
      )}

      {/* Table */}
      {list.length > 0 && (
        <div className="overflow-x-auto rounded-md border border-gray-200 dark:border-zinc-700">
          <table className="w-full text-xs">
            <thead className="text-gray-500 dark:text-zinc-400 bg-gray-50 dark:bg-zinc-800/60">
              <tr>
                <th className="px-3 py-2 text-left font-medium">{t('config_snapshots.col_name')}</th>
                <th className="px-3 py-2 text-left font-medium">{t('config_snapshots.col_note')}</th>
                <th className="px-3 py-2 text-left font-medium">{t('config_snapshots.col_source')}</th>
                <th className="px-3 py-2 text-left font-medium">{t('config_snapshots.col_created')}</th>
                <th className="px-3 py-2 text-right font-medium">{t('common.actions')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-zinc-800">
              {list.map(snap => (
                <tr key={snap.id} className="hover:bg-gray-50 dark:hover:bg-zinc-800/30">
                  <td className="px-3 py-2 font-mono text-gray-700 dark:text-zinc-300 max-w-[200px] truncate" title={snap.name}>{snap.name}</td>
                  <td className="px-3 py-2 text-gray-600 dark:text-zinc-400 max-w-[180px] truncate" title={snap.note}>{snap.note || '—'}</td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <SourceBadge source={snap.source} t={t} />
                      {snap.source === 'auto' && snap.created_by_scheduled_job_id && (
                        <AutoBadge jobId={snap.created_by_scheduled_job_id} />
                      )}
                    </div>
                  </td>
                  <td className="px-3 py-2 text-gray-500 dark:text-zinc-500 whitespace-nowrap">{formatDate(snap.created_at)}</td>
                  <td className="px-3 py-2">
                    <div className="flex justify-end gap-1 flex-wrap">
                      <button type="button" className="btn-table" onClick={() => setDetailId(snap.id)}>
                        {t('common.view')}
                      </button>
                      <button type="button" className="btn-table" onClick={() => setDiffSnap({ id: snap.id, name: snap.name, mode: 'live' })}>
                        {t('config_snapshots.btn_diff')}
                      </button>
                      <button type="button" className="btn-table" onClick={() => downloadSnapshot(snap.id, snap.name + '.conf')}>
                        {t('config_snapshots.btn_download')}
                      </button>
                      {deleteConfirmId === snap.id ? (
                        <>
                          <button type="button" className="btn-table-danger" onClick={() => handleDelete(snap.id)} disabled={deleteMutation.isPending}>
                            {t('common.confirm')}
                          </button>
                          <button type="button" className="btn-table" onClick={() => setDeleteConfirmId(null)}>
                            {t('common.cancel')}
                          </button>
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

      {/* Modals */}
      {showCreate && (
        <ConfigSnapshotCreateModal
          portalNodeId={portalNodeId}
          proxmoxNode={proxmoxNode}
          vmid={vmid}
          kind={kind}
          onClose={() => setShowCreate(false)}
          onCreated={() => { setShowCreate(false); refetch() }}
        />
      )}
      {showUpload && (
        <ConfigSnapshotUploadModal
          portalNodeId={portalNodeId}
          proxmoxNode={proxmoxNode}
          vmid={vmid}
          kind={kind}
          onClose={() => setShowUpload(false)}
          onUploaded={() => { setShowUpload(false); refetch() }}
        />
      )}
      {detailId && (
        <ConfigSnapshotDetailModal
          snapshotId={detailId}
          onClose={() => setDetailId(null)}
        />
      )}
      {diffSnap && (
        <ConfigSnapshotDiffModal
          mode={diffSnap.mode}
          snapshotId={diffSnap.id}
          snapshotNameA={diffSnap.name}
          onClose={() => setDiffSnap(null)}
        />
      )}
    </div>
  )
}
