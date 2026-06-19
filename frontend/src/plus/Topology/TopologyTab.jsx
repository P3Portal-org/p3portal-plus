// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-75: Vollbild-Topologie-Tab (Toolbar + View-Toggle + Filter + Graph +
// Detail-Panel). AC-TAB-*, AC-VIEW-*, AC-PERF-2.
import { useState, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { useCapability } from '../../hooks/useCapability'
import FilterToolbar from './FilterToolbar'
import TopologyGraph from './TopologyGraph'
import NetworkBoard from './NetworkBoard'
import NetworkDetailPanel from './NetworkDetailPanel'
import { useTopologyCluster, useTopologyNetwork, useTopologyDependencies } from './hooks'
import { DEFAULT_FILTERS } from './topologyHelpers'
import { totalNodeCount } from './topologyModel'

const VIEW_KEY = 'p3_topology_view'
const VALID_VIEWS = ['compute', 'network', 'board', 'dependencies']

function readView() {
  try {
    const v = localStorage.getItem(VIEW_KEY)
    return VALID_VIEWS.includes(v) ? v : 'compute'
  } catch {
    return 'compute'
  }
}

export default function TopologyTab() {
  const { t } = useTranslation()
  const showDeps = useCapability('vm_dependencies')  // PROJ-96
  const [viewRaw, setViewState] = useState(readView)
  const [filters, setFilters] = useState(DEFAULT_FILTERS)
  const [selected, setSelected] = useState(null)

  // PROJ-96: persistierte „dependencies"-Sicht ohne Capability → auf Compute.
  const view = (viewRaw === 'dependencies' && !showDeps) ? 'compute' : viewRaw

  // Netz-Daten brauchen sowohl die Graph-Netzsicht als auch das Board.
  const needsNetwork = view === 'network' || view === 'board'
  const needsDeps = view === 'dependencies'

  const cluster = useTopologyCluster({ enabled: view !== 'dependencies' })
  const network = useTopologyNetwork({ enabled: needsNetwork })
  const dependencies = useTopologyDependencies({ enabled: needsDeps })

  const setView = useCallback((v) => {
    setViewState(v)
    try { localStorage.setItem(VIEW_KEY, v) } catch { /* EC-11: localStorage blockiert */ }
  }, [])

  const refresh = useCallback(() => {
    if (needsDeps) dependencies.refetch()
    else cluster.refetch()
    if (needsNetwork) network.refetch()
  }, [cluster, network, dependencies, needsNetwork, needsDeps])

  const loading = needsDeps
    ? dependencies.isLoading
    : cluster.isLoading || (needsNetwork && network.isLoading)
  const errored = needsDeps
    ? dependencies.isError
    : cluster.isError || (needsNetwork && network.isError)
  const refreshing = needsDeps
    ? dependencies.isFetching
    : cluster.isFetching || (needsNetwork && network.isFetching)
  const bigGraph = view === 'compute' || view === 'network'
    ? totalNodeCount(cluster.data, network.data) > 500
    : false

  // Best-Effort: einzelne unerreichbare Installationen (AC-BE-10 / EC-16).
  const unreachable = (cluster.data?.installations || []).filter((i) => i.unreachable).map((i) => i.name)

  // Netz-Diagnose: Installationen, deren per-VM-Config-Abruf (teilweise) scheitert
  // → Bridges erscheinen, aber Konnektivitäts-Kanten fehlen (z. B. fehlendes
  // VM.Audit / Timeout). Macht die früher stille Lücke sichtbar.
  const netDiag = needsNetwork
    ? (network.data?.diagnostics || []).filter((d) => d.guests_failed > 0)
    : []

  return (
    <div className="flex flex-col flex-1 min-h-0">
      <FilterToolbar
        view={view}
        onViewChange={setView}
        filters={filters}
        onFiltersChange={setFilters}
        stacks={cluster.data?.stacks || []}
        onRefresh={refresh}
        refreshing={refreshing}
        showDependencies={showDeps}
      />

      {bigGraph && (
        <div className="px-3 py-1.5 bg-portal-warn/10 text-portal-warn text-xs border-b border-portal-warn/20">
          {t('topology.perf_warn')}
        </div>
      )}
      {unreachable.length > 0 && (
        <div className="px-3 py-1.5 bg-portal-danger/10 text-portal-danger text-xs border-b border-portal-danger/20">
          {t('topology.unreachable_banner', { names: unreachable.join(', ') })}
        </div>
      )}
      {netDiag.map((d) => (
        <div key={d.installation_id} className="px-3 py-1.5 bg-portal-warn/10 text-portal-warn text-xs border-b border-portal-warn/20">
          {t('topology.conn_warn', {
            name: d.name,
            failed: d.guests_failed,
            total: d.guests_total,
            reasons: (d.sample_errors || []).join(', ') || '—',
          })}
        </div>
      ))}

      <div className="relative flex-1 min-h-0">
        {loading ? (
          <div className="flex items-center justify-center h-full text-sm text-gray-400 dark:text-zinc-500">
            {t('topology.loading')}
          </div>
        ) : errored ? (
          <div className="flex items-center justify-center h-full text-sm text-portal-danger">
            {t('topology.load_error')}
          </div>
        ) : view === 'board' ? (
          <NetworkBoard
            clusterData={cluster.data}
            networkData={network.data}
            filters={filters}
            onGuestClick={setSelected}
          />
        ) : (
          <TopologyGraph
            view={view}
            clusterData={cluster.data}
            networkData={network.data}
            dependencyData={dependencies.data}
            filters={filters}
            onGuestClick={view === 'dependencies' ? undefined : setSelected}
            showLegend
          />
        )}
      </div>

      {selected && <NetworkDetailPanel guest={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}
