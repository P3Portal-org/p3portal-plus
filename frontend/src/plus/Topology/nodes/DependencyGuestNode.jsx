// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-96: Kompakter VM/LXC-Knoten für die Abhängigkeits-Sicht. Anders als der
// Compute-/Netz-GuestNode hat er BEIDE Handles (oben=target, unten=source), da
// gerichtete Abhängigkeits-Kanten von ihm ausgehen UND auf ihn zeigen.
import { Handle, Position } from 'reactflow'
import { StatusBadge } from '../NodeBadges'

function GuestIcon({ type }) {
  return type === 'lxc' ? (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} className="w-3.5 h-3.5 shrink-0 text-gray-500 dark:text-zinc-400">
      <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
      <path d="M3.27 6.96 12 12.01l8.73-5.05M12 22.08V12" />
    </svg>
  ) : (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} className="w-3.5 h-3.5 shrink-0 text-gray-500 dark:text-zinc-400">
      <rect x="2" y="3" width="20" height="14" rx="2" /><path d="M8 21h8M12 17v4" />
    </svg>
  )
}

export default function DependencyGuestNode({ data }) {
  const g = data.guest
  return (
    <div className="rounded-md border-2 border-gray-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 shadow-sm w-[200px]">
      <Handle type="target" position={Position.Top} className="!bg-portal-info !w-1.5 !h-1.5" />
      <div className="px-2 py-1.5">
        <div className="flex items-start gap-1.5">
          <GuestIcon type={g.type} />
          <span
            className="flex-1 min-w-0 text-xs font-medium text-gray-900 dark:text-zinc-100 break-words leading-tight [display:-webkit-box] [-webkit-line-clamp:2] [-webkit-box-orient:vertical] overflow-hidden"
            title={g.label}
          >
            {g.label}
          </span>
          <StatusBadge status={g.status} />
        </div>
        <div className="mt-0.5 flex items-center justify-between gap-2 text-[9px] text-gray-400 dark:text-zinc-500">
          <span>{g.type === 'lxc' ? 'LXC' : 'VM'} · {g.vmid}</span>
          {g.installation && <span className="truncate text-gray-500 dark:text-zinc-400">{g.installation}</span>}
        </div>
      </div>
      <Handle type="source" position={Position.Bottom} className="!bg-portal-info !w-1.5 !h-1.5" />
    </div>
  )
}
