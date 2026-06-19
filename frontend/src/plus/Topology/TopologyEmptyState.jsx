// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-75: Empty-States (gefiltert leer AC-TAB-8 / 0 sichtbare Gäste AC-TAB-9).
import { useTranslation } from 'react-i18next'

export default function TopologyEmptyState({ reason, onResetFilters }) {
  const { t } = useTranslation()
  const filtered = reason === 'filtered'
  const message = reason === 'no_deps'
    ? t('topology.empty.no_deps')
    : filtered ? t('topology.empty.filtered') : t('topology.empty.no_access')
  return (
    <div className="flex flex-col items-center justify-center h-full text-center gap-3 px-6">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.4} className="w-10 h-10 text-gray-300 dark:text-zinc-600">
        <circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" strokeLinecap="round" />
      </svg>
      <p className="text-sm text-gray-500 dark:text-zinc-400 max-w-sm">
        {message}
      </p>
      {filtered && onResetFilters && (
        <button type="button" onClick={onResetFilters} className="btn-secondary text-xs">
          {t('topology.empty.reset_filters')}
        </button>
      )}
    </div>
  )
}
