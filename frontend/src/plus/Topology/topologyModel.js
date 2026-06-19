// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-75: Transformiert die Backend-Topologie + Toolbar-Filter in ReactFlow
// Knoten/Kanten. dagre läuft je Installation separat; die Blöcke werden
// vertikal gestapelt (Tech-Design § H/J).
import { filterGuests, guestMatchesFilters, visibleConnEdges } from './topologyHelpers'
import { layoutGraph } from './layout'

// Knoten-Dimensionen (müssen zum CSS der Node-Komponenten passen).
const DIM = {
  node: { width: 184, height: 66 },
  guest: { width: 210, height: 140 },         // 2-Zeilen-Name + Bars
  guestCompact: { width: 220, height: 80 },  // breiter → volle Namen (2 Zeilen) + IP
  network: { width: 188, height: 62 },
}

const COMPUTE_MAX_COLS = 6   // VMs als Raster unter ihrem Node (statt einer breiten Reihe)

const INSTALL_GAP = 70   // vertikaler Abstand zwischen Installations-Blöcken
const BANNER_H = 30

const edgeBase = {
  type: 'smoothstep',
  style: { stroke: 'var(--portal-border, #d4d4d8)', strokeWidth: 1 },
}

function bannerNode(inst, x, y) {
  return {
    id: `banner-${inst.id}`,
    type: 'topoBanner',
    position: { x, y },
    data: { name: inst.name, unreachable: !!inst.unreachable },
    draggable: false,
    selectable: false,
  }
}

// ── Compute-Sicht ─────────────────────────────────────────────────────────────

/**
 * @param {object} clusterData  Antwort von /api/topology/cluster
 * @param {object} filters      { status, type, stack, q }
 * @returns {{nodes:Array, edges:Array}}
 */
export function buildComputeFlow(clusterData, filters) {
  const installations = clusterData?.installations || []
  const allNodes = []
  const allEdges = []
  let offsetY = 0

  const NW = DIM.node.width
  const NH = DIM.node.height
  const GW = DIM.guest.width
  const GH = DIM.guest.height

  const busEdge = { type: 'bus', style: { stroke: 'var(--portal-border, #d4d4d8)', strokeWidth: 1.5 } }

  for (const inst of installations) {
    const visibleGuests = (inst.guests || []).filter((g) => guestMatchesFilters(g, filters))
    // Vorlagen (Templates) getrennt vom VM-Raster halten (eigener Bereich unten).
    const vms = visibleGuests.filter((g) => !g.is_template)
    const templates = visibleGuests.filter((g) => g.is_template)

    // VMs je Node gruppieren → jeder Node ein Cluster (Node oben, VMs als Raster
    // darunter, per Bus-Kante verbunden) statt einer einzigen breiten Reihe.
    const guestsByNode = new Map()
    for (const g of vms) {
      const k = g.parent_node_id || '__orphan'
      if (!guestsByNode.has(k)) guestsByNode.set(k, [])
      guestsByNode.get(k).push(g)
    }
    const nodeIds = new Set((inst.nodes || []).map((n) => n.id))
    const orphan = []
    for (const [k, gs] of guestsByNode) {
      if (k === '__orphan' || !nodeIds.has(k)) orphan.push(...gs)
    }

    if ((inst.nodes || []).length === 0 && orphan.length === 0 && templates.length === 0) continue

    let shelfX = 0
    let shelfY = 0
    let shelfMaxH = 0
    allNodes.push(bannerNode(inst, 0, offsetY - BANNER_H - 6))

    // header: {id,...} oder null; withEdges=false → reine Liste ohne Bus (Vorlagen).
    const placeCluster = (header, guests, withEdges = true) => {
      const count = guests.length
      const cols = count === 0 ? 1 : Math.min(COMPUTE_MAX_COLS, Math.max(1, Math.ceil(Math.sqrt(count))))
      const rows = count === 0 ? 0 : Math.ceil(count / cols)
      const gridW = cols * GW + (cols - 1) * G_GAP_X
      const clusterW = Math.max(gridW, NW)
      const clusterH = NH + (count ? NET_V_GAP + rows * GH + (rows - 1) * G_GAP_Y : 0)

      if (shelfX > 0 && shelfX + clusterW > SHELF_MAX_W) {
        shelfX = 0
        shelfY += shelfMaxH + CLUSTER_GAP
        shelfMaxH = 0
      }

      const baseY = offsetY + shelfY
      if (header) {
        allNodes.push({
          id: header.id,
          type: 'topoNode',
          position: { x: shelfX + (clusterW - NW) / 2, y: baseY },
          data: { node: header, view: 'compute' },
          sourcePosition: 'bottom',
          targetPosition: 'top',
        })
      }
      const gridLeft = shelfX + (clusterW - gridW) / 2
      guests.forEach((g, i) => {
        const col = i % cols
        const row = Math.floor(i / cols)
        allNodes.push({
          id: g.id,
          type: 'topoGuest',
          position: { x: gridLeft + col * (GW + G_GAP_X), y: baseY + NH + NET_V_GAP + row * (GH + G_GAP_Y) },
          data: { guest: g, view: 'compute' },
          sourcePosition: 'bottom',
          targetPosition: 'top',
        })
        // Genau eine Bus-Kante Node→VM (ein Andockpunkt oben).
        if (header && withEdges) {
          allEdges.push({ id: `e-${header.id}-${g.id}`, source: header.id, target: g.id, ...busEdge })
        }
      })

      shelfX += clusterW + CLUSTER_GAP
      shelfMaxH = Math.max(shelfMaxH, clusterH)
    }

    for (const node of inst.nodes || []) {
      placeCluster(node, guestsByNode.get(node.id) || [])
    }
    if (orphan.length) placeCluster(null, orphan)
    // Vorlagen: eigener Bereich (synthetischer „Vorlagen"-Header, keine Bus-Linien).
    if (templates.length) {
      placeCluster({ id: `${inst.id}-templates`, node: '', label: '', status: 'templates' }, templates, false)
    }

    offsetY += shelfY + shelfMaxH + INSTALL_GAP + BANNER_H
  }

  return { nodes: allNodes, edges: allEdges }
}

