// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-76 Phase 2b: Deployment-Zustand-Badge (AC-2B-UI-6, AC-2B-DRIFT-3).
import { useTranslation } from 'react-i18next'

// portal-* Theme-Tokens (PROJ-58) — Zerstörung/Fehler = danger, in-sync = success.
const STATE_STYLES = {
  not_deployed: 'bg-portal-bg3 text-portal-text2',
  deploying:    'bg-portal-info/15 text-portal-info',
  deployed:     'bg-portal-success/15 text-portal-success',
  partial:      'bg-portal-warn/15 text-portal-warn',
  destroying:   'bg-portal-info/15 text-portal-info',
  destroyed:    'bg-portal-bg3 text-portal-text2',
  out_of_sync:  'bg-portal-warn/15 text-portal-warn',
  error:        'bg-portal-danger/15 text-portal-danger',
}

const ANIMATED = new Set(['deploying', 'destroying'])

export default function DeploymentStateBadge({ state }) {
  const { t } = useTranslation()
  if (!state) return null
  const cls = STATE_STYLES[state] ?? 'bg-portal-bg3 text-portal-text2'
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium ${cls}`}>
      {ANIMATED.has(state) && (
        <svg className="animate-spin w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
          <path d="M21 12a9 9 0 1 1-6.219-8.56" />
        </svg>
      )}
      {t(`stacks.deploy.state.${state}`, state)}
    </span>
  )
}
