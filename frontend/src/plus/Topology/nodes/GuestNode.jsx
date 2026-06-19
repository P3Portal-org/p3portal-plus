// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-75: VM/LXC-Knoten (Compute-Sicht voll, Netz-Sicht kompakt).
import { Handle, Position } from 'reactflow'
import { useTranslation } from 'react-i18next'
import MiniResourceBar from '../MiniResourceBar'
import { StatusBadge, GuestBadges } from '../NodeBadges'
import { cpuPct, memPct, diskPct, formatBytes } from '../topologyHelpers'

function GuestIcon({ type }) {
  // VM = Monitor, LXC = Box
  return type === 'lxc' ? (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} className="w-4 h-4 shrink-0 text-gray-500 dark:text-zinc-400">
      <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
      <path d="M3.27 6.96 12 12.01l8.73-5.05M12 22.08V12" />
    </svg>
  ) : (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} className="w-4 h-4 shrink-0 text-gray-500 dark:text-zinc-400">
      <rect x="2" y="3" width="20" height="14" rx="2" /><path d="M8 21h8M12 17v4" />
    </svg>
  )
}

export default function GuestNode({ data }) {
  const { t } = useTranslation()
  const g = data.guest
  const compact = data.compact
  const accent = g.managed_by_stack ? 'border-portal-accent' : 'border-gray-200 dark:border-zinc-700'

  const cpu = cpuPct(g)
  const mem = memPct(g)
  const disk = diskPct(g)
  const cpuTip = cpu == null
    ? t('topology.res.cpu_na')
    : t('topology.res.cpu_tip', { pct: cpu.toFixed(0), cores: g.maxcpu || '?' })
  const memTip = mem == null
    ? t('topology.res.ram_na')
    : t('topology.res.ram_tip', { used: formatBytes(g.mem), total: formatBytes(g.maxmem) })
  const diskTip = disk == null
    ? t('topology.res.disk_na')
    : t('topology.res.disk_tip', { used: formatBytes(g.disk), total: formatBytes(g.maxdisk) })

  return (
    <div className={`rounded-md border-2 bg-white dark:bg-zinc-900 shadow-sm ${accent} ${compact ? 'w-[220px]' : 'w-[200px]'}`}>
      <Handle type="target" position={Position.Top} className="!bg-gray-300 dark:!bg-zinc-600 !w-1.5 !h-1.5" />
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
          {(g.ip || data.ip) && <span className="font-mono text-gray-500 dark:text-zinc-400 truncate">{g.ip || data.ip}</span>}
        </div>
        {!compact && (
          <>
            <div className="mt-1"><GuestBadges guest={g} /></div>
            <div className="mt-1.5 space-y-1">
              <MiniResourceBar label="CPU" pct={cpu} tooltip={cpuTip} naLabel={t('topology.na')} />
              <MiniResourceBar label="RAM" pct={mem} tooltip={memTip} naLabel={t('topology.na')} />
              <MiniResourceBar label="DISK" pct={disk} tooltip={diskTip} naLabel={t('topology.na')} />
            </div>
          </>
        )}
      </div>
      {/* Gäste sind Blätter (Node→VM bzw. Netz→VM) → nur EIN Andockpunkt (oben). */}
    </div>
  )
}
