// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-74: Node-Übersicht Config-Snapshots Tab (AC-NODE-*, Bulk-Download, Bulk-Delete).
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useConfigSnapshotsByNode, useBulkDeleteSnapshots } from './hooks'
import { bulkDownloadSnapshots } from './api'

function formatDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString()
}

export default function ConfigSnapshotsNodeTab({ portalNodeId, active }) {
  const { t } = useTranslation()
  const [q, setQ] = useState('')
  const [kindFilter, setKindFilter] = useState('')
  const [since, setSince] = useState('')
  const [selected, setSelected] = useState(new Set())
  const [bulkError, setBulkError] = useState(null)
  const [bulkBusy, setBulkBusy] = useState(false)
  const [deleteConfirm, setDeleteConfirm] = useState(false)

  const { data: snapshots, isLoading, error, refetch } = useConfigSnapshotsByNode(
    { portalNodeId, q: q || undefined, kind: kindFilter || undefined, since: since || undefined },
    active && !!portalNodeId
  )
  const bulkDeleteMutation = useBulkDeleteSnapshots({ portalNodeId })

  const list = snapshots ?? []
  const allIds = list.map(s => s.id)
  const allSelected = allIds.length > 0 && allIds.every(id => selected.has(id))
  const someSelected = selected.size > 0

  const toggleAll = () => {
    if (allSelected) setSelected(new Set())
    else setSelected(new Set(allIds))
  }

  const toggleOne = id => {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  const handleBulkDownload = async () => {
    setBulkError(null)
    const ids = [...selected]
    const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
    await bulkDownloadSnapshots(ids, `config-snapshots-${ts}.zip`)
  }

  const handleBulkDelete = async () => {
    setBulkBusy(true)
    setBulkError(null)
    try {
      await bulkDeleteMutation.mutateAsync([...selected])
      setSelected(new Set())
      setDeleteConfirm(false)
    } catch (err) {
      setBulkError(err?.response?.data?.detail ?? t('config_snapshots.delete_error'))
    } finally {
      setBulkBusy(false)
    }
  }

  const isMultiNode = list.length > 0 && new Set(list.map(s => s.proxmox_node)).size > 1

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex flex-wrap gap-2 items-center">
        <input
          type="search"
          placeholder={t('config_snapshots.filter_search')}
          value={q}
          onChange={e => setQ(e.target.value)}
          className="text-xs bg-white dark:bg-zinc-800 border border-gray-300 dark:border-zinc-600 rounded-md px-3 py-1.5 text-gray-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-orange-500 w-48"
        />
        <select
          value={kindFilter}
          onChange={e => setKindFilter(e.target.value)}
          className="text-xs bg-white dark:bg-zinc-800 border border-gray-300 dark:border-zinc-600 rounded-md px-2 py-1.5 text-gray-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-orange-500"
        >
          <option value="">{t('config_snapshots.filter_kind_all')}</option>
          <option value="qemu">VM (QEMU)</option>
          <option value="lxc">LXC</option>
        </select>
        <input
          type="date"
          value={since}
          onChange={e => setSince(e.target.value)}
          title={t('config_snapshots.filter_since')}
          className="text-xs bg-white dark:bg-zinc-800 border border-gray-300 dark:border-zinc-600 rounded-md px-2 py-1.5 text-gray-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-orange-500"
        />
        <button type="button" className="btn-secondary text-xs" onClick={() => { setQ(''); setKindFilter(''); setSince('') }}>
          {t('common.reset')}
        </button>
        <span className="ml-auto text-xs text-gray-400 dark:text-zinc-500">{list.length} {t('config_snapshots.snapshots_count')}</span>
      </div>

      {/* Bulk actions */}
      {someSelected && (
        <div className="flex items-center gap-2 bg-[var(--portal-bg2)] border border-gray-200 dark:border-zinc-700 rounded-md px-3 py-2">
          <span className="text-xs text-gray-700 dark:text-zinc-300">{selected.size} {t('config_snapshots.selected')}</span>
          <button type="button" className="btn-secondary text-xs" onClick={handleBulkDownload} disabled={bulkBusy}>
            {t('config_snapshots.btn_bulk_download')}
          </button>
          {deleteConfirm ? (
            <>
              <button type="button" className="btn-danger text-xs" onClick={handleBulkDelete} disabled={bulkBusy}>
                {bulkBusy ? t('common.saving') : t('common.confirm')}
              </button>
              <button type="button" className="btn-secondary text-xs" onClick={() => setDeleteConfirm(false)}>{t('common.cancel')}</button>
            </>
          ) : (
            <button type="button" className="btn-table-danger text-xs" onClick={() => setDeleteConfirm(true)}>
              {t('config_snapshots.btn_bulk_delete')}
            </button>
          )}
          {bulkError && <span className="text-xs text-red-500 ml-2">{bulkError}</span>}
        </div>
      )}

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
        <p className="text-sm text-gray-400 dark:text-zinc-500 py-6 text-center">{t('config_snapshots.empty_node')}</p>
      )}

      {/* Table */}
      {list.length > 0 && (
        <div className="overflow-x-auto rounded-md border border-gray-200 dark:border-zinc-700">
          <table className="w-full text-xs">
            <thead className="text-gray-500 dark:text-zinc-400 bg-gray-50 dark:bg-zinc-800/60">
              <tr>
                <th className="px-3 py-2 w-8">
                  <input type="checkbox" checked={allSelected} onChange={toggleAll} />
                </th>
                {isMultiNode && <th className="px-3 py-2 text-left font-medium">{t('config_snapshots.col_node')}</th>}
                <th className="px-3 py-2 text-left font-medium">VM/LXC</th>
                <th className="px-3 py-2 text-left font-medium">{t('config_snapshots.col_name')}</th>
                <th className="px-3 py-2 text-left font-medium">{t('config_snapshots.col_note')}</th>
                <th className="px-3 py-2 text-left font-medium">{t('config_snapshots.col_created')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-zinc-800">
              {list.map(snap => (
                <tr key={snap.id} className={`hover:bg-gray-50 dark:hover:bg-zinc-800/30 ${selected.has(snap.id) ? 'bg-orange-50 dark:bg-orange-900/10' : ''}`}>
                  <td className="px-3 py-2">
                    <input type="checkbox" checked={selected.has(snap.id)} onChange={() => toggleOne(snap.id)} />
                  </td>
                  {isMultiNode && <td className="px-3 py-2 text-gray-500 dark:text-zinc-500 whitespace-nowrap">{snap.proxmox_node}</td>}
                  <td className="px-3 py-2 font-mono text-gray-600 dark:text-zinc-400 whitespace-nowrap">
                    <span className="uppercase text-[10px] mr-1">{snap.kind}</span>{snap.vmid}
                  </td>
                  <td className="px-3 py-2 text-gray-700 dark:text-zinc-300 max-w-[160px] truncate" title={snap.name}>{snap.name}</td>
                  <td className="px-3 py-2 text-gray-600 dark:text-zinc-400 max-w-[160px] truncate" title={snap.note}>{snap.note || '—'}</td>
                  <td className="px-3 py-2 text-gray-500 dark:text-zinc-500 whitespace-nowrap">{formatDate(snap.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