// ── Netz-Sicht (Cluster pro Bridge) ───────────────────────────────────────────
// Statt eines flachen bipartiten Graphen (alle Bridges in einer Reihe, alle
// Gäste darunter → „Schiene") wird jede Bridge zu einem Cluster: die Bridge oben,
// ihre Gäste als kompaktes Raster direkt darunter. Multi-NIC-Gäste sitzen unter
// ihrer ERSTEN Bridge; weitere Verbindungen erscheinen als dezente Kreuz-Kanten.

const NETW_W = DIM.network.width
const NETW_H = DIM.network.height
const GCW = DIM.guestCompact.width
const GCH = DIM.guestCompact.height
const G_GAP_X = 14          // Abstand der Gäste im Raster
const G_GAP_Y = 12
const NET_V_GAP = 28        // Abstand Bridge → Gäste-Raster
const CLUSTER_GAP = 52      // Abstand zwischen Clustern
const MAX_COLS = 4          // max. Spalten im Gäste-Raster pro Cluster
const SHELF_MAX_W = 1600    // Cluster brechen in ein neues „Regal" um

/**
 * @param {object} clusterData  /cluster (für die Gäste + Filter)
 * @param {object} networkData  /network (Netz-Knoten + Konnektivität)
 * @param {object} filters
 */
