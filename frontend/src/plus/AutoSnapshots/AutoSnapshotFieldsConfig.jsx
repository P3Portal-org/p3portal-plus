// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-77: Felder für ``auto_config_snapshot`` (PROJ-74 Config-Snapshot).
// Eigenständig: skip_if_no_changes + Retention/GFS (via AutoSnapshotFieldsBase).
import { useTranslation } from 'react-i18next'
import AutoSnapshotFieldsBase from './AutoSnapshotFieldsBase'

export default function AutoSnapshotFieldsConfig({ values, onChange }) {
  const { t } = useTranslation()

  return (
    <div className="space-y-4">
      <AutoSnapshotFieldsBase values={values} onChange={onChange} />

      <div className="flex items-center gap-2 border-t border-gray-100 dark:border-zinc-800 pt-3">
        <input
          id="as-skip-if-no-changes"
          type="checkbox"
          checked={values.skip_if_no_changes !== false}
          onChange={(e) => onChange({ ...values, skip_if_no_changes: e.target.checked })}
          className="w-4 h-4 rounded border-gray-300 dark:border-zinc-600 text-portal-accent focus:ring-portal-accent"
        />
        <label htmlFor="as-skip-if-no-changes" className="text-sm text-gray-700 dark:text-zinc-300">
          {t('auto_snapshots.config.skip_if_no_changes')}
        </label>
      </div>
      <p className="text-[11px] text-gray-400 dark:text-zinc-500 pl-6">
        {t('auto_snapshots.config.skip_if_no_changes_hint')}
      </p>
    </div>
  )
}
