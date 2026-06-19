// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-75: Proxmox-Node-Knoten (Compute-Sicht, Wurzel je Node). AC-CMP-1.
import { Handle, Position } from 'reactflow'
import { useTranslation } from 'react-i18next'
import { formatBytes } from '../topologyHelpers'

export default function NodeNode({ data }) {
  const { t } = useTranslation()
  const n = data.node

  // Synthetischer „Vorlagen"-Header (Templates getrennt vom VM-Raster): keine
  // Status-/CPU-Zeile, keine Andockpunkte (es laufen keine Bus-Linien daran).
  if (n.status === 'templates') {
    return (
      <div className="rounded-md border border-dashed border-gray-300 dark:border-zinc-600 bg-portal-bg2 shadow-sm w-[184px]">
        <div className="px-2.5 py-2 flex items-center gap-1.5">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} className="w-4 h-4 shrink-0 text-gray-500 dark:text-zinc-400">
            <path d="M12 2 2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />
          </svg>
          <span className="text-sm font-semibold text-gray-700 dark:text-zinc-200">{t('topology.templates')}</span>
        </div>
      </div>
    )
  }

  const offline = n.status !== 'online'
  return (
    <div
      className={`rounded-md border bg-portal-bg2 shadow-sm w-[184px] ${
        offline ? 'border-portal-danger' : 'border-portal-border'
      }`}
    >
      <Handle type="target" position={Position.Top} className="!bg-gray-300 dark:!bg-zinc-600 !w-1.5 !h-1.5" />
      <div className="px-2.5 py-2">
        <div className="flex items-center gap-1.5">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} className="w-4 h-4 shrink-0 text-gray-600 dark:text-zinc-300">
            <rect x="2" y="3" width="20" height="7" rx="1.5" /><rect x="2" y="14" width="20" height="7" rx="1.5" />
            <path d="M6 6.5h.01M6 17.5h.01" />
          </svg>
          <span className="flex-1 min-w-0 truncate text-sm font-semibold text-gray-900 dark:text-zinc-100" title={n.label}>
            {n.label}
          </span>
          <span
            className={`inline-flex items-center rounded px-1 py-0.5 text-[9px] font-medium ${
              offline ? 'bg-portal-danger/15 text-portal-danger' : 'bg-portal-success/15 text-portal-success'
            }`}
          >
            {t(`topology.node.${offline ? 'offline' : 'online'}`)}
          </span>
        </div>
        <div className="mt-1 flex items-center gap-2 text-[9px] text-gray-400 dark:text-zinc-500">
          <span>{n.cpu_count || '?'} CPU</span>
          <span>·</span>
          <span>{formatBytes(n.ram_total)}</span>
        </div>
      </div>
      <Handle type="source" position={Position.Bottom} className="!bg-gray-300 dark:!bg-zinc-600 !w-1.5 !h-1.5" />
    </div>
  )
}
