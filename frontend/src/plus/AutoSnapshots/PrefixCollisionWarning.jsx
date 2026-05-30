// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-77: Warn-Box bei Prefix-Kollision (AC-UI-7).
// Wird im ScheduledJobDetailModal eingeblendet, wenn das Backend in den
// letzten Runs eine Pre-Existing-`p3auto_*`-Snapshot ohne DB-Eintrag
// gemeldet hat.
import { useTranslation } from 'react-i18next'

export default function PrefixCollisionWarning({ collisions = [] }) {
  const { t } = useTranslation()
  if (!collisions || collisions.length === 0) return null

  return (
    <div className="bg-portal-warn/10 border border-portal-warn/30 rounded-lg px-4 py-3">
      <p className="text-xs font-medium text-portal-warn mb-1">
        {t('auto_snapshots.warn.prefix_collision_title')}
      </p>
      <p className="text-xs text-portal-warn/80 mb-2">
        {t('auto_snapshots.warn.prefix_collision')}
      </p>
      <ul className="text-xs font-mono text-portal-warn/80 space-y-0.5 max-h-32 overflow-y-auto">
        {collisions.slice(0, 20).map((c, i) => (
          <li key={i}>
            {c.proxmox_node ?? c.node ?? '–'} · vmid {c.vmid} · {c.snapname}
          </li>
        ))}
      </ul>
      {collisions.length > 20 && (
        <p className="text-xs text-portal-warn/60 mt-1">
          {t('auto_snapshots.warn.prefix_collision_more', { count: collisions.length - 20 })}
        </p>
      )}
    </div>
  )
}
