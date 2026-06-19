// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-75: Installations-Banner als Überschrift je Wurzel-Block (AC-MI-2).
import { useTranslation } from 'react-i18next'

export default function InstallationBanner({ data }) {
  const { t } = useTranslation()
  return (
    <div className="flex items-center gap-2 pointer-events-none select-none">
      <span className="text-[11px] font-semibold uppercase tracking-wide text-gray-500 dark:text-zinc-400">
        {t('topology.installation')}: {data.name}
      </span>
      {data.unreachable && (
        <span className="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium bg-portal-danger/15 text-portal-danger">
          {t('topology.unreachable')}
        </span>
      )}
    </div>
  )
}
