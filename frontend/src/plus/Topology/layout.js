// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-75: Hierarchisches Auto-Layout via @dagrejs/dagre. React Flow liefert
// kein eigenes Layout; dagre berechnet die Positionen (Tech-Design § J).
// Fällt dagre aus (EC-6), liefert ein simples Grid-Layout den Fallback.
import dagre from '@dagrejs/dagre'

/**
 * Berechnet Top-Left-Positionen für eine Knotenmenge.
 * @param {Array<{id,width,height}>} nodes
 * @param {Array<{source,target}>} edges
 * @param {{rankdir?:string, ranksep?:number, nodesep?:number}} opts
 * @returns {Map<string,{x:number,y:number,width:number,height:number}>}
 */
export function layoutGraph(nodes, edges, opts = {}) {
  const { rankdir = 'TB', ranksep = 70, nodesep = 28 } = opts
  try {
    const g = new dagre.graphlib.Graph()
    g.setGraph({ rankdir, ranksep, nodesep, marginx: 16, marginy: 16 })
    g.setDefaultEdgeLabel(() => ({}))
    for (const n of nodes) {
      g.setNode(n.id, { width: n.width, height: n.height })
    }
    for (const e of edges) {
      // dagre verlangt, dass beide Endpunkte als Knoten existieren.
      if (g.hasNode(e.source) && g.hasNode(e.target)) g.setEdge(e.source, e.target)
    }
    dagre.layout(g)
    const out = new Map()
    for (const n of nodes) {
      const pos = g.node(n.id)
      if (!pos) throw new Error('dagre: missing node position')
      // dagre gibt den Mittelpunkt → in Top-Left umrechnen.
      out.set(n.id, { x: pos.x - n.width / 2, y: pos.y - n.height / 2, width: n.width, height: n.height })
    }
    return out
  } catch {
    return gridLayout(nodes)
  }
}

/** Fallback: Knoten in ein gleichmäßiges Raster legen (EC-6, kein White-Screen). */
export function gridLayout(nodes) {
  const out = new Map()
  const cols = Math.max(1, Math.ceil(Math.sqrt(nodes.length)))
  const colW = 240
  const rowH = 160
  nodes.forEach((n, i) => {
    const r = Math.floor(i / cols)
    const c = i % cols
    out.set(n.id, { x: c * colW, y: r * rowH, width: n.width, height: n.height })
  })
  return out
}

/** Bounding-Box einer Positions-Map (für Installations-Bänder + Stacking). */
export function boundingBox(posMap) {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  for (const p of posMap.values()) {
    minX = Math.min(minX, p.x)
    minY = Math.min(minY, p.y)
    maxX = Math.max(maxX, p.x + p.width)
    maxY = Math.max(maxY, p.y + p.height)
  }
  if (!Number.isFinite(minX)) return { x: 0, y: 0, width: 0, height: 0 }
  return { x: minX, y: minY, width: maxX - minX, height: maxY - minY }
}
