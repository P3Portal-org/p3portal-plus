// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-76 Phase 1: „Verwaiste Stacks"-Tab in System Settings (AC-UI-16, AC-API-14/15/16).
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchUsers } from '../../api/admin'
import { formatApiError } from '../../api/errors'
import ConfirmModal from '../../components/common/ConfirmModal'
import { useOrphanStacks, useReassignOrphan, usePurgeOrphan } from './hooks'

function ReassignRow({ orphan, users, onReassign }) {
  const { t } = useTranslation()
  const [userId, setUserId] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  const submit = async () => {
    if (!userId) return
    setBusy(true); setErr(null)
    try {
      await onReassign(orphan.id, Number(userId))
    } catch (e) {
      setErr(formatApiError(e, t('common.error_generic')))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex items-center gap-2">
      <select
        value={userId}
        onChange={(e) => setUserId(e.target.value)}
        className="px-2 py-1 text-xs rounded-md border border-portal-border bg-portal-bg2 text-portal-text"
      >
        <option value="">{t('stacks.orphans.select_owner')}</option>
        {users.map((u) => <option key={u.id} value={u.id}>{u.username}</option>)}
      </select>
      <button onClick={submit} disabled={busy || !userId} className="btn-table disabled:opacity-40">
        {t('stacks.orphans.reassign_btn')}
      </button>
      {err && <span className="text-xs text-portal-danger">{err}</span>}
    </div>
  )
}

export default function OrphanStacksTab() {
  const { t } = useTranslation()
  const { data, isLoading, error } = useOrphanStacks()
  const reassignMut = useReassignOrphan()
  const purgeMut = usePurgeOrphan()
  const [users, setUsers] = useState([])
  const [confirmPurge, setConfirmPurge] = useState(null)

  const orphans = data ?? []

  useEffect(() => {
    fetchUsers().then((rows) => setUsers((rows || []).filter((u) => u.auth_type === 'local' || !u.auth_type))).catch(() => {})
  }, [])

  return (
    <div className="space-y-3">
      <div>
        <h3 className="text-sm font-semibold text-gray-900 dark:text-zinc-100">{t('stacks.orphans.title')}</h3>
        <p className="text-xs text-portal-text2 mt-0.5">{t('stacks.orphans.subtitle')}</p>
      </div>

      {isLoading ? (
        <p className="text-sm text-portal-text2">{t('common.loading')}</p>
      ) : error ? (
        <p className="text-sm text-portal-danger">{formatApiError(error, t('common.error_generic'))}</p>
      ) : orphans.length === 0 ? (
        <p className="text-sm text-portal-text3 italic">{t('stacks.orphans.empty')}</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-portal-text3 border-b border-portal-border text-left">
              <th className="px-3 py-2 font-medium">{t('stacks.col.name')}</th>
              <th className="px-3 py-2 font-medium">{t('stacks.col.resources')}</th>
              <th className="px-3 py-2 font-medium">{t('stacks.orphans.col_orphaned_at')}</th>
              <th className="px-3 py-2 font-medium">{t('stacks.orphans.col_ex_owner')}</th>
              <th className="px-3 py-2 font-medium text-right">{t('stacks.col.actions')}</th>
            </tr>
          </thead>
          <tbody>
            {orphans.map((o) => (
              <tr key={o.id} className="border-b border-portal-border/50">
                <td className="px-3 py-2 font-medium text-portal-text">{o.name}</td>
                <td className="px-3 py-2 text-portal-text2">{o.resource_count}</td>
                <td className="px-3 py-2 text-portal-text3 text-xs">{(o.orphaned_at || '').replace('T', ' ').slice(0, 16)}</td>
                <td className="px-3 py-2 text-portal-text2">{o.ex_owner_user_id ? `#${o.ex_owner_user_id}` : '—'}</td>
                <td className="px-3 py-2">
                  <div className="flex items-center justify-end gap-2">
                    <ReassignRow orphan={o} users={users} onReassign={(id, uid) => reassignMut.mutateAsync({ id, ownerUserId: uid })} />
                    <button onClick={() => setConfirmPurge(o)} className="btn-table-danger">{t('stacks.orphans.purge_btn')}</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {confirmPurge && (
        <ConfirmModal
          title={t('stacks.orphans.purge_confirm_title')}
          body={t('stacks.orphans.purge_confirm_body', { name: confirmPurge.name })}
          confirmLabel={t('stacks.orphans.purge_btn')}
          variant="danger"
          onConfirm={() => purgeMut.mutateAsync(confirmPurge.id)}
          onClose={() => setConfirmPurge(null)}
        />
      )}
    </div>
  )
}
