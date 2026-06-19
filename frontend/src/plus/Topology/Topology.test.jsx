// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-75: Tests für die Cluster-Topologie (Modell-Transform + Chrome).
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { I18nextProvider } from 'react-i18next'
import i18n from '../../i18n'

import {
  guestMatchesFilters,
  filterGuests,
  hasActiveFilters,
  cpuPct,
  memPct,
  diskPct,
  visibleConnEdges,
  resourceLevel,
  DEFAULT_FILTERS,
} from './topologyHelpers'
import { buildComputeFlow, buildNetworkFlow, buildNetworkBoard, totalNodeCount } from './topologyModel'
import { layoutGraph, gridLayout } from './layout'
import MiniResourceBar from './MiniResourceBar'
import TopologyEmptyState from './TopologyEmptyState'
import FilterToolbar from './FilterToolbar'

function wrap(ui) {
  return render(<I18nextProvider i18n={i18n}>{ui}</I18nextProvider>)
}

// ── Fixtures (Backend-Antwort-Form, IDs bereits prefixed) ─────────────────────

const CLUSTER = {
  installations: [
    {
      id: 'inst1',
      name: 'produktiv',
      unreachable: false,
      nodes: [{ id: 'inst1-node-pve1', node: 'pve1', label: 'pve1', status: 'online', cpu_count: 8, ram_total: 16e9, disk_total: 0 }],
      guests: [
        { id: 'inst1-vm-101', parent_node_id: 'inst1-node-pve1', node: 'pve1', type: 'vm', label: 'web', vmid: 101, status: 'running', cpu: 0.45, maxcpu: 8, mem: 6e9, maxmem: 16e9, disk: 0, maxdisk: 0, managed_by_stack: 'web', ssh_managed: true, is_template: false },
        { id: 'inst1-lxc-201', parent_node_id: 'inst1-node-pve1', node: 'pve1', type: 'lxc', label: 'ct', vmid: 201, status: 'stopped', cpu: 0, maxcpu: 2, mem: 0, maxmem: 2e9, disk: 5e9, maxdisk: 10e9, managed_by_stack: null, ssh_managed: false, is_template: false },
      ],
    },
    {
      id: 'inst2',
      name: 'lab',
      unreachable: true,
      nodes: [],
      guests: [],
    },
  ],
  stats: { installations: 2, nodes: 1, vms: 1, lxcs: 1, running: 1, stack_managed: 1 },
  stacks: ['web'],
}

const NETWORK = {
  networks: [
    { id: 'inst1-pve1-vmbr0', installation_id: 'inst1', kind: 'node_bridge', label: 'vmbr0', scope: 'node', node: 'pve1', vlan_tag: null, owning_stack: null },
    { id: 'inst1-sdn-vnet5', installation_id: 'inst1', kind: 'sdn_vnet', label: 'vnet5', scope: 'cluster', node: null, vlan_tag: 100, owning_stack: null },
    { id: 'inst1-pve1-stackbr', installation_id: 'inst1', kind: 'stack_bridge', label: 'stackbr', scope: 'node', node: 'pve1', vlan_tag: null, owning_stack: 'web' },
  ],
  edges_conn: [
    { guest_id: 'inst1-vm-101', network_id: 'inst1-pve1-vmbr0' },
    { guest_id: 'inst1-lxc-201', network_id: 'inst1-sdn-vnet5' },
  ],
  unreachable_installations: ['inst2'],
}

// ── Filter-Logik ──────────────────────────────────────────────────────────────

