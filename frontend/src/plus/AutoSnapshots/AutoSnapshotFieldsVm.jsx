// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-77: Felder für ``auto_vm_snapshot`` (Proxmox-native qm/pct snapshot).
// Eigenständig: include_ram + Retention/GFS (via AutoSnapshotFieldsBase).
import { useTranslation } from 'react-i18next'
import AutoSnapshotFieldsBase from './AutoSnapshotFieldsBase'

export default function AutoSnapshotFieldsVm({ values, onChange }) {
  const { t } = useTranslation()

  return (
    <div className="space-y-4">
      <AutoSnapshotFieldsBase values={values} onChange={onChange} />

      <div className="flex items-center gap-2 border-t border-gray-100 dark:border-zinc-800 pt-3">
        <input
          id="as-include-ram"
          type="checkbox"
          checked={!!values.include_ram}
          onChange={(e) => onChange({ ...values, include_ram: e.target.checked })}
          className="w-4 h-4 rounded border-gray-300 dark:border-zinc-600 text-orange-500 focus:ring-orange-500"
        />
        <label htmlFor="as-include-ram" className="text-sm text-gray-700 dark:text-zinc-300">
          {t('auto_snapshots.vm.include_ram')}
        </label>
      </div>
      <p className="text-[11px] text-gray-400 dark:text-zinc-500 pl-6">
        {t('auto_snapshots.vm.include_ram_hint')}
      </p>
    </div>
  )
}
