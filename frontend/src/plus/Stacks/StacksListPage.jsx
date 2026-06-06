// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-76 Phase 1: Stacks-Übersichtsseite /stacks (AC-UI-1).
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../hooks/useAuth'
import { useCapability } from '../../hooks/useCapability'
import { formatApiError } from '../../api/errors'
import ConfirmModal from '../../components/common/ConfirmModal'
import PlusBadge from '../../components/common/PlusBadge'
import Watermark from '../../components/common/Watermark'
import DeploymentStateBadge from './DeploymentStateBadge'
import { useStacks, useDeleteStack } from './hooks'

function StatusBadge({ status, t }) {
  const cls = status === 'active'
    ? 'bg-portal-success/15 text-portal-success'
    : 'bg-portal-bg3 text-portal-text2'
  return <span className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${cls}`}>{t(`stacks.status.${status}`, status)}</span>
}

export default function StacksListPage() {
  const { t } = useTranslation()
  const canUseStacks = useCapability('stacks')
  const navigate = useNavigate()
  const { role } = useAuth()
  const isAdmin = role === 'admin'

  const [q, setQ] = useState('')
  const [includeDeleted, setIncludeDeleted] = useState(false)
  const { data, isLoading, error } = useStacks({ q: q || undefined, includeDeleted: includeDeleted && isAdmin })
  const delMut = useDeleteStack()

  const [confirmDel, setConfirmDel] = useState(null)  // stack row
  const [pendingMsg, setPendingMsg] = useState(null)

  const stacks = data ?? []

  const handleDelete = async () => {
    const res = await delMut.mutateAsync(confirmDel.id)
    if (res?.kind === 'pending') {
      setPendingMsg(t('stacks.approval.delete_pending', { name: confirmDel.name }))
    }
  }

  if (!canUseStacks) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <p className="text-sm text-portal-text2">{t('stacks.not_available')}</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col flex-1 min-h-0">
      <header className="h-12 flex items-center justify-between px-6 border-b border-gray-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 shrink-0">
        <div className="flex items-center gap-2">
          <h1 className="text-sm font-semibold text-gray-900 dark:text-zinc-100">{t('stacks.title')}</h1>
          <PlusBadge />
        </div>
        <button onClick={() => navigate('/stacks/new')} className="btn-primary">
          + {t('stacks.create_btn')}
        </button>
      </header>
      <main className="flex-1 overflow-y-auto px-6 py-6 space-y-4 bg-transparent">
        <p className="text-sm text-portal-text2">{t('stacks.subtitle')}</p>

        {/* Filter */}
        <div className="flex items-center gap-3 flex-wrap">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={t('stacks.search_ph')}
            className="px-3 py-1.5 text-sm rounded-md border border-portal-border bg-portal-bg2 text-portal-text focus:outline-none focus:ring-1 focus:ring-portal-accent w-64"
          />
          {isAdmin && (
            <label className="flex items-center gap-2 text-xs text-portal-text2">
              <input type="checkbox" checked={includeDeleted} onChange={(e) => setIncludeDeleted(e.target.checked)} className="accent-[var(--accent)]" />
              {t('stacks.show_deleted')}
            </label>
          )}
        </div>

        {pendingMsg && (
          <div className="rounded-md border border-portal-warn/40 bg-portal-warn/10 p-3 text-xs text-portal-warn">{pendingMsg}</div>
        )}

        <div className="bg-white dark:bg-zinc-900 rounded-lg border border-gray-200 dark:border-zinc-700 overflow-hidden">
          {isLoading ? (
            <p className="p-5 text-sm text-portal-text2">{t('common.loading')}</p>
          ) : error ? (
            <p className="p-5 text-sm text-portal-danger">{formatApiError(error, t('common.error_generic'))}</p>
          ) : stacks.length === 0 ? (
            <div className="p-8 text-center">
              <p className="text-sm text-portal-text2">{t('stacks.empty_state')}</p>
              <button onClick={() => navigate('/stacks/new')} className="btn-primary mt-3">+ {t('stacks.create_btn')}</button>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-portal-text3 border-b border-portal-border text-left">
                  <th className="px-4 py-2.5 font-medium">{t('stacks.col.name')}</th>
                  <th className="px-4 py-2.5 font-medium">{t('stacks.col.version')}</th>
                  <th className="px-4 py-2.5 font-medium">{t('stacks.col.status')}</th>
                  <th className="px-4 py-2.5 font-medium">{t('stacks.col.deployment')}</th>
                  <th className="px-4 py-2.5 font-medium">{t('stacks.col.resources')}</th>
                  <th className="px-4 py-2.5 font-medium">{t('stacks.col.owner')}</th>
                  <th className="px-4 py-2.5 font-medium">{t('stacks.col.updated')}</th>
                  <th className="px-4 py-2.5 font-medium text-right">{t('stacks.col.actions')}</th>
                </tr>
              </thead>
              <tbody>
                {stacks.map((s) => (
                  <tr
                    key={s.id}
                    className="group border-b border-portal-border/50 hover:bg-portal-bg3/40 cursor-pointer"
                    onClick={() => navigate(`/stacks/${s.id}`)}
                  >
                    <td className="px-4 py-2.5 font-medium text-portal-text group-hover:text-portal-accent">
                      {s.name}
                      {s.is_orphan && <span className="ml-2 text-[10px] uppercase text-portal-warn">{t('stacks.orphan_badge')}</span>}
                    </td>
                    <td className="px-4 py-2.5 text-portal-text2">{s.version}</td>
                    <td className="px-4 py-2.5"><StatusBadge status={s.status} t={t} /></td>
                    <td className="px-4 py-2.5">{s.deployment_state ? <DeploymentStateBadge state={s.deployment_state} /> : <span className="text-portal-text3 text-xs">—</span>}</td>
                    <td className="px-4 py-2.5 text-portal-text2">{s.resource_count}</td>
                    <td className="px-4 py-2.5 text-portal-text2">{s.owner_username || (s.owner_user_id ? `#${s.owner_user_id}` : '—')}</td>
                    <td className="px-4 py-2.5 text-portal-text3 text-xs">{(s.updated_at || '').replace('T', ' ').slice(0, 16)}</td>
                    <td className="px-4 py-2.5 text-right whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
                      <button onClick={() => navigate(`/stacks/${s.id}/edit`)} className="btn-table">{t('common.edit')}</button>
                      <button onClick={() => setConfirmDel(s)} className="btn-table-danger ml-1">{t('common.delete')}</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <Watermark />
      </main>

      {confirmDel && (
        <ConfirmModal
          title={t('stacks.delete_confirm_title')}
          body={t('stacks.delete_confirm_body', { name: confirmDel.name })}
          confirmLabel={t('common.delete')}
          variant="danger"
          onConfirm={handleDelete}
          onClose={() => setConfirmDel(null)}
        />
      )}
    </div>
  )
}
