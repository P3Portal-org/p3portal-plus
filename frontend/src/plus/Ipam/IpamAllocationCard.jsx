// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-42 Phase 2: read-only IPAM-Karte auf der VM/LXC-Detailseite (US-7).
// Zeigt die zugeordnete IP + Pool + Status, sofern eine Allocation existiert.
// Rendert nichts, wenn keine Allocation vorliegt (Muster: unauffällig).
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { allocationForVm } from './api'
import { listPools } from '../../api/ipam'
import { poolLabel, StatusBadge } from './helpers'

export default function IpamAllocationCard({ portalNodeId, vmid }) {
  const { t } = useTranslation()

  const { data: alloc, isLoading } = useQuery({
    queryKey: ['ipam', 'alloc-for-vm', portalNodeId, vmid],
    queryFn: () => allocationForVm({ portalNodeId, vmid }),
    enabled: portalNodeId != null && vmid != null,
    staleTime: 30_000,
  })

  const { data: pools } = useQuery({
    queryKey: ['ipam', 'pools'],
    queryFn: listPools,
    enabled: !!alloc,
    staleTime: 30_000,
  })

  // Kein Fund / noch am Laden → nichts rendern (keine leere Karte).
  if (isLoading || !alloc) return null

  const pool = (pools || []).find((p) => p.id === alloc.pool_id) || null

  return (
    <div className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-700 rounded-lg p-4">
      <h3 className="text-sm font-semibold text-gray-900 dark:text-zinc-100 mb-2">
        {t('ipam.card.title')}
      </h3>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
        <div>
          <span className="text-portal-text2">{t('ipam.card.ip')}: </span>
          <span className="font-mono text-gray-900 dark:text-zinc-100">{alloc.ip}</span>
        </div>
        <div>
          <span className="text-portal-text2">{t('ipam.card.pool')}: </span>
          <span className="text-gray-900 dark:text-zinc-100">{pool ? poolLabel(pool, t) : `#${alloc.pool_id}`}</span>
        </div>
        <StatusBadge status={alloc.status} t={t} />
      </div>
    </div>
  )
}