describe('PROJ-75 topologyHelpers – filters', () => {
  const guests = CLUSTER.installations[0].guests

  it('status filter', () => {
    expect(guestMatchesFilters(guests[0], { ...DEFAULT_FILTERS, status: 'running' })).toBe(true)
    expect(guestMatchesFilters(guests[1], { ...DEFAULT_FILTERS, status: 'running' })).toBe(false)
    expect(guestMatchesFilters(guests[1], { ...DEFAULT_FILTERS, status: 'stopped' })).toBe(true)
  })

  it('type filter', () => {
    expect(guestMatchesFilters(guests[0], { ...DEFAULT_FILTERS, type: 'vm' })).toBe(true)
    expect(guestMatchesFilters(guests[0], { ...DEFAULT_FILTERS, type: 'lxc' })).toBe(false)
  })

  it('stack filter (managed / free / by name)', () => {
    expect(guestMatchesFilters(guests[0], { ...DEFAULT_FILTERS, stack: 'managed' })).toBe(true)
    expect(guestMatchesFilters(guests[1], { ...DEFAULT_FILTERS, stack: 'managed' })).toBe(false)
    expect(guestMatchesFilters(guests[1], { ...DEFAULT_FILTERS, stack: 'free' })).toBe(true)
    expect(guestMatchesFilters(guests[0], { ...DEFAULT_FILTERS, stack: 'web' })).toBe(true)
    expect(guestMatchesFilters(guests[1], { ...DEFAULT_FILTERS, stack: 'web' })).toBe(false)
  })

  it('search filter on name + vmid', () => {
    expect(guestMatchesFilters(guests[0], { ...DEFAULT_FILTERS, q: 'web' })).toBe(true)
    expect(guestMatchesFilters(guests[0], { ...DEFAULT_FILTERS, q: '101' })).toBe(true)
    expect(guestMatchesFilters(guests[0], { ...DEFAULT_FILTERS, q: 'zzz' })).toBe(false)
  })

  it('filterGuests across installations', () => {
    expect(filterGuests(CLUSTER.installations, DEFAULT_FILTERS)).toHaveLength(2)
    expect(filterGuests(CLUSTER.installations, { ...DEFAULT_FILTERS, type: 'lxc' })).toHaveLength(1)
  })

  it('hasActiveFilters', () => {
    expect(hasActiveFilters(DEFAULT_FILTERS)).toBe(false)
    expect(hasActiveFilters({ ...DEFAULT_FILTERS, status: 'running' })).toBe(true)
  })
})

// ── Ressourcen-Mathematik ─────────────────────────────────────────────────────

describe('PROJ-75 resource math', () => {
  const [vm, lxc] = CLUSTER.installations[0].guests
  it('cpuPct null when stopped, value when running', () => {
    expect(cpuPct(vm)).toBeCloseTo(45)
    expect(cpuPct(lxc)).toBeNull()
  })
  it('memPct from mem/maxmem', () => {
    expect(memPct(vm)).toBeCloseTo(37.5)
    expect(memPct(lxc)).toBeNull() // stopped
  })
  it('diskPct null when disk 0 (QEMU N/A), value for LXC', () => {
    expect(diskPct(vm)).toBeNull()
    expect(diskPct({ ...lxc, status: 'running' })).toBeCloseTo(50)
  })
  it('resourceLevel thresholds', () => {
    expect(resourceLevel(40)).toBe('success')
    expect(resourceLevel(75)).toBe('warn')
    expect(resourceLevel(90)).toBe('danger')
    expect(resourceLevel(null)).toBe('na')
  })
})

// ── Compute-Flow ──────────────────────────────────────────────────────────────