export function buildNetworkFlow(clusterData, networkData, filters) {
  const networks = networkData?.networks || []
  const edgesConn = networkData?.edges_conn || []

  const visibleGuests = filterGuests(clusterData?.installations, filters)
  const guestById = new Map(visibleGuests.map((g) => [g.id, g]))
  const visibleIds = new Set(visibleGuests.map((g) => g.id))
  const conn = visibleConnEdges(edgesConn, visibleIds)

  const netByInst = new Map()
  for (const n of networks) {
    if (!netByInst.has(n.installation_id)) netByInst.set(n.installation_id, [])
    netByInst.get(n.installation_id).push(n)
  }
  const instOf = new Map()
  for (const inst of clusterData?.installations || []) instOf.set(inst.id, inst)

  // Gast → geordnete Netz-IDs (aus den sichtbaren Kanten).
  const guestNets = new Map()
  for (const e of conn) {
    if (!guestNets.has(e.guest_id)) guestNets.set(e.guest_id, [])
    guestNets.get(e.guest_id).push(e.network_id)
  }

  const allNodes = []
  const allEdges = []
  let offsetY = 0

  const instIds = new Set([...netByInst.keys()])
  for (const inst of clusterData?.installations || []) {
    if ((inst.guests || []).some((g) => visibleIds.has(g.id))) instIds.add(inst.id)
  }

  for (const instId of instIds) {
    const inst = instOf.get(instId)
    const nets = netByInst.get(instId) || []
    const netIds = new Set(nets.map((n) => n.id))
    const instGuestIds = (inst?.guests || []).map((g) => g.id).filter((id) => visibleIds.has(id))
    const instGuestSet = new Set(instGuestIds)

    // Primär-Bridge je Gast = erste sichtbare Netz-Kante; sonst „ohne Netz".
    const primaryByNet = new Map()
    const unassigned = []
    for (const gid of instGuestIds) {
      const gn = (guestNets.get(gid) || []).filter((nid) => netIds.has(nid))
      if (gn.length) {
        if (!primaryByNet.has(gn[0])) primaryByNet.set(gn[0], [])
        primaryByNet.get(gn[0]).push(gid)
      } else {
        unassigned.push(gid)
      }
    }

    const clusters = nets.map((n) => ({ net: n, guests: primaryByNet.get(n.id) || [] }))
    if (unassigned.length) {
      clusters.push({
        net: { id: `${instId}-nonet`, installation_id: instId, kind: 'none', label: '', scope: 'node', node: null },
        guests: unassigned,
      })
    }
    if (clusters.length === 0) continue

    // Reihenfolge: SDN-VNets (cluster-weit) zuerst, dann nach Gäste-Anzahl
    // absteigend (volle zuerst), leere/„ohne Netz" hinten.
    clusters.sort((a, b) => {
      const an = a.net.kind === 'none' ? 1 : 0
      const bn = b.net.kind === 'none' ? 1 : 0
      if (an !== bn) return an - bn
      const ac = a.net.scope === 'cluster' ? 0 : 1
      const bc = b.net.scope === 'cluster' ? 0 : 1
      if (ac !== bc) return ac - bc
      if (b.guests.length !== a.guests.length) return b.guests.length - a.guests.length
      return String(a.net.label).localeCompare(String(b.net.label))
    })

    // Cluster in „Regale" legen (Umbruch bei SHELF_MAX_W).
    let shelfX = 0
    let shelfY = 0
    let shelfMaxH = 0
    if (inst) allNodes.push(bannerNode(inst, 0, offsetY - BANNER_H - 6))

    for (const c of clusters) {
      const count = c.guests.length
      const cols = count === 0 ? 1 : Math.min(MAX_COLS, Math.max(1, Math.ceil(Math.sqrt(count))))
      const rows = count === 0 ? 0 : Math.ceil(count / cols)
      const gridW = cols * GCW + (cols - 1) * G_GAP_X
      const clusterW = Math.max(gridW, NETW_W)
      const clusterH = NETW_H + (count ? NET_V_GAP + rows * GCH + (rows - 1) * G_GAP_Y : 0)

      if (shelfX > 0 && shelfX + clusterW > SHELF_MAX_W) {
        shelfX = 0
        shelfY += shelfMaxH + CLUSTER_GAP
        shelfMaxH = 0
      }

      const baseY = offsetY + shelfY
      // Bridge mittig über dem Raster.
      allNodes.push({
        id: c.net.id,
        type: 'topoNetwork',
        position: { x: shelfX + (clusterW - NETW_W) / 2, y: baseY },
        data: { network: c.net, stackFilter: filters?.stack },
        sourcePosition: 'bottom',
        targetPosition: 'top',
      })
      const gridLeft = shelfX + (clusterW - gridW) / 2
      c.guests.forEach((gid, i) => {
        const g = guestById.get(gid)
        if (!g) return
        const col = i % cols
        const row = Math.floor(i / cols)
        allNodes.push({
          id: gid,
          type: 'topoGuest',
          position: {
            x: gridLeft + col * (GCW + G_GAP_X),
            y: baseY + NETW_H + NET_V_GAP + row * (GCH + G_GAP_Y),
          },
          data: { guest: g, view: 'network', compact: true },
          sourcePosition: 'bottom',
          targetPosition: 'top',
        })
      })

      shelfX += clusterW + CLUSTER_GAP
      shelfMaxH = Math.max(shelfMaxH, clusterH)
    }

    // Kanten: alle sichtbaren Konnektivitäts-Kanten (Primär kurz innerhalb des
    // Clusters, Sekundär/Multi-NIC als Kreuz-Kante). Standardmäßig dezent; Hover
    // hebt hervor.
    for (const e of conn) {
      if (instGuestSet.has(e.guest_id) && netIds.has(e.network_id)) {
        allEdges.push({
          id: `c-${e.network_id}-${e.guest_id}`,
          source: e.network_id,
          target: e.guest_id,
          type: 'bus',
          style: { ...edgeBase.style, opacity: 0.35 },
        })
      }
    }
    // „Ohne Netz"-Gäste an den synthetischen Header hängen (rein visuelle Gruppierung).
    if (unassigned.length) {
      const noNetId = `${instId}-nonet`
      for (const gid of unassigned) {
        allEdges.push({
          id: `c-${noNetId}-${gid}`,
          source: noNetId,
          target: gid,
          type: 'bus',
          style: { ...edgeBase.style, opacity: 0.18, strokeDasharray: '4 3' },
        })
      }
    }

    offsetY += shelfY + shelfMaxH + INSTALL_GAP + BANNER_H
  }

  return { nodes: allNodes, edges: allEdges }
}

