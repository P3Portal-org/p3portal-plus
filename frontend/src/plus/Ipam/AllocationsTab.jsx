// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-42 Phase 2: „Allocations"-Tab (Plus). Pool wählen → Auslastung
// (belegt/frei/gesamt) + Allocation-Liste (IP↔VM, Status) + Fremd-IP manuell
// eintragen + freigeben (US-6). Bindet OrphansSection ein (US-9).
import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { formatApiError } from '../../api/errors'
import ConfirmModal from '../../components/common/ConfirmModal'
import { useIpamPools, usePoolUsage, useAddManualAllocation, useReleaseAllocation } from './hooks'
import { poolLabel, StatusBadge } from './helpers'
import OrphansSection from './OrphansSection'

const inputCls =
  'h-8 rounded-md border border-gray-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-2 text-xs text-gray-700 dark:text-zinc-200 focus:outline-none focus:border-portal-accent'

function UsageBar({ used, total }) {
  const pct = total > 0 ? Math.min(100, Math.round((used / total) * 100)) : 0
  const cls = pct >= 90 ? 'bg-portal-danger' : pct >= 70 ? 'bg-portal-warn' : 'bg-portal-accent'
  return (
    <div className="h-2 w-full rounded-full bg-gray-200 dark:bg-zinc-800 overflow-hidden">
      <div className={`h-full ${cls}`} style={{ width: `${pct}%` }} />
    </div>
  )
}