describe('PROJ-75 buildComputeFlow', () => {
  it('builds node + guest nodes with prefixed ids, banner per installation, one edge per guest', () => {
    const { nodes, edges } = buildComputeFlow(CLUSTER, DEFAULT_FILTERS)
    const ids = nodes.map((n) => n.id)
    expect(ids).toContain('inst1-node-pve1')
    expect(ids).toContain('inst1-vm-101')
    expect(ids).toContain('inst1-lxc-201')
    expect(ids).toContain('banner-inst1')
    // EC-10: ids stay installation-prefixed (no collision)
    expect(nodes.find((n) => n.id === 'inst1-vm-101').type).toBe('topoGuest')
    expect(nodes.find((n) => n.id === 'inst1-node-pve1').type).toBe('topoNode')
    // genau eine Linie Node→Gast je VM (eine Verbindung, ein Andockpunkt)
    expect(edges.filter((e) => e.target === 'inst1-vm-101')).toHaveLength(1)
    expect(edges.some((e) => e.source === 'inst1-node-pve1' && e.target === 'inst1-vm-101')).toBe(true)
  })

  it('filtering removes guests but keeps the node', () => {
    const { nodes } = buildComputeFlow(CLUSTER, { ...DEFAULT_FILTERS, type: 'lxc' })
    const ids = nodes.map((n) => n.id)
    expect(ids).toContain('inst1-node-pve1')
    expect(ids).toContain('inst1-lxc-201')
    expect(ids).not.toContain('inst1-vm-101')
  })

  it('skips the empty/unreachable installation block (no nodes)', () => {
    const { nodes } = buildComputeFlow(CLUSTER, DEFAULT_FILTERS)
    expect(nodes.some((n) => n.id === 'banner-inst2')).toBe(false)
  })

  it('uses bus edges (type "bus") for node→VM connections', () => {
    const { edges } = buildComputeFlow(CLUSTER, DEFAULT_FILTERS)
    expect(edges.length).toBeGreaterThan(0)
    expect(edges.every((e) => e.type === 'bus')).toBe(true)
  })

  it('separates templates into a "Vorlagen" cluster with no bus lines', () => {
    const data = {
      installations: [{
        id: 'inst1', name: 'p', unreachable: false,
        nodes: [{ id: 'inst1-node-pve1', node: 'pve1', label: 'pve1', status: 'online', cpu_count: 8, ram_total: 0, disk_total: 0 }],
        guests: [
          { id: 'inst1-vm-101', parent_node_id: 'inst1-node-pve1', node: 'pve1', type: 'vm', label: 'web', vmid: 101, status: 'running', cpu: 0.1, maxcpu: 2, mem: 1e9, maxmem: 2e9, disk: 0, maxdisk: 0, managed_by_stack: null, ssh_managed: false, is_template: false },
          { id: 'inst1-vm-900', parent_node_id: 'inst1-node-pve1', node: 'pve1', type: 'vm', label: 'tmpl-deb', vmid: 900, status: 'stopped', cpu: 0, maxcpu: 2, mem: 0, maxmem: 2e9, disk: 0, maxdisk: 0, managed_by_stack: null, ssh_managed: false, is_template: true },
        ],
      }],
    }
    const { nodes, edges } = buildComputeFlow(data, DEFAULT_FILTERS)
    // synthetic "Vorlagen" header present
    expect(nodes.some((n) => n.id === 'inst1-templates' && n.data.node.status === 'templates')).toBe(true)
    // template guest is rendered but NOT wired by a bus line
    expect(nodes.some((n) => n.id === 'inst1-vm-900')).toBe(true)
    expect(edges.some((e) => e.target === 'inst1-vm-900')).toBe(false)
    // the real VM still has its bus edge
    expect(edges.some((e) => e.target === 'inst1-vm-101')).toBe(true)
  })

  it('grids many guests under their node into multiple rows (no single wide row)', () => {
    const guests = Array.from({ length: 20 }, (_, i) => ({
      id: `inst1-vm-${100 + i}`, parent_node_id: 'inst1-node-pve1', node: 'pve1',
      type: 'vm', label: `vm-${100 + i}`, vmid: 100 + i, status: 'running',
      cpu: 0.1, maxcpu: 2, mem: 1e9, maxmem: 2e9, disk: 0, maxdisk: 0,
      managed_by_stack: null, ssh_managed: false, is_template: false,
    }))
    const data = { installations: [{ id: 'inst1', name: 'p', unreachable: false, nodes: [{ id: 'inst1-node-pve1', node: 'pve1', label: 'pve1', status: 'online', cpu_count: 8, ram_total: 0, disk_total: 0 }], guests }] }
    const { nodes } = buildComputeFlow(data, DEFAULT_FILTERS)
    const node = nodes.find((n) => n.id === 'inst1-node-pve1')
    const gnodes = nodes.filter((n) => n.type === 'topoGuest')
    // all guests below their node
    expect(gnodes.every((g) => g.position.y > node.position.y)).toBe(true)
    // multiple distinct Y rows (grid), not one single row
    const distinctRows = new Set(gnodes.map((g) => Math.round(g.position.y)))
    expect(distinctRows.size).toBeGreaterThan(1)
  })
})

// ── Network-Flow ──────────────────────────────────────────────────────────────

