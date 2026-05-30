// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-77: Gemeinsame Retention- und Parallelism-Felder beider Auto-Snapshot-Types.
import { useTranslation } from 'react-i18next'

const inputCls = 'w-full text-sm border border-gray-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-gray-900 dark:text-zinc-100 px-3 py-2 rounded focus:outline-none focus:ring-1 focus:ring-orange-500 placeholder-gray-400 dark:placeholder-zinc-500'

export default function AutoSnapshotFieldsBase({ values, onChange }) {
  const { t } = useTranslation()

  const update = (key, val) => onChange({ ...values, [key]: val })

  const handleGfsToggle = (checked) => {
    if (checked && values.keep_daily === 0 && values.keep_weekly === 0 && values.keep_monthly === 0) {
      // Standardvorschlag 7/4/12 wenn GFS erstmalig aktiviert (AC-RET-2)
      onChange({
        ...values,
        gfs_enabled: true,
        keep_daily: 7,
        keep_weekly: 4,
        keep_monthly: 12,
      })
    } else {
      onChange({ ...values, gfs_enabled: checked })
    }
  }

  return (
    <div className="space-y-4 border-t border-gray-100 dark:border-zinc-800 pt-3">
      <p className="text-xs font-medium text-gray-500 dark:text-zinc-400 uppercase tracking-wider">
        {t('auto_snapshots.retention.title')}
      </p>

      {/* keep_last */}
      <div>
        <label htmlFor="as-keep-last" className="block text-xs font-medium text-gray-700 dark:text-zinc-300 mb-1">
          {t('auto_snapshots.retention.keep_last')} <span className="text-red-500">*</span>
        </label>
        <input
          id="as-keep-last"
          type="number"
          min={1}
          max={100}
          value={values.keep_last ?? 7}
          onChange={(e) => update('keep_last', Math.max(1, Math.min(100, parseInt(e.target.value, 10) || 1)))}
          className={inputCls}
        />
        <p className="mt-1 text-[11px] text-gray-400 dark:text-zinc-500">
          {t('auto_snapshots.retention.keep_last_hint')}
        </p>
      </div>

      {/* GFS-Toggle */}
      <div className="flex items-center gap-2">
        <input
          id="as-gfs-toggle"
          type="checkbox"
          checked={!!values.gfs_enabled}
          onChange={(e) => handleGfsToggle(e.target.checked)}
          className="w-4 h-4 rounded border-gray-300 dark:border-zinc-600 text-orange-500 focus:ring-orange-500"
        />
        <label htmlFor="as-gfs-toggle" className="text-sm text-gray-700 dark:text-zinc-300">
          {t('auto_snapshots.retention.gfs.enable')}
        </label>
      </div>

      {/* GFS-Felder */}
      {values.gfs_enabled && (
        <div className="grid grid-cols-3 gap-3 pl-6">
          <div>
            <label htmlFor="as-gfs-daily" className="block text-xs font-medium text-gray-700 dark:text-zinc-300 mb-1">
              {t('auto_snapshots.retention.gfs.daily')}
            </label>
            <input
              id="as-gfs-daily"
              type="number"
              min={0}
              max={100}
              value={values.keep_daily ?? 0}
              onChange={(e) => update('keep_daily', Math.max(0, Math.min(100, parseInt(e.target.value, 10) || 0)))}
              className={inputCls}
            />
          </div>
          <div>
            <label htmlFor="as-gfs-weekly" className="block text-xs font-medium text-gray-700 dark:text-zinc-300 mb-1">
              {t('auto_snapshots.retention.gfs.weekly')}
            </label>
            <input
              id="as-gfs-weekly"
              type="number"
              min={0}
              max={100}
              value={values.keep_weekly ?? 0}
              onChange={(e) => update('keep_weekly', Math.max(0, Math.min(100, parseInt(e.target.value, 10) || 0)))}
              className={inputCls}
            />
          </div>
          <div>
            <label htmlFor="as-gfs-monthly" className="block text-xs font-medium text-gray-700 dark:text-zinc-300 mb-1">
              {t('auto_snapshots.retention.gfs.monthly')}
            </label>
            <input
              id="as-gfs-monthly"
              type="number"
              min={0}
              max={100}
              value={values.keep_monthly ?? 0}
              onChange={(e) => update('keep_monthly', Math.max(0, Math.min(100, parseInt(e.target.value, 10) || 0)))}
              className={inputCls}
            />
          </div>
        </div>
      )}

      {/* Parallelism */}
      <div>
        <label htmlFor="as-max-parallel" className="block text-xs font-medium text-gray-700 dark:text-zinc-300 mb-1">
          {t('auto_snapshots.vm.max_parallel')}
        </label>
        <input
          id="as-max-parallel"
          type="number"
          min={1}
          max={10}
          value={values.max_parallel ?? 5}
          onChange={(e) => update('max_parallel', Math.max(1, Math.min(10, parseInt(e.target.value, 10) || 1)))}
          className={inputCls}
        />
        <p className="mt-1 text-[11px] text-gray-400 dark:text-zinc-500">
          {t('auto_snapshots.vm.max_parallel_hint')}
        </p>
      </div>
    </div>
  )
}