export default function AllocationsTab() {
  const { t } = useTranslation()
  const { data: pools, isLoading: poolsLoading } = useIpamPools()
  const [poolId, setPoolId] = useState(null)

  // Ersten Pool automatisch wählen, sobald geladen.
  useEffect(() => {
    if (poolId == null && pools && pools.length > 0) setPoolId(pools[0].id)
  }, [pools, poolId])

  const usage = usePoolUsage(poolId)
  const addMut = useAddManualAllocation()
  const releaseMut = useReleaseAllocation()

  const [manualIp, setManualIp] = useState('')
  const [manualNote, setManualNote] = useState('')
  const [addErr, setAddErr] = useState('')
  const [releaseTarget, setReleaseTarget] = useState(null)

  const allocations = usage.data?.allocations || []

  const submitManual = async () => {
    setAddErr('')
    if (!poolId || !manualIp.trim()) return
    try {
      await addMut.mutateAsync({ poolId, ip: manualIp.trim(), note: manualNote.trim() || null })
      setManualIp('')
      setManualNote('')
    } catch (e) {
      if (e?.response?.status === 409) setAddErr(t('ipam.alloc.err_conflict'))
      else if (e?.response?.status === 422) setAddErr(t('ipam.alloc.err_invalid'))
      else setAddErr(formatApiError(e, t('common.error_generic')))
    }
  }

  const confirmRelease = async () => {
    if (!releaseTarget) return
    try {
      await releaseMut.mutateAsync(releaseTarget.id)
    } finally {
      setReleaseTarget(null)
    }
  }

  if (poolsLoading) {
    return <p className="text-sm text-gray-400 dark:text-zinc-500 py-4">{t('common.loading')}</p>
  }
  if (!pools || pools.length === 0) {
    return (
      <p className="text-sm text-gray-400 dark:text-zinc-500 py-8 text-center">
        {t('ipam.alloc.no_pools')}
      </p>
    )
  }

  return (
    <div className="space-y-4">
      {/* Pool-Auswahl + Auslastung */}
      <div className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-700 rounded-lg p-4">
        <div className="flex flex-wrap items-center gap-3 mb-3">
          <label className="text-xs font-medium text-gray-700 dark:text-zinc-300">
            {t('ipam.alloc.pool_label')}
          </label>
          <select
            value={poolId ?? ''}
            onChange={(e) => setPoolId(Number(e.target.value))}
            className={`${inputCls} min-w-[16rem]`}
          >
            {pools.map((p) => (
              <option key={p.id} value={p.id}>{poolLabel(p, t)}</option>
            ))}
          </select>
        </div>

        {usage.isLoading ? (
          <p className="text-xs text-gray-400 dark:text-zinc-500">{t('common.loading')}</p>
        ) : usage.isError ? (
          <p className="text-xs text-portal-danger">{formatApiError(usage.error, t('common.error_generic'))}</p>
        ) : (
          <div className="space-y-2">
            <div className="flex items-center gap-4 text-xs text-gray-600 dark:text-zinc-400 tabular-nums">
              <span>{t('ipam.alloc.used')}: <b className="text-gray-900 dark:text-zinc-100">{usage.data?.used ?? 0}</b></span>
              <span>{t('ipam.alloc.free')}: <b className="text-gray-900 dark:text-zinc-100">{usage.data?.free ?? 0}</b></span>
              <span>{t('ipam.alloc.total')}: <b className="text-gray-900 dark:text-zinc-100">{usage.data?.total ?? 0}</b></span>
            </div>
            <UsageBar used={usage.data?.used ?? 0} total={usage.data?.total ?? 0} />
          </div>
        )}
      </div>

      {/* Allocation-Liste */}
      <div className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-700 rounded-lg p-4">
        <h3 className="text-sm font-semibold text-gray-900 dark:text-zinc-100 mb-3">
          {t('ipam.alloc.list_title')}
        </h3>
        {allocations.length === 0 ? (
          <p className="text-xs text-gray-400 dark:text-zinc-500 italic">{t('ipam.alloc.empty')}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-wide text-gray-500 dark:text-zinc-400">
                  <th className="py-1.5 pr-3 font-semibold">{t('ipam.alloc.col_ip')}</th>
                  <th className="py-1.5 pr-3 font-semibold">{t('ipam.alloc.col_status')}</th>
                  <th className="py-1.5 pr-3 font-semibold">{t('ipam.alloc.col_source')}</th>
                  <th className="py-1.5 pr-3 font-semibold">{t('ipam.alloc.col_vm')}</th>
                  <th className="py-1.5 pr-3 font-semibold">{t('ipam.alloc.col_owner')}</th>
                  <th className="py-1.5 font-semibold text-right">{t('ipam.alloc.col_actions')}</th>
                </tr>
              </thead>
              <tbody>
                {allocations.map((a) => (
                  <tr key={a.id} className="border-t border-gray-100 dark:border-zinc-800">
                    <td className="py-1.5 pr-3 font-mono text-gray-900 dark:text-zinc-100">{a.ip}</td>
                    <td className="py-1.5 pr-3"><StatusBadge status={a.status} t={t} /></td>
                    <td className="py-1.5 pr-3 text-portal-text2">{t(`ipam.alloc.source_${a.source}`)}</td>
                    <td className="py-1.5 pr-3 text-portal-text2 tabular-nums">{a.vmid ?? '–'}</td>
                    <td className="py-1.5 pr-3 text-portal-text2 truncate">{a.owner_username || '–'}</td>
                    <td className="py-1.5 text-right">
                      <button
                        type="button"
                        onClick={() => setReleaseTarget(a)}
                        disabled={releaseMut.isPending}
                        className="btn-table-danger"
                      >
                        {t('ipam.alloc.release')}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Fremd-IP manuell eintragen */}
        <div className="mt-4 pt-3 border-t border-gray-100 dark:border-zinc-800">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-500 dark:text-zinc-400 mb-2">
            {t('ipam.alloc.manual_title')}
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <input
              value={manualIp}
              onChange={(e) => setManualIp(e.target.value)}
              placeholder={t('ipam.alloc.manual_ip_ph')}
              className={`${inputCls} w-40`}
            />
            <input
              value={manualNote}
              onChange={(e) => setManualNote(e.target.value)}
              placeholder={t('ipam.alloc.manual_note_ph')}
              maxLength={500}
              className={`${inputCls} flex-1 min-w-[10rem]`}
            />
            <button
              type="button"
              onClick={submitManual}
              disabled={!manualIp.trim() || addMut.isPending}
              className="btn-primary text-xs"
            >
              {addMut.isPending ? '…' : t('ipam.alloc.manual_add')}
            </button>
          </div>
          {addErr && <p className="text-[11px] text-portal-danger mt-1">{addErr}</p>}
          <p className="text-[11px] text-portal-text2 mt-1">{t('ipam.alloc.manual_hint')}</p>
        </div>
      </div>

      {/* Verwaiste Allocations */}
      <OrphansSection pools={pools} />

      {releaseTarget && (
        <ConfirmModal
          title={t('ipam.alloc.release_title')}
          body={t('ipam.alloc.release_confirm', { ip: releaseTarget.ip })}
          confirmLabel={t('ipam.alloc.release')}
          variant="danger"
          onConfirm={confirmRelease}
          onClose={() => setReleaseTarget(null)}
        />
      )}
    </div>
  )
}
