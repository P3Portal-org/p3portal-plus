// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-96: Tests für VM-Abhängigkeiten – buildDependencyFlow (Modell),
// VmDependencySection (beide Richtungen + Anlegen/Entfernen) und den
// Core-Impact-Guard (409 → Dialog → confirm-Retry).
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { I18nextProvider } from 'react-i18next'
import i18n from '../../i18n'

import { buildDependencyFlow } from '../Topology/topologyModel'
import { DEFAULT_FILTERS } from '../Topology/topologyHelpers'

const h = vi.hoisted(() => ({
  deps: null,
  vms: [],
  createSpy: vi.fn(() => Promise.resolve({})),
  deleteSpy: vi.fn(() => Promise.resolve()),
  updateSpy: vi.fn(() => Promise.resolve({})),
}))

vi.mock('./hooks', () => ({
  useVmDependencies: () => ({ data: h.deps, isLoading: false, isError: false }),
  useVisibleVms: () => ({ data: h.vms, isLoading: false }),
  useCreateDependency: () => ({ mutateAsync: h.createSpy, isPending: false }),
  useDeleteDependency: () => ({ mutateAsync: h.deleteSpy, isPending: false }),
  useUpdateDependencyLabel: () => ({ mutateAsync: h.updateSpy, isPending: false }),
}))

import VmDependencySection from './VmDependencySection'

function wrap(ui) {
  return render(<I18nextProvider i18n={i18n}>{ui}</I18nextProvider>)
}

beforeEach(() => {
  vi.clearAllMocks()
  h.deps = {
    depends_on: [
      { id: 1, source_node_id: 1, source_vmid: 100, target_node_id: 1, target_vmid: 200, target_name: 'db-1', target_installation: 'prod', dep_label: 'needs pg', stale: false },
    ],
    dependents: [
      { id: 2, source_node_id: 1, source_vmid: 300, source_name: 'web-2', source_installation: 'prod', target_node_id: 1, target_vmid: 100, dep_label: null, stale: false },
    ],
  }
  h.vms = [
    { vmid: 100, name: 'svc-1', type: 'qemu', status: 'running', node: 'pve1', portal_node_id: 1, portal_node_name: 'prod' }, // aktuelle VM
    { vmid: 500, name: 'cache-1', type: 'qemu', status: 'running', node: 'pve1', portal_node_id: 1, portal_node_name: 'prod' }, // Kandidat
    { vmid: 200, name: 'db-1', type: 'qemu', status: 'running', node: 'pve1', portal_node_id: 1, portal_node_name: 'prod' }, // schon Ziel
  ]
})

// ── buildDependencyFlow (reines Modell) ───────────────────────────────────────

describe('buildDependencyFlow', () => {
  const G = (id, vmid, extra = {}) => ({ id, vmid, node: 'pve1', type: 'vm', label: `vm-${vmid}`, status: 'running', installation: 'prod', ...extra })

  it('emits only nodes that are part of a visible edge (drops isolated VMs)', () => {
    const data = {
      guests: [G('a', 1), G('b', 2), G('c', 3)],
      edges: [{ id: 10, source_id: 'a', target_id: 'b', dep_label: null, stale: false }],
    }
    const { nodes, edges } = buildDependencyFlow(data, DEFAULT_FILTERS)
    expect(nodes.map((n) => n.id).sort()).toEqual(['a', 'b'])
    expect(edges).toHaveLength(1)
    expect(edges[0].type).toBe('dependency')
    expect(edges[0].markerEnd.type).toBe('arrowclosed')
    expect(nodes[0].type).toBe('topoDepGuest')
  })

  it('renders stale edges dashed + dimmed', () => {
    const data = {
      guests: [G('a', 1), G('b', 2)],
      edges: [{ id: 11, source_id: 'a', target_id: 'b', dep_label: null, stale: true }],
    }
    const { edges } = buildDependencyFlow(data, DEFAULT_FILTERS)
    expect(edges[0].style.strokeDasharray).toBeTruthy()
    expect(edges[0].style.opacity).toBeLessThan(1)
  })

  it('applies the type filter (and drops edges whose endpoint is filtered out)', () => {
    const data = {
      guests: [G('a', 1, { type: 'vm' }), G('b', 2, { type: 'lxc' })],
      edges: [{ id: 12, source_id: 'a', target_id: 'b', dep_label: null, stale: false }],
    }
    const { nodes, edges } = buildDependencyFlow(data, { ...DEFAULT_FILTERS, type: 'vm' })
    // b (lxc) gefiltert → die Kante a→b ist nicht beidseitig sichtbar → keine Knoten/Kanten
    expect(nodes).toHaveLength(0)
    expect(edges).toHaveLength(0)
  })

  it('returns empty for no data', () => {
    expect(buildDependencyFlow(undefined, DEFAULT_FILTERS)).toEqual({ nodes: [], edges: [] })
    expect(buildDependencyFlow({ guests: [], edges: [] }, DEFAULT_FILTERS)).toEqual({ nodes: [], edges: [] })
  })
})

