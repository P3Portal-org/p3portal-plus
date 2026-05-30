// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-77: Per-VM-Detail-Tabelle für einen Auto-Snapshot-Run (AC-UI-6).
// Wird im ScheduledJobDetailModal aufklappbar pro Run-History-Eintrag genutzt.
import { useTranslation } from 'react-i18next'
import { useRunDetails } from './hooks'

const STATUS_BADGE = {
  created:            { i18n: 'auto_snapshots.run_entry.created',     cls: 'bg-portal-success/10 text-portal-success border-portal-success/30' },
  rotated_only:       { i18n: 'auto_snapshots.run_entry.rotated',     cls: 'bg-gray-100 dark:bg-zinc-800 text-gray-600 dark:text-zinc-300 border-gray-200 dark:border-zinc-700' },
  skipped_no_change:  { i18n: 'auto_snapshots.run_entry.skipped_no_change', cls: 'bg-portal-info/10 text-portal-info border-portal-info/30' },
  skipped_locked:     { i18n: 'auto_snapshots.run_entry.skipped_locked',    cls: 'bg-portal-warn/10 text-portal-warn border-portal-warn/30' },
  skipped_not_owner:  { i18n: 'auto_snapshots.run_entry.skipped_not_owner', cls: 'bg-portal-warn/10 text-portal-warn border-portal-warn/30' },
  failed:             { i18n: 'auto_snapshots.run_entry.failed',      cls: 'bg-portal-danger/10 text-portal-danger border-portal-danger/30' },
}

export default function RunDetailsTable({ runId }) {
  const { t } = useTranslation()
  const { data, isLoading, error } = useRunDetails(runId)

  if (isLoading) {
    return <p className="text-xs text-gray-500 dark:text-zinc-400">{t('common.loading')}</p>
  }
  if (error) {
    return <p className="text-xs text-red-500">{error?.response?.data?.detail ?? t('common.error_generic')}</p>
  }
  if (!data) return null

  const summary = data.summary ?? {}
  const entries = data.entries ?? []

  return (
    <div className="space-y-3">
      {/* Summary-Block */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
        <SummaryStat label={t('auto_snapshots.runs.summary.total')}        value={summary.targets_total ?? 0} />
        <SummaryStat label={t('auto_snapshots.runs.summary.created')}      value={summary.created_count ?? 0} tone="success" />
        <SummaryStat label={t('auto_snapshots.runs.summary.failed')}       value={summary.failed_count ?? 0} tone={summary.failed_count > 0 ? 'danger' : null} />
        <SummaryStat label={t('auto_snapshots.runs.summary.rotated')}      value={summary.rotated_count ?? 0} />
        <SummaryStat label={t('auto_snapshots.runs.summary.skipped_nochg')} value={summary.skipped_no_change_count ?? 0} />
        <SummaryStat label={t('auto_snapshots.runs.summary.skipped_lock')}  value={summary.skipped_locked_count ?? 0} tone={summary.skipped_locked_count > 0 ? 'warn' : null} />
        <SummaryStat label={t('auto_snapshots.runs.summary.skipped_owner')} value={summary.skipped_not_owner_count ?? 0} tone={summary.skipped_not_owner_count > 0 ? 'warn' : null} />
        <SummaryStat label={t('auto_snapshots.runs.summary.status')}        value={t(`auto_snapshots.runs.status.${summary.status ?? 'failed'}`)} />
      </div>

      {/* Per-VM-Tabelle */}
      {entries.length > 0 ? (
        <div className="overflow-x-auto rounded border border-gray-200 dark:border-zinc-700">
          <table className="w-full text-xs">
            <thead className="text-gray-500 dark:text-zinc-400 bg-gray-50 dark:bg-zinc-800/60">
              <tr>
                <th className="px-2 py-1.5 text-left font-medium">{t('auto_snapshots.runs.col.node')}</th>
                <th className="px-2 py-1.5 text-left font-medium">{t('auto_snapshots.runs.col.vmid')}</th>
                <th className="px-2 py-1.5 text-left font-medium">{t('auto_snapshots.runs.col.kind')}</th>
                <th className="px-2 py-1.5 text-left font-medium">{t('auto_snapshots.runs.col.status')}</th>
                <th className="px-2 py-1.5 text-left font-medium">{t('auto_snapshots.runs.col.snapname')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-zinc-800">
              {entries.map((e, i) => {
                const meta = STATUS_BADGE[e.status] ?? STATUS_BADGE.failed
                return (
                  <tr key={`${e.snapshot_id ?? e.vmid}-${i}`} className="hover:bg-gray-50 dark:hover:bg-zinc-800/30">
                    <td className="px-2 py-1.5 text-gray-700 dark:text-zinc-300">{e.proxmox_node}</td>
                    <td className="px-2 py-1.5 font-mono text-gray-700 dark:text-zinc-300">{e.vmid}</td>
                    <td className="px-2 py-1.5">
                      <span className={`text-[10px] uppercase px-1 rounded ${e.kind === 'lxc' ? 'bg-purple-100 dark:bg-purple-900/40 text-purple-700 dark:text-purple-300' : 'bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300'}`}>
                        {e.kind}
                      </span>
                    </td>
                    <td className="px-2 py-1.5">
                      <span className={`text-[10px] font-medium uppercase px-1.5 py-0.5 rounded border ${meta.cls}`}>
                        {t(meta.i18n)}
                      </span>
                    </td>
                    <td className="px-2 py-1.5 font-mono text-gray-600 dark:text-zinc-400 truncate max-w-[260px]" title={e.snapname ?? ''}>
                      {e.snapname ?? '—'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-xs text-gray-400 dark:text-zinc-500 py-4 text-center">
          {t('auto_snapshots.runs.no_entries')}
        </p>
      )}

      {/* Failed-Details (max 100) */}
      {summary.failed_details && summary.failed_details.length > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer text-portal-danger font-medium">
            {t('auto_snapshots.runs.failed_details', { count: summary.failed_details.length })}
          </summary>
          <ul className="mt-2 space-y-0.5 font-mono text-portal-danger/80 max-h-40 overflow-y-auto">
            {summary.failed_details.slice(0, 100).map((d, i) => (
              <li key={i}>
                {d.node} · vmid {d.vmid} · {d.error_class}: {d.error_msg}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}

function SummaryStat({ label, value, tone }) {
  const toneCls = tone === 'success' ? 'text-portal-success'
    : tone === 'danger' ? 'text-portal-danger'
    : tone === 'warn' ? 'text-portal-warn'
    : 'text-gray-900 dark:text-zinc-100'
  return (
    <div className="bg-gray-50 dark:bg-zinc-800/50 rounded px-2 py-1.5">
      <p className="text-[10px] uppercase text-gray-500 dark:text-zinc-400 tracking-wider">{label}</p>
      <p className={`font-semibold ${toneCls}`}>{value}</p>
    </div>
  )
}
