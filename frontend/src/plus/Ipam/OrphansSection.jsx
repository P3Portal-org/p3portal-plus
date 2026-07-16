// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-42 Phase 2: verwaiste Allocations (VM außerhalb P3 verschwunden → orphaned).
// Einzeln oder gesammelt freigeben (US-9). Muster PROJ-96 OrphanDependenciesTab.
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { formatApiError } from '../../api/errors'
import ConfirmModal from '../../components/common/ConfirmModal'
import { useOrphans, useReleaseOrphans } from './hooks'
import { StatusBadge } from './helpers'

export default function OrphansSection({ pools }) {
  const { t } = useTranslation()
  const { data: orphans, isLoading, isError, error } = useOrphans()
  const releaseMut = useReleaseOrphans()
  const [confirmAll, setConfirmAll] = useState(false)
  const [err, setErr] = useState('')

  const poolCidr = (poolId) => (pools || []).find((p) => p.id === poolId)?.cidr || `#${poolId}`
  const rows = orphans || []

  const releaseOne = async (id) => {
    setErr('')
    try {
      await releaseMut.mutateAsync([id])
    } catch (e) {
      setErr(formatApiError(e, t('common.error_generic')))
    }
  }

  const releaseAll = async () => {
    setErr('')
    try {
      await releaseMut.mutateAsync([]) // leer = alle
    } finally {
      setConfirmAll(false)
    }
  }

  return (
    <div className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-700 rounded-lg p-4">
      <div className="flex items-center justify-between gap-2 mb-3">
        <div>
          <h3 className="text-sm font-semibold text-gray-900 dark:text-zinc-100">
            {t('ipam.orphans.title')}
          </h3>
          <p className="text-[11px] text-portal-text2 mt-0.5">{t('ipam.orphans.hint')}</p>
        </div>
        {rows.length > 0 && (
          <button
            type="button"
            onClick={() => setConfirmAll(true)}
            disabled={releaseMut.isPending}
            className="btn-table-danger"
          >
            {t('ipam.orphans.release_all')}
          </button>
        )}
      </div>

      {err && <p className="text-xs text-portal-danger mb-2">{err}</p>}

      {isLoading ? (
        <p className="text-xs text-gray-400 dark:text-zinc-500">{t('common.loading')}</p>
      ) : isError ? (
        <p className="text-xs text-portal-danger">{formatApiError(error, t('common.error_generic'))}</p>
      ) : rows.length === 0 ? (
        <p className="text-xs text-gray-400 dark:text-zinc-500 italic">{t('ipam.orphans.empty')}</p>
      ) : (
        <ul>
          {rows.map((a) => (
            <li
              key={a.id}
              className="flex items-center gap-2 py-1.5 border-b border-gray-100 dark:border-zinc-800 last:border-0"
            >
              <span className="font-mono text-xs text-gray-900 dark:text-zinc-100">{a.ip}</span>
              <StatusBadge status={a.status} t={t} />
              <span className="text-[11px] text-portal-text2 truncate">
                {poolCidr(a.pool_id)}
                {a.vmid != null && ` · VMID ${a.vmid}`}
                {a.owner_username && ` · ${a.owner_username}`}
              </span>
              <button
                type="button"
                onClick={() => releaseOne(a.id)}
                disabled={releaseMut.isPending}
                className="btn-table-danger ml-auto shrink-0"
              >
                {t('ipam.orphans.release')}
              </button>
            </li>
          ))}
        </ul>
      )}

      {confirmAll && (
        <ConfirmModal
          title={t('ipam.orphans.release_all')}
          body={t('ipam.orphans.release_all_confirm', { count: rows.length })}
          confirmLabel={t('ipam.orphans.release')}
          variant="danger"
          onConfirm={releaseAll}
          onClose={() => setConfirmAll(false)}
        />
      )}
    </div>
  )
}
