// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-75: Kompakte Status-/Zusatz-Badges am VM/LXC-Knoten (AC-STACK/AC-BADGE).
import { useTranslation } from 'react-i18next'

export function StatusBadge({ status }) {
  const { t } = useTranslation()
  const running = status === 'running'
  const cls = running
    ? 'bg-portal-success/15 text-portal-success'
    : status === 'paused'
    ? 'bg-portal-warn/15 text-portal-warn'
    : 'bg-portal-danger/15 text-portal-danger'
  return (
    <span className={`inline-flex items-center rounded px-1 py-0.5 text-[9px] font-medium ${cls}`}>
      {t(`topology.status.${running ? 'running' : status === 'paused' ? 'paused' : 'stopped'}`)}
    </span>
  )
}

/** Stack-/Ansible-/Template-Badges (kompakt, kollidieren nicht mit Status). */
export function GuestBadges({ guest }) {
  const { t } = useTranslation()
  return (
    <div className="flex flex-wrap items-center gap-1">
      {guest.managed_by_stack && (
        <span
          className="inline-flex items-center gap-0.5 rounded px-1 py-0.5 text-[9px] font-medium bg-portal-accent/15 text-portal-accent max-w-[88px]"
          title={t('topology.badge.stack', { name: guest.managed_by_stack })}
        >
          <span className="truncate">⛓ {guest.managed_by_stack}</span>
        </span>
      )}
      {guest.ssh_managed && (
        <span
          className="inline-flex items-center rounded px-1 py-0.5 text-[9px] font-medium bg-portal-info/15 text-portal-info"
          title={t('topology.badge.ansible')}
        >
          ⚙ {t('topology.badge.ansible_short')}
        </span>
      )}
      {guest.is_template && (
        <span
          className="inline-flex items-center rounded px-1 py-0.5 text-[9px] font-medium bg-gray-200 dark:bg-zinc-700 text-gray-600 dark:text-zinc-300"
          title={t('topology.badge.template')}
        >
          {t('topology.badge.template_short')}
        </span>
      )}
    </div>
  )
}