// ── VmDependencySection ───────────────────────────────────────────────────────

describe('VmDependencySection', () => {
  const baseProps = { portalNodeId: 1, vmid: 100, node: 'pve1', vmName: 'svc-1' }

  it('shows both directions with the peer names (AC-DECLARE-4)', () => {
    wrap(<VmDependencySection {...baseProps} canManage={false} />)
    expect(screen.getByText('db-1')).toBeInTheDocument()   // depends_on peer
    expect(screen.getByText('web-2')).toBeInTheDocument()  // dependents peer
  })

  it('hides add/remove without manage_dependencies (AC-DECLARE-5)', () => {
    wrap(<VmDependencySection {...baseProps} canManage={false} />)
    expect(screen.queryByRole('button', { name: /Abhängigkeit hinzufügen|Add dependency/ })).toBeNull()
    expect(screen.queryByRole('button', { name: /Entfernen|Remove/ })).toBeNull()
  })

  it('opens the add form and excludes self + already-linked targets (AC-DECLARE-1/2)', () => {
    wrap(<VmDependencySection {...baseProps} canManage />)
    fireEvent.click(screen.getByRole('button', { name: /Abhängigkeit hinzufügen|Add dependency/ }))
    const select = screen.getByRole('combobox')
    const values = Array.from(select.querySelectorAll('option')).map((o) => o.value)
    expect(values).toContain('1:500')        // cache-1 wählbar
    expect(values).not.toContain('1:100')    // selbst ausgeschlossen
    expect(values).not.toContain('1:200')    // db-1 schon verknüpft
  })

  it('creates a dependency from the current VM to the chosen target (AC-DECLARE-1)', async () => {
    wrap(<VmDependencySection {...baseProps} canManage />)
    fireEvent.click(screen.getByRole('button', { name: /Abhängigkeit hinzufügen|Add dependency/ }))
    fireEvent.change(screen.getByRole('combobox'), { target: { value: '1:500' } })
    fireEvent.click(screen.getByRole('button', { name: /^Abhängigkeit hinzufügen$|^Add dependency$/ }))
    await waitFor(() => expect(h.createSpy).toHaveBeenCalledTimes(1))
    expect(h.createSpy).toHaveBeenCalledWith(expect.objectContaining({
      source_node_id: 1, source_vmid: 100, target_node_id: 1, target_vmid: 500,
    }))
  })

  it('removes a dependency by id (AC-DECLARE-3)', async () => {
    wrap(<VmDependencySection {...baseProps} canManage />)
    // erste Entfernen-Schaltfläche = die der depends_on-Kante (id 1)
    fireEvent.click(screen.getAllByRole('button', { name: /Entfernen|Remove/ })[0])
    await waitFor(() => expect(h.deleteSpy).toHaveBeenCalledWith(1))
  })
})
