// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-75: Netz-Board — linienfreie Alternative zur Graph-Netzsicht. Oben eine
// Node/Cluster-Auswahl (kein endloses Scrollen), darunter eine Node-Card-Kopfzeile
// und pro Bridge/VNet eine Box mit der vollständigen Gästeliste (volle Namen + IP).
// Multi-Homed-Gäste (Firewalls) erscheinen in jeder Box, an der sie hängen. Hover
// über eine VM/LXC hebt alle Boxen hervor, an denen sie hängt.
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import MiniResourceBar from './MiniResourceBar'
import { StatusBadge, GuestBadges } from './NodeBadges'
import { cpuPct, memPct, diskPct, formatBytes, hasActiveFilters } from './topologyHelpers'
import { buildNetworkBoard } from './topologyModel'
import TopologyEmptyState from './TopologyEmptyState'

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

const NET_BORDER = {
  node_bridge: 'border-gray-300 dark:border-zinc-600',
  sdn_vnet: 'border-portal-info',
  stack_bridge: 'border-portal-accent',
  unknown: 'border-portal-warn border-dashed',
  none: 'border-gray-300 dark:border-zinc-600 border-dashed',
}

function GuestCard({ guest, dimmed, highlighted, onHover, onClick }) {
  const { t } = useTranslation()
  const cpu = cpuPct(guest)
  const mem = memPct(guest)
  const disk = diskPct(guest)
  const cpuTip = cpu == null ? t('topology.res.cpu_na') : t('topology.res.cpu_tip', { pct: cpu.toFixed(0), cores: guest.maxcpu || '?' })
  const memTip = mem == null ? t('topology.res.ram_na') : t('topology.res.ram_tip', { used: formatBytes(guest.mem), total: formatBytes(guest.maxmem) })
  const diskTip = disk == null ? t('topology.res.disk_na') : t('topology.res.disk_tip', { used: formatBytes(guest.disk), total: formatBytes(guest.maxdisk) })

  return (
    <button
      type="button"
      onClick={() => onClick?.(guest)}
      onMouseEnter={() => onHover?.(guest.id)}
      onMouseLeave={() => onHover?.(null)}
      className={`w-full text-left rounded-md border bg-white dark:bg-zinc-900 px-2.5 py-2 transition-all ${
        guest.managed_by_stack ? 'border-portal-accent' : 'border-gray-200 dark:border-zinc-700'
      } ${highlighted ? 'ring-2 ring-portal-accent' : ''} ${dimmed ? 'opacity-40' : ''}`}
    >
      <div className="flex items-start gap-1.5">
        <GuestIcon type={guest.type} />
        <span className="flex-1 min-w-0 break-words text-xs font-medium text-gray-900 dark:text-zinc-100 leading-snug">
          {guest.label}
        </span>
        <StatusBadge status={guest.status} />
      </div>
      <div className="mt-0.5 flex items-center justify-between gap-2 text-[10px] text-gray-400 dark:text-zinc-500">
        <span>{guest.type === 'lxc' ? 'LXC' : 'VM'} · {guest.vmid}</span>
        {guest.ip && <span className="font-mono text-gray-500 dark:text-zinc-400">{guest.ip}</span>}
      </div>
      {(guest.managed_by_stack || guest.ssh_managed || guest.is_template) && (
        <div className="mt-1"><GuestBadges guest={guest} /></div>
      )}
      <div className="mt-1.5 space-y-1">
        <MiniResourceBar label="CPU" pct={cpu} tooltip={cpuTip} naLabel={t('topology.na')} />
        <MiniResourceBar label="RAM" pct={mem} tooltip={memTip} naLabel={t('topology.na')} />
        <MiniResourceBar label="DISK" pct={disk} tooltip={diskTip} naLabel={t('topology.na')} />
      </div>
    </button>
  )
}

function NetworkBox({ group, hoverGuest, onHover, onClick }) {
  const { t } = useTranslation()
  const { network: n, guests } = group
  const border = NET_BORDER[n.kind] || NET_BORDER.node_bridge
  const containsHovered = !!hoverGuest && guests.some((g) => g.id === hoverGuest)
  const dimBox = !!hoverGuest && !containsHovered
  const title = n.label || t(`topology.net.kind.${n.kind}`)

  return (
    <section
      className={`rounded-lg border-2 ${border} bg-gray-50/50 dark:bg-zinc-800/30 transition-all ${
        dimBox ? 'opacity-40' : ''
      } ${containsHovered ? 'ring-2 ring-portal-accent' : ''}`}
    >
      <header className="px-3 py-2 border-b border-gray-200 dark:border-zinc-700">
        <div className="flex items-center gap-1.5">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} className="w-4 h-4 shrink-0 text-gray-500 dark:text-zinc-400">
            <circle cx="12" cy="5" r="2.5" /><circle cx="5" cy="19" r="2.5" /><circle cx="19" cy="19" r="2.5" />
            <path d="M12 7.5v4M12 11.5 6.5 17M12 11.5 17.5 17" />
          </svg>
          <span className="flex-1 min-w-0 truncate text-sm font-semibold text-gray-900 dark:text-zinc-100" title={title}>{title}</span>
          {n.kind !== 'none' && (
            <span className="rounded px-1.5 py-0.5 text-[10px] bg-gray-200 dark:bg-zinc-700 text-gray-500 dark:text-zinc-300">
              {t(`topology.net.kind.${n.kind}`)}
            </span>
          )}
          {n.vlan_tag != null && (
            <span className="rounded px-1.5 py-0.5 text-[10px] bg-portal-info/10 text-portal-info">VLAN {n.vlan_tag}</span>
          )}
          <span className="rounded-full px-1.5 py-0.5 text-[10px] tabular-nums bg-gray-200 dark:bg-zinc-700 text-gray-600 dark:text-zinc-300">
            {guests.length}
          </span>
        </div>
        {n.address && (
          <div className="mt-0.5 text-[10px] font-mono text-gray-400 dark:text-zinc-500" title={t('topology.board.bridge_ip')}>
            {n.address}
          </div>
        )}
      </header>
      {guests.length === 0 ? (
        <div className="px-3 py-3 text-[11px] text-gray-400 dark:text-zinc-500">{t('topology.board.empty_box')}</div>
      ) : (
        <div className="p-2 grid gap-2 [grid-template-columns:repeat(auto-fill,minmax(200px,1fr))]">
          {guests.map((g) => (
            <GuestCard
              key={g.id}
              guest={g}
              highlighted={hoverGuest === g.id}
              dimmed={!!hoverGuest && hoverGuest !== g.id && !containsHovered}
              onHover={onHover}
              onClick={onClick}
            />
          ))}
        </div>
      )}
    </section>
  )
}

