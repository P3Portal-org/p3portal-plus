// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-75: Dashboard-Widget. Default eingeklappt (Kompakt-Statistik); ausgeklappt
// zeigt es ausschließlich die Compute-Sicht kompakt (~400 px). AC-WIDGET-*.
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import TopologyGraph from './TopologyGraph'
import { useTopologyCluster } from './hooks'
import { DEFAULT_FILTERS } from './topologyHelpers'

const EXPAND_KEY = 'p3_topology_widget_expanded'

function readExpanded() {
  try { return localStorage.getItem(EXPAND_KEY) === '1' } catch { return false }
}

function Stat({ label, value }) {
  return (
    <span className="inline-flex items-baseline gap-1">
      <span className="text-sm font-semibold text-gray-900 dark:text-zinc-100 tabular-nums">{value}</span>
      <span className="text-[11px] text-gray-400 dark:text-zinc-500">{label}</span>
    </span>
  )
}

export default function TopologyWidget() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [expanded, setExpanded] = useState(readExpanded)
  // Eingeklappt: einmal laden für die Stats, kein 60-s-Poll. Erst beim Aufklappen
  // live pollen (vermeidet teure per-VM-IP-Abrufe im Hintergrund).
  const { data } = useTopologyCluster({ poll: expanded })

  const s = data?.stats || {}

  const toggle = () => {
    setExpanded((e) => {
      const next = !e
      try { localStorage.setItem(EXPAND_KEY, next ? '1' : '0') } catch { /* EC-11 */ }
      return next
    })
  }

  return (
    <section className="rounded-lg border border-gray-200 dark:border-zinc-700 bg-white dark:bg-zinc-900">
      <div className="flex items-center gap-3 px-4 py-2.5">
        <button
          type="button"
          onClick={toggle}
          className="flex items-center gap-2 text-sm font-semibold text-gray-900 dark:text-zinc-100"
          aria-expanded={expanded}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className={`w-4 h-4 transition-transform ${expanded ? 'rotate-90' : ''}`}>
            <path d="m9 18 6-6-6-6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          {t('topology.widget.title')}
        </button>

        <div className="hidden sm:flex items-center gap-4 ml-2">
          <Stat label={t('topology.stat.installations')} value={s.installations ?? '–'} />
          <Stat label={t('topology.stat.nodes')} value={s.nodes ?? '–'} />
          <Stat label={t('topology.stat.vms')} value={s.vms ?? '–'} />
          <Stat label={t('topology.stat.lxcs')} value={s.lxcs ?? '–'} />
          <Stat label={t('topology.stat.running')} value={s.running ?? '–'} />
          <Stat label={t('topology.stat.stack')} value={s.stack_managed ?? '–'} />
        </div>

        <button
          type="button"
          onClick={() => navigate('/dashboard?tab=topology')}
          className="ml-auto btn-secondary text-xs flex items-center gap-1"
          title={t('topology.widget.open_fullscreen')}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="w-3.5 h-3.5">
            <path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          {t('topology.widget.open_fullscreen')}
        </button>
      </div>

      {expanded && (
        <div className="border-t border-gray-100 dark:border-zinc-800" style={{ height: 400 }}>
          <TopologyGraph
            view="compute"
            clusterData={data}
            filters={DEFAULT_FILTERS}
            compact
          />
        </div>
      )}
    </section>
  )
}
