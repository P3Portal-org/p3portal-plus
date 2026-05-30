// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-77: Badge "auto" mit Klick-Navigation auf den verantwortlichen Scheduled-Job
// (AC-UI-4 + AC-UI-5). Wird in PROJ-74 ConfigSnapshotsTab und PROJ-29
// VmSnapshotSection eingebettet.
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

export default function AutoBadge({ jobId }) {
  const navigate = useNavigate()
  const { t } = useTranslation()

  const handleClick = (e) => {
    e.stopPropagation()
    if (!jobId) return
    navigate(`/automation?tab=scheduled&openJob=${jobId}`)
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      title={t('auto_snapshots.badge.tooltip')}
      className="inline-flex items-center gap-1 text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded bg-portal-info/10 text-portal-info border border-portal-info/30 hover:bg-portal-info/20 transition-colors"
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="w-2.5 h-2.5">
        <circle cx="12" cy="12" r="10" />
        <polyline points="12 6 12 12 16 14" />
      </svg>
      {t('auto_snapshots.badge.auto')}
    </button>
  )
}