describe('PROJ-75 buildNetworkFlow', () => {
  it('shows all network nodes incl. isolated stack-bridge (EC-14) and connectivity edges to visible guests', () => {
    const { nodes, edges } = buildNetworkFlow(CLUSTER, NETWORK, DEFAULT_FILTERS)
    const ids = nodes.map((n) => n.id)
    expect(ids).toContain('inst1-pve1-vmbr0')
    expect(ids).toContain('inst1-sdn-vnet5')
    expect(ids).toContain('inst1-pve1-stackbr') // isolated stack-bridge still shown
    // connectivity edge network→guest
    expect(edges.some((e) => e.source === 'inst1-pve1-vmbr0' && e.target === 'inst1-vm-101')).toBe(true)
  })

  it('drops connectivity edges to filtered-out guests (RBAC/filter consistency)', () => {
    // only running → lxc-201 hidden → its edge to vnet5 must be gone
    const { edges } = buildNetworkFlow(CLUSTER, NETWORK, { ...DEFAULT_FILTERS, status: 'running' })
    expect(edges.some((e) => e.target === 'inst1-lxc-201')).toBe(false)
    expect(edges.some((e) => e.target === 'inst1-vm-101')).toBe(true)
  })

  it('uses bus edges (type "bus") for network connectivity too', () => {
    const { edges } = buildNetworkFlow(CLUSTER, NETWORK, DEFAULT_FILTERS)
    expect(edges.length).toBeGreaterThan(0)
    expect(edges.every((e) => e.type === 'bus')).toBe(true)
  })

  it('visibleConnEdges restricts to the visible id set', () => {
    const out = visibleConnEdges(NETWORK.edges_conn, new Set(['inst1-vm-101']))
    expect(out).toHaveLength(1)
    expect(out[0].guest_id).toBe('inst1-vm-101')
  })

  it('clusters guests directly below their primary bridge (Option 2 layout)', () => {
    const { nodes } = buildNetworkFlow(CLUSTER, NETWORK, DEFAULT_FILTERS)
    const vmbr0 = nodes.find((n) => n.id === 'inst1-pve1-vmbr0')
    const web = nodes.find((n) => n.id === 'inst1-vm-101') // primary edge → vmbr0
    // Guest sits BELOW its bridge and is horizontally aligned within the cluster.
    expect(web.position.y).toBeGreaterThan(vmbr0.position.y)
    expect(Math.abs(web.position.x - vmbr0.position.x)).toBeLessThan(60)
  })

  it('multi-NIC guest sits under its first bridge but keeps a secondary edge', () => {
    const NET2 = {
      networks: [
        { id: 'inst1-pve1-vmbr0', installation_id: 'inst1', kind: 'node_bridge', label: 'vmbr0', scope: 'node', node: 'pve1' },
        { id: 'inst1-sdn-vnet5', installation_id: 'inst1', kind: 'sdn_vnet', label: 'vnet5', scope: 'cluster', node: null, vlan_tag: 100 },
      ],
      edges_conn: [
        { guest_id: 'inst1-vm-101', network_id: 'inst1-pve1-vmbr0' },  // primary
        { guest_id: 'inst1-vm-101', network_id: 'inst1-sdn-vnet5' },   // secondary (multi-NIC)
      ],
      unreachable_installations: [],
    }
    const { nodes, edges } = buildNetworkFlow(CLUSTER, NET2, DEFAULT_FILTERS)
    // exactly one guest node for vm-101 (not duplicated)
    expect(nodes.filter((n) => n.id === 'inst1-vm-101')).toHaveLength(1)
    // both connectivity edges present (primary + secondary)
    expect(edges.some((e) => e.source === 'inst1-pve1-vmbr0' && e.target === 'inst1-vm-101')).toBe(true)
    expect(edges.some((e) => e.source === 'inst1-sdn-vnet5' && e.target === 'inst1-vm-101')).toBe(true)
    // guest is clustered under vmbr0 (its first bridge), not vnet5
    const vmbr0 = nodes.find((n) => n.id === 'inst1-pve1-vmbr0')
    const web = nodes.find((n) => n.id === 'inst1-vm-101')
    expect(Math.abs(web.position.x - vmbr0.position.x)).toBeLessThan(60)
  })

  it('guests without a connectivity edge land in a synthetic "no network" cluster', () => {
    const NET3 = {
      networks: [{ id: 'inst1-pve1-vmbr0', installation_id: 'inst1', kind: 'node_bridge', label: 'vmbr0', scope: 'node', node: 'pve1' }],
      edges_conn: [{ guest_id: 'inst1-vm-101', network_id: 'inst1-pve1-vmbr0' }], // lxc-201 has no edge
      unreachable_installations: [],
    }
    const { nodes } = buildNetworkFlow(CLUSTER, NET3, DEFAULT_FILTERS)
    expect(nodes.some((n) => n.id === 'inst1-nonet' && n.data.network.kind === 'none')).toBe(true)
    // the edge-less guest is still shown (not silently dropped)
    expect(nodes.some((n) => n.id === 'inst1-lxc-201')).toBe(true)
  })
})

