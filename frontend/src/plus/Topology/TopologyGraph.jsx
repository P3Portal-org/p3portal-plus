// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-75: ReactFlow-Canvas. Wird vom Tab (Vollbild) und vom Widget (kompakt)
// geteilt. Die reactflow-CSS wird hier importiert → landet im Plus-Lazy-Chunk
// (kein Core-Bundle-Leak).
import { useMemo, useEffect, useState, useCallback } from 'react'
import ReactFlow, {
  Background,
  Controls,
  ReactFlowProvider,
  useReactFlow,
} from 'reactflow'
import 'reactflow/dist/style.css'
import { useNavigate } from 'react-router-dom'
import NodeNode from './nodes/NodeNode'
import GuestNode from './nodes/GuestNode'
import NetworkNode from './nodes/NetworkNode'
import InstallationBanner from './nodes/InstallationBanner'
import DependencyGuestNode from './nodes/DependencyGuestNode'
import BusEdge from './BusEdge'
import DependencyEdge from './DependencyEdge'
import Legend from './Legend'
import TopologyEmptyState from './TopologyEmptyState'
import { buildComputeFlow, buildNetworkFlow, buildDependencyFlow } from './topologyModel'
import { hasActiveFilters } from './topologyHelpers'

const NODE_TYPES = {
  topoNode: NodeNode,
  topoGuest: GuestNode,
  topoNetwork: NetworkNode,
  topoBanner: InstallationBanner,
  topoDepGuest: DependencyGuestNode,
}

const EDGE_TYPES = { bus: BusEdge, dependency: DependencyEdge }

// Knoten-Schwelle für `onlyRenderVisibleElements` (AC-PERF-1/2).
const PERF_THRESHOLD = 500

function FitOnChange({ depKey }) {
  const { fitView } = useReactFlow()
  useEffect(() => {
    const id = requestAnimationFrame(() => fitView({ padding: 0.2, duration: 200 }))
    return () => cancelAnimationFrame(id)
  }, [depKey, fitView])
  return null
}

function GraphInner({ view, clusterData, networkData, dependencyData, filters, onGuestClick, showLegend, compact }) {
  const navigate = useNavigate()
  // Hover-Hervorhebung: zeigt, welche Gäste tatsächlich an einer Bridge/VM
  // hängen. Ohne sie verschmelzen die Kanten optisch zu einer „Schiene", sodass
  // es aussieht, als hinge jeder Gast an jeder Bridge (Netz-Sicht-Lesbarkeit).
  const [hoverId, setHoverId] = useState(null)

  const { nodes, edges } = useMemo(() => {
    if (view === 'dependencies') return buildDependencyFlow(dependencyData, filters)
    if (view === 'network') return buildNetworkFlow(clusterData, networkData, filters)
    return buildComputeFlow(clusterData, filters)
  }, [view, clusterData, networkData, dependencyData, filters])

  // Wende die Hervorhebung an: gehoverter Knoten + seine direkten Nachbarn voll,
  // der Rest abgeblendet; verbundene Kanten in Akzentfarbe, fremde fast unsichtbar.
  const { viewNodes, viewEdges } = useMemo(() => {
    if (!hoverId) return { viewNodes: nodes, viewEdges: edges }
    const connected = new Set([hoverId])
    const viewEdges = edges.map((e) => {
      const touches = e.source === hoverId || e.target === hoverId
      if (touches) {
        connected.add(e.source)
        connected.add(e.target)
        return { ...e, style: { stroke: 'var(--accent)', strokeWidth: 2.5 }, animated: true, zIndex: 20 }
      }
      return { ...e, style: { ...e.style, opacity: 0.05 } }
    })
    const viewNodes = nodes.map((n) =>
      n.type === 'topoBanner' || connected.has(n.id)
        ? n
        : { ...n, style: { ...(n.style || {}), opacity: 0.25 } },
    )
    return { viewNodes, viewEdges }
  }, [nodes, edges, hoverId])

  const realNodes = nodes.filter((n) => n.type !== 'topoBanner').length
  const bigGraph = realNodes > PERF_THRESHOLD

  const onNodeMouseEnter = useCallback((_e, n) => {
    if (n.type !== 'topoBanner') setHoverId(n.id)
  }, [])
  const onNodeMouseLeave = useCallback(() => setHoverId(null), [])

  const handleNodeClick = (_evt, node) => {
    if (node.type === 'topoNode') {
      if (node.data.node.status === 'templates') return  // „Vorlagen"-Header ist kein Node
      navigate(`/compute/${node.data.node.node}`)
    } else if (node.type === 'topoNetwork') {
      navigate('/network')
    } else if (node.type === 'topoGuest') {
      const g = node.data.guest
      if (onGuestClick) onGuestClick(g)
      else navigate(`/vm/${g.node}/${g.type === 'lxc' ? 'lxc' : 'qemu'}/${g.vmid}`)
    } else if (node.type === 'topoDepGuest') {
      // PROJ-96: Klick → VM-Detailseite (mit der Abhängigkeits-Sektion); das
      // Netz-Detail-Panel wäre hier unpassend.
      const g = node.data.guest
      navigate(`/vm/${g.node}/${g.type === 'lxc' ? 'lxc' : 'qemu'}/${g.vmid}`)
    }
  }

  if (realNodes === 0) {
    const reason = hasActiveFilters(filters)
      ? 'filtered'
      : view === 'dependencies' ? 'no_deps' : 'no_access'
    return <TopologyEmptyState reason={reason} />
  }

  return (
    <ReactFlow
      nodes={viewNodes}
      edges={viewEdges}
      nodeTypes={NODE_TYPES}
      edgeTypes={EDGE_TYPES}
      onNodeClick={handleNodeClick}
      onNodeMouseEnter={onNodeMouseEnter}
      onNodeMouseLeave={onNodeMouseLeave}
      fitView
      fitViewOptions={{ padding: 0.2 }}
      minZoom={0.1}
      maxZoom={2}
      onlyRenderVisibleElements={bigGraph}
      nodesDraggable
      nodesConnectable={false}
      elementsSelectable
      proOptions={{ hideAttribution: false }}
    >
      <FitOnChange depKey={`${view}:${realNodes}`} />
      <Background gap={18} color="var(--portal-border, #e5e7eb)" />
      {!compact && <Controls position="bottom-right" showInteractive={false} />}
      {showLegend && (
        <div className="absolute bottom-3 left-3 z-10">
          <Legend view={view} />
        </div>
      )}
    </ReactFlow>
  )
}

export default function TopologyGraph(props) {
  return (
    <ReactFlowProvider>
      <GraphInner {...props} />
    </ReactFlowProvider>
  )
}
