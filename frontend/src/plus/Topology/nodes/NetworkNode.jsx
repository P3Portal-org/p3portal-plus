// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-75: Netz-Knoten (Node-Bridge / SDN-VNet / Stack-Bridge / Unbekannt).
// AC-NET-VIEW-1/4/6.
import { Handle, Position } from 'reactflow'
import { useTranslation } from 'react-i18next'

const KIND_STYLE = {
  node_bridge: 'border-gray-300 dark:border-zinc-600',
  sdn_vnet: 'border-portal-info',
  stack_bridge: 'border-portal-accent',
  unknown: 'border-portal-warn border-dashed',
  none: 'border-gray-300 dark:border-zinc-600 border-dashed',
}

export default function NetworkNode({ data }) {
  const { t } = useTranslation()
  const n = data.network
  const border = KIND_STYLE[n.kind] || KIND_STYLE.node_bridge
  // Stack-Bridge wird hervorgehoben, wenn der Stack-Filter genau auf sie zeigt.
  const stackMatch = n.owning_stack && data.stackFilter === n.owning_stack
  return (
    <div className={`rounded-md border-2 bg-white dark:bg-zinc-900 shadow-sm w-[178px] ${border} ${stackMatch ? 'ring-2 ring-portal-accent' : ''}`}>
      <Handle type="target" position={Position.Top} className="!bg-gray-300 dark:!bg-zinc-600 !w-1.5 !h-1.5" />
      <div className="px-2 py-1.5">
        <div className="flex items-center gap-1.5">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} className="w-4 h-4 shrink-0 text-gray-500 dark:text-zinc-400">
            <circle cx="12" cy="5" r="2.5" /><circle cx="5" cy="19" r="2.5" /><circle cx="19" cy="19" r="2.5" />
            <path d="M12 7.5v4M12 11.5 6.5 17M12 11.5 17.5 17" />
          </svg>
          <span className="flex-1 min-w-0 truncate text-xs font-medium text-gray-900 dark:text-zinc-100" title={n.label || t(`topology.net.kind.${n.kind}`)}>
            {n.label || t(`topology.net.kind.${n.kind}`)}
          </span>
        </div>
        <div className="mt-0.5 flex flex-wrap items-center gap-1 text-[9px]">
          {n.kind !== 'none' && (
            <span className="rounded px-1 py-0.5 bg-gray-100 dark:bg-zinc-800 text-gray-500 dark:text-zinc-400">
              {t(`topology.net.kind.${n.kind}`)}
            </span>
          )}
          {n.vlan_tag != null && (
            <span className="rounded px-1 py-0.5 bg-portal-info/10 text-portal-info">VLAN {n.vlan_tag}</span>
          )}
          {n.owning_stack && (
            <span className="rounded px-1 py-0.5 bg-portal-accent/15 text-portal-accent max-w-[80px] truncate" title={n.owning_stack}>
              ⛓ {n.owning_stack}
            </span>
          )}
        </div>
      </div>
      <Handle type="source" position={Position.Bottom} className="!bg-gray-300 dark:!bg-zinc-600 !w-1.5 !h-1.5" />
    </div>
  )
}