// ── Netz-Board (Boxen statt Graph) ────────────────────────────────────────────
// Alternative, linienfreie Darstellung zum Vergleich: pro Bridge/VNet eine Box
// mit der vollständigen Gästeliste. Multi-Homed-Gäste (Firewalls) erscheinen in
// JEDER Box, an der sie hängen → pro Bridge sofort die komplette Liste, volle
// Namen, keine Kreuz-Linien.

/**
 * @returns {{ installations: Array<{id,name,unreachable,groups:Array<{network,guests}>,noNet:Array}> }}
 */
export function buildNetworkBoard(clusterData, networkData, filters) {
  const networks = networkData?.networks || []
  const edgesConn = networkData?.edges_conn || []

  const visibleGuests = filterGuests(clusterData?.installations, filters)
  const guestById = new Map(visibleGuests.map((g) => [g.id, g]))
  const visibleIds = new Set(visibleGuests.map((g) => g.id))
  const conn = visibleConnEdges(edgesConn, visibleIds)

  // networkId → [guestId] (Mitgliedschaft; Multi-Homed-Gast steht in mehreren).
  const guestsByNet = new Map()
  for (const e of conn) {
    if (!guestsByNet.has(e.network_id)) guestsByNet.set(e.network_id, [])
    guestsByNet.get(e.network_id).push(e.guest_id)
  }

  const netByInst = new Map()
  for (const n of networks) {
    if (!netByInst.has(n.installation_id)) netByInst.set(n.installation_id, [])
    netByInst.get(n.installation_id).push(n)
  }
  const instOf = new Map()
  for (const inst of clusterData?.installations || []) instOf.set(inst.id, inst)

  const instIds = new Set([...netByInst.keys()])
  for (const inst of clusterData?.installations || []) {
    if ((inst.guests || []).some((g) => visibleIds.has(g.id))) instIds.add(inst.id)
  }

  const installations = []
  for (const instId of instIds) {
    const inst = instOf.get(instId)
    const nets = netByInst.get(instId) || []
    const netIdSet = new Set(nets.map((n) => n.id))
    const instGuestIds = (inst?.guests || []).map((g) => g.id).filter((id) => visibleIds.has(id))

    const groups = nets.map((n) => ({
      network: n,
      guests: (guestsByNet.get(n.id) || []).map((gid) => guestById.get(gid)).filter(Boolean),
    }))
    groups.sort((a, b) => {
      const ac = a.network.scope === 'cluster' ? 0 : 1
      const bc = b.network.scope === 'cluster' ? 0 : 1
      if (ac !== bc) return ac - bc
      if (b.guests.length !== a.guests.length) return b.guests.length - a.guests.length
      return String(a.network.label).localeCompare(String(b.network.label))
    })

    // Gäste ohne (sichtbare) Netz-Zugehörigkeit in dieser Installation.
    const noNet = instGuestIds
      .filter((id) => {
        const gn = (conn.filter((e) => e.guest_id === id).map((e) => e.network_id)) || []
        return !gn.some((nid) => netIdSet.has(nid))
      })
      .map((id) => guestById.get(id))
      .filter(Boolean)

    installations.push({
      id: instId,
      name: inst?.name || instId,
      unreachable: !!inst?.unreachable,
      nodes: inst?.nodes || [],
      groups,
      noNet,
    })
  }
  return { installations }
}