function NodeHeaderCard({ node }) {
  const { t } = useTranslation()
  const online = node.status === 'online'
  const ramTotal = node.ram_total || 0
  return (
    <div className="inline-flex items-center gap-2 rounded-lg border border-gray-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-3 py-1.5">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} className="w-4 h-4 shrink-0 text-gray-500 dark:text-zinc-400">
        <rect x="2" y="2" width="20" height="8" rx="2" /><rect x="2" y="14" width="20" height="8" rx="2" />
        <path d="M6 6h.01M6 18h.01" />
      </svg>
      <span className="text-sm font-semibold text-gray-900 dark:text-zinc-100">{node.label || node.node}</span>
      <span className={`rounded px-1.5 py-0.5 text-[10px] ${online ? 'bg-portal-success/15 text-portal-success' : 'bg-portal-danger/15 text-portal-danger'}`}>
        {online ? t('topology.node.online') : t('topology.node.offline')}
      </span>
      {!!node.cpu_count && (
        <span className="text-[11px] text-gray-400 dark:text-zinc-500">{node.cpu_count} {t('topology.board.cores')}</span>
      )}
      {!!ramTotal && (
        <span className="text-[11px] text-gray-400 dark:text-zinc-500">{formatBytes(ramTotal)} RAM</span>
      )}
    </div>
  )
}

export default function NetworkBoard({ clusterData, networkData, filters, onGuestClick }) {
  const { t } = useTranslation()
  const [hoverGuest, setHoverGuest] = useState(null)
  const [selectedId, setSelectedId] = useState(null)

  const board = useMemo(
    () => buildNetworkBoard(clusterData, networkData, filters),
    [clusterData, networkData, filters],
  )

  // Nur Installationen mit Inhalt; ausgewählte (default erste).
  const installations = board.installations.filter((i) => i.groups.length > 0 || i.noNet.length > 0)
  if (installations.length === 0) {
    return <TopologyEmptyState reason={hasActiveFilters(filters) ? 'filtered' : 'no_access'} />
  }
  const selected = installations.find((i) => i.id === selectedId) || installations[0]

  const boxes = [...selected.groups]
  if (selected.noNet.length) {
    boxes.push({
      network: { id: `${selected.id}-nonet`, kind: 'none', label: '', scope: 'node' },
      guests: selected.noNet,
    })
  }

  return (
    <div className="h-full overflow-auto p-4">
      {/* Node/Cluster-Auswahl oben (kein vertikales Stapeln + Scrollen). */}
      {installations.length > 1 && (
        <div className="mb-3 inline-flex flex-wrap gap-1 rounded-md border border-gray-300 dark:border-zinc-700 p-0.5">
          {installations.map((inst) => {
            const active = inst.id === selected.id
            return (
              <button
                key={inst.id}
                type="button"
                onClick={() => setSelectedId(inst.id)}
                className={`px-2.5 py-1 rounded text-xs transition-colors ${
                  active ? 'bg-[var(--accent)] text-white' : 'text-gray-600 dark:text-zinc-300 hover:bg-gray-100 dark:hover:bg-zinc-800'
                }`}
              >
                {inst.name}
              </button>
            )
          })}
        </div>
      )}

      {/* Node-Card-Kopfzeile (statt „Installation: X"). */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        {selected.nodes.length > 0 ? (
          selected.nodes.map((nd) => <NodeHeaderCard key={nd.id || nd.node} node={nd} />)
        ) : (
          <NodeHeaderCard node={{ node: selected.name, label: selected.name, status: selected.unreachable ? 'offline' : 'online' }} />
        )}
        {selected.unreachable && (
          <span className="rounded px-1.5 py-0.5 text-[10px] bg-portal-danger/15 text-portal-danger">
            {t('topology.unreachable')}
          </span>
        )}
      </div>

      <div className="grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(300px,1fr))]">
        {boxes.map((g) => (
          <NetworkBox
            key={g.network.id}
            group={g}
            hoverGuest={hoverGuest}
            onHover={setHoverGuest}
            onClick={onGuestClick}
          />
        ))}
      </div>
    </div>
  )
}