describe('PROJ-75 buildNetworkBoard (Board view)', () => {
  it('groups guests per network box with full guest objects', () => {
    const { installations } = buildNetworkBoard(CLUSTER, NETWORK, DEFAULT_FILTERS)
    const inst = installations.find((i) => i.id === 'inst1')
    const vmbr0 = inst.groups.find((g) => g.network.id === 'inst1-pve1-vmbr0')
    expect(vmbr0.guests.map((g) => g.id)).toContain('inst1-vm-101')
    expect(vmbr0.guests[0].label).toBe('web') // full guest object, not just id
  })

  it('multi-homed guest appears in EVERY bridge box it connects to', () => {
    const NET_MULTI = {
      networks: [
        { id: 'inst1-pve1-vmbr0', installation_id: 'inst1', kind: 'node_bridge', label: 'vmbr0', scope: 'node', node: 'pve1' },
        { id: 'inst1-sdn-vnet5', installation_id: 'inst1', kind: 'sdn_vnet', label: 'vnet5', scope: 'cluster', node: null },
      ],
      edges_conn: [
        { guest_id: 'inst1-vm-101', network_id: 'inst1-pve1-vmbr0' },
        { guest_id: 'inst1-vm-101', network_id: 'inst1-sdn-vnet5' }, // firewall on both
      ],
      unreachable_installations: [],
    }
    const { installations } = buildNetworkBoard(CLUSTER, NET_MULTI, DEFAULT_FILTERS)
    const inst = installations.find((i) => i.id === 'inst1')
    const inVmbr0 = inst.groups.find((g) => g.network.id === 'inst1-pve1-vmbr0').guests.some((g) => g.id === 'inst1-vm-101')
    const inVnet5 = inst.groups.find((g) => g.network.id === 'inst1-sdn-vnet5').guests.some((g) => g.id === 'inst1-vm-101')
    expect(inVmbr0 && inVnet5).toBe(true) // listed in both boxes
  })

  it('edge-less guests go to noNet; VNets sort first', () => {
    const NET4 = {
      networks: [
        { id: 'inst1-pve1-vmbr0', installation_id: 'inst1', kind: 'node_bridge', label: 'vmbr0', scope: 'node', node: 'pve1' },
        { id: 'inst1-sdn-vnet5', installation_id: 'inst1', kind: 'sdn_vnet', label: 'vnet5', scope: 'cluster', node: null },
      ],
      edges_conn: [{ guest_id: 'inst1-vm-101', network_id: 'inst1-sdn-vnet5' }], // lxc-201 has none
      unreachable_installations: [],
    }
    const { installations } = buildNetworkBoard(CLUSTER, NET4, DEFAULT_FILTERS)
    const inst = installations.find((i) => i.id === 'inst1')
    expect(inst.groups[0].network.scope).toBe('cluster') // VNet sorted first
    expect(inst.noNet.map((g) => g.id)).toContain('inst1-lxc-201')
  })
})

// ── Layout ────────────────────────────────────────────────────────────────────

describe('PROJ-75 layout', () => {
  it('layoutGraph positions every node', () => {
    const pos = layoutGraph(
      [{ id: 'a', width: 100, height: 50 }, { id: 'b', width: 100, height: 50 }],
      [{ source: 'a', target: 'b' }],
    )
    expect(pos.get('a')).toBeDefined()
    expect(pos.get('b')).toBeDefined()
    expect(typeof pos.get('a').x).toBe('number')
  })

  it('gridLayout fallback positions all nodes', () => {
    const pos = gridLayout([{ id: 'a', width: 10, height: 10 }, { id: 'b', width: 10, height: 10 }])
    expect(pos.size).toBe(2)
  })

  it('totalNodeCount counts nodes + guests + networks', () => {
    expect(totalNodeCount(CLUSTER, NETWORK)).toBe(1 + 2 + 3)
  })
})

// ── Chrome-Komponenten ────────────────────────────────────────────────────────

describe('PROJ-75 chrome components', () => {
  it('MiniResourceBar shows N/A when pct is null', () => {
    wrap(<MiniResourceBar label="CPU" pct={null} tooltip="t" naLabel="N/A" />)
    expect(screen.getByText('N/A')).toBeInTheDocument()
  })

  it('TopologyEmptyState (filtered) shows reset button', () => {
    const onReset = vi.fn()
    wrap(<TopologyEmptyState reason="filtered" onResetFilters={onReset} />)
    const btn = screen.getByRole('button')
    fireEvent.click(btn)
    expect(onReset).toHaveBeenCalled()
  })

  it('TopologyEmptyState (no_access) has no reset button', () => {
    wrap(<TopologyEmptyState reason="no_access" />)
    expect(screen.queryByRole('button')).toBeNull()
  })

  it('FilterToolbar view-toggle calls onViewChange', () => {
    const onView = vi.fn()
    wrap(
      <FilterToolbar
        view="compute"
        onViewChange={onView}
        filters={DEFAULT_FILTERS}
        onFiltersChange={() => {}}
        stacks={['web']}
        onRefresh={() => {}}
      />,
    )
    fireEvent.click(screen.getByText(i18n.t('topology.view.network'))) // i18n default de in test env
    expect(onView).toHaveBeenCalledWith('network')
  })
})