// ── Abhängigkeits-Sicht (PROJ-96) ─────────────────────────────────────────────
// Gerichteter Graph aus dem lazy /api/topology/dependencies-Endpoint
// ({ guests, edges }). Es werden NUR Knoten gezeigt, die an mindestens einer
// (nach Filter sichtbaren) Kante hängen — isolierte VMs blähen den
// Abhängigkeits-Graph sonst unnötig auf. dagre legt die Knoten Top-Down aus.

const DEP_DIM = { width: 200, height: 60 }
const DEP_STROKE = 'var(--portal-info, #3b82f6)'
const DEP_STALE_STROKE = 'var(--portal-text3, #9ca3af)'

/** Filtert einen DepGuest gegen die Toolbar-Filter (q/type/status; stack n/a). */
function depGuestMatches(g, filters) {
  if (!filters) return true
  if (filters.type && filters.type !== 'all' && g.type !== filters.type) return false
  if (filters.status && filters.status !== 'all') {
    const st = g.status === 'running' ? 'running' : 'stopped'
    if (st !== filters.status) return false
  }
  if (filters.q) {
    const q = filters.q.toLowerCase()
    if (!(String(g.label || '').toLowerCase().includes(q) || String(g.vmid).includes(q))) return false
  }
  return true
}

/**
 * @param {object} depData  Antwort von /api/topology/dependencies ({guests, edges})
 * @param {object} filters  { status, type, stack, q }
 * @returns {{nodes:Array, edges:Array}}
 */
export function buildDependencyFlow(depData, filters) {
  const guests = depData?.guests || []
  const rawEdges = depData?.edges || []

  const guestById = new Map(guests.map((g) => [g.id, g]))
  const visible = new Set(guests.filter((g) => depGuestMatches(g, filters)).map((g) => g.id))

  // Nur Kanten, deren beide Endpunkte sichtbar sind (Backend filtert bereits
  // RBAC; hier zusätzlich der clientseitige Toolbar-Filter, Defense-in-Depth).
  const edges = rawEdges.filter((e) => visible.has(e.source_id) && visible.has(e.target_id))

  // Knoten = nur die, die an mindestens einer sichtbaren Kante hängen.
  const usedIds = new Set()
  for (const e of edges) { usedIds.add(e.source_id); usedIds.add(e.target_id) }
  const nodeGuests = guests.filter((g) => usedIds.has(g.id))

  if (nodeGuests.length === 0) return { nodes: [], edges: [] }

  const layoutNodes = nodeGuests.map((g) => ({ id: g.id, width: DEP_DIM.width, height: DEP_DIM.height }))
  const layoutEdges = edges.map((e) => ({ source: e.source_id, target: e.target_id }))
  const pos = layoutGraph(layoutNodes, layoutEdges, { rankdir: 'TB', ranksep: 90, nodesep: 36 })

  const nodes = nodeGuests.map((g) => {
    const p = pos.get(g.id) || { x: 0, y: 0 }
    return {
      id: g.id,
      type: 'topoDepGuest',
      position: { x: p.x, y: p.y },
      data: { guest: guestById.get(g.id) },
      sourcePosition: 'bottom',
      targetPosition: 'top',
    }
  })

  const flowEdges = edges.map((e) => {
    const stroke = e.stale ? DEP_STALE_STROKE : DEP_STROKE
    return {
      id: `dep-${e.id}`,
      source: e.source_id,
      target: e.target_id,
      type: 'dependency',
      data: { label: e.dep_label || null },
      markerEnd: { type: 'arrowclosed', width: 16, height: 16, color: stroke },
      style: e.stale
        ? { stroke, strokeWidth: 1.5, strokeDasharray: '5 4', opacity: 0.6 }
        : { stroke, strokeWidth: 1.5 },
    }
  })

  return { nodes, edges: flowEdges }
}

/** Anzahl der Roh-Knoten (für die Performance-Warnung AC-PERF-2). */
export function totalNodeCount(clusterData, networkData) {
  let n = 0
  for (const inst of clusterData?.installations || []) {
    n += (inst.nodes || []).length + (inst.guests || []).length
  }
  n += (networkData?.networks || []).length
  return n
}
