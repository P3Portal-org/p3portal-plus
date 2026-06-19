// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-87: Stacks-Netzwerk-Erstellung – Editor-Sektion, Bridge-Karte,
// Resource-Bridge-Dropdown (stack-Netze) und Plan-Modal-409 (network_in_use).
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { I18nextProvider } from 'react-i18next'
import i18n from '../../i18n'

// Per-test-mutable plan-result/-error for the StackPlanModal mock (vi.mock is hoisted).
const h = vi.hoisted(() => ({ planResult: null, planError: null, deployError: null, deployResult: null }))

function deployHook() {
  return {
    mutateAsync: () => (h.deployError
      ? Promise.reject(h.deployError)
      : Promise.resolve(h.deployResult || { kind: 'ok', data: { job_id: 'j1' } })),
    isPending: false,
  }
}

vi.mock('./hooks', () => ({
  useNodeVmOptions: vi.fn(() => ({ data: { bridges: ['vmbr0', 'vmbr1'], cpu_types: [], tags: [] } })),
  useImageStorages: vi.fn(() => ({ data: [] })),
  useLxcTemplates: vi.fn(() => ({ data: [] })),
  useStackPlan: () => ({
    mutateAsync: () => (h.planError ? Promise.reject(h.planError) : Promise.resolve(h.planResult)),
    isPending: false,
  }),
  useDeployStack: deployHook,
  useDestroyStack: deployHook,
}))
vi.mock('react-router-dom', () => ({ useNavigate: () => () => {} }))
vi.mock('./StackDeployLogView', () => ({ default: () => null }))

import StackFormEditor from './StackFormEditor'
import StackResourceCard from './StackResourceCard'
import StackPlanModal from './StackPlanModal'

function wrap(ui) {
  return render(<I18nextProvider i18n={i18n}>{ui}</I18nextProvider>)
}

const VM = {
  type: 'vm', name: 'web', node: 'pve-01', template: 'debian-12', count: 1,
  cores: 2, sockets: 1, memory: 2048, disk: 32, cpu_type: 'host',
  network: { bridge: 'vmbr0' }, tags: [], start_after_create: true,
}
const BRIDGE = { kind: 'bridge', name: 'vmbr10', node: 'pve-01', vlan_aware: false }
const VNET = {
  kind: 'vnet', name: 'vnet0', zone: 'zone0',
  subnet_cidr: '10.10.0.0/24', subnet_gateway: '10.10.0.1', snat: false,
}

beforeEach(() => {
  vi.clearAllMocks()
  h.planResult = null
  h.planError = null
  h.deployError = null
  h.deployResult = null
})

// ── StackFormEditor: networks section (AC-MODEL/BRIDGE) ───────────────────────

describe('StackFormEditor – networks section', () => {
  it('shows empty state and adds a first bridge network', () => {
    const onChange = vi.fn()
    wrap(<StackFormEditor model={{ name: 's', resources: [], networks: [] }} onChange={onChange} />)
    const addBtn = screen.getByText(/erstes netz hinzufügen|add first network/i)
    fireEvent.click(addBtn)
    expect(onChange).toHaveBeenCalled()
    const next = onChange.mock.calls[0][0]
    expect(next.networks).toHaveLength(1)
    expect(next.networks[0].kind).toBe('bridge')
  })

  it('offers an enabled SDN-VNet option and switches to a vnet skeleton (PROJ-89)', () => {
    const onChange = vi.fn()
    wrap(<StackFormEditor model={{ name: 's', resources: [], networks: [BRIDGE] }} onChange={onChange} />)
    // bridge card title visible
    expect(screen.getAllByText(/^Bridge$/i).length).toBeGreaterThan(0)
    // vnet kind option exists AND is now selectable (no longer disabled)
    const vnetOpt = screen.getByRole('option', { name: /SDN.?VNet/i })
    expect(vnetOpt).not.toBeDisabled()
    // switching the type resets the card to a clean vnet skeleton
    const kindSelect = screen.getByDisplayValue(/Node.?Bridge|Bridge/i)
    fireEvent.change(kindSelect, { target: { value: 'vnet' } })
    expect(onChange).toHaveBeenCalled()
    const next = onChange.mock.calls[onChange.mock.calls.length - 1][0]
    expect(next.networks[0].kind).toBe('vnet')
    expect(next.networks[0].snat).toBe(false)
    expect(next.networks[0]).toHaveProperty('zone')
    expect(next.networks[0]).not.toHaveProperty('vlan_aware') // bridge field gone
  })

  it('renders the SDN-VNet card with zone, subnet and SNAT fields (PROJ-89)', () => {
    wrap(<StackFormEditor model={{ name: 's', resources: [], networks: [VNET] }} onChange={vi.fn()} />)
    expect(screen.getByDisplayValue('zone0')).toBeInTheDocument()
    expect(screen.getByDisplayValue('10.10.0.0/24')).toBeInTheDocument()
    expect(screen.getByDisplayValue('10.10.0.1')).toBeInTheDocument()
    // SNAT field label present (contains "SNAT (")
    expect(screen.getByText(/SNAT \(/i)).toBeInTheDocument()
    // cluster-wide warning shown (AC-APPLY-3)
    expect(screen.getByText(/cluster-weit|cluster-wide/i)).toBeInTheDocument()
  })

  it('toggles SNAT on the vnet card (PROJ-89)', () => {
    const onChange = vi.fn()
    wrap(<StackFormEditor model={{ name: 's', resources: [], networks: [VNET] }} onChange={onChange} />)
    const snatLabel = screen.getByText(/SNAT \(/i)
    const snatCheckbox = snatLabel.closest('label').querySelector('input[type=checkbox]')
    fireEvent.click(snatCheckbox)
    const next = onChange.mock.calls[onChange.mock.calls.length - 1][0]
    expect(next.networks[0].snat).toBe(true)
  })

  it('flags an invalid vnet name (not ≤8 alnum) (PROJ-89)', () => {
    wrap(<StackFormEditor
      model={{ name: 's', resources: [], networks: [{ ...VNET, name: 'too-long-name' }] }}
      onChange={vi.fn()} />)
    expect(screen.getByText(/≤8 alphanumeric|≤8 alphanumerische/i)).toBeInTheDocument()
  })

  it('flags an invalid bridge name (not vmbrN)', () => {
    wrap(<StackFormEditor
      model={{ name: 's', resources: [], networks: [{ kind: 'bridge', name: 'eth0', node: 'pve-01' }] }}
      onChange={vi.fn()} />)
    expect(screen.getByText(/vmbrN/i)).toBeInTheDocument()
  })

  it('removes the only network and clears the list (undefined)', () => {
    const onChange = vi.fn()
    wrap(<StackFormEditor model={{ name: 's', resources: [], networks: [BRIDGE] }} onChange={onChange} />)
    fireEvent.click(screen.getByLabelText(/netz entfernen|remove network/i))
    expect(onChange).toHaveBeenCalled()
    // empty list is not persisted (byte-genau for pure VM/LXC stacks)
    expect(onChange.mock.calls[0][0].networks).toBeUndefined()
  })
})

// ── StackResourceCard: bridge dropdown offers stack networks (AC-MODEL-2) ──────

describe('StackResourceCard – bridge dropdown with stack networks', () => {
  it('lists stack-declared bridge names as options', () => {
    wrap(<StackResourceCard
      resource={VM} index={0} total={1}
      onChange={vi.fn()} onRemove={vi.fn()} onMove={vi.fn()} onDuplicate={vi.fn()}
      nodeOptions={['pve-01']} templateOptions={[]} stackNetworks={['vmbr10']} />)
    // the stack-declared network appears as a selectable option in the bridge field
    expect(screen.getByRole('option', { name: 'vmbr10' })).toBeInTheDocument()
  })
})

// ── StackPlanModal: 409 network_in_use + 422 network_name_taken (AC-DES-2) ─────

describe('StackPlanModal – network gates', () => {
  it('renders the foreign-guest block on 409 network_in_use', async () => {
    h.planError = {
      response: {
        status: 409,
        data: { detail: { error: 'network_in_use', networks: { vmbr10: [
          { vmid: 120, name: 'alien', node: 'pve-01', kind: 'qemu' },
        ] } } },
      },
    }
    wrap(<StackPlanModal stackId={7} stackName="mystack" operation="destroy" onClose={vi.fn()} />)
    expect(await screen.findByText(/fremden Gästen|foreign guests/i)).toBeInTheDocument()
    expect(await screen.findByText(/alien/)).toBeInTheDocument()
    expect(await screen.findByText(/vmbr10/)).toBeInTheDocument()
  })

  it('shows a clear message on 422 network_name_taken', async () => {
    h.planError = {
      response: { status: 422, data: { detail: { error: 'network_name_taken', taken: ['vmbr10'] } } },
    }
    wrap(<StackPlanModal stackId={7} stackName="mystack" operation="apply" onClose={vi.fn()} />)
    expect(await screen.findByText(/bereits belegt|already taken/i)).toBeInTheDocument()
  })

  it('renders normally (no network block) for a clean plan', async () => {
    h.planResult = {
      plan_token: 'tok', operation: 'apply',
      summary: { create: 1, change: 0, destroy: 0, replace: 0, resources: [] },
      destructive_disk_changes: [],
    }
    wrap(<StackPlanModal stackId={7} stackName="mystack" operation="apply" onClose={vi.fn()} />)
    expect(await screen.findByText(/erstellen|create/i)).toBeInTheDocument()
    expect(screen.queryByText(/fremden Gästen|foreign guests/i)).not.toBeInTheDocument()
  })

  // ── PROJ-89: pending-SDN hint + sdn_apply_busy ──────────────────────────────

  it('surfaces foreign pending SDN as a non-blocking hint (AC-PENDING-1)', async () => {
    h.planResult = {
      plan_token: 'tok', operation: 'apply',
      summary: { create: 3, change: 0, destroy: 0, replace: 0, resources: [] },
      destructive_disk_changes: [],
      foreign_pending_sdn: [{ kind: 'vnet', name: 'othervnet', state: 'new' }],
    }
    wrap(<StackPlanModal stackId={7} stackName="mystack" operation="apply" onClose={vi.fn()} />)
    expect(await screen.findByText(/committet auch diese|will also commit these/i)).toBeInTheDocument()
    expect(await screen.findByText(/othervnet/)).toBeInTheDocument()
    // hint is informational, the Apply button stays enabled
    const applyBtn = await screen.findByRole('button', { name: /anwenden|^apply$/i })
    expect(applyBtn).not.toBeDisabled()
  })

  it('shows a clear message on 409 sdn_apply_busy when applying (AC-APPLY-1)', async () => {
    h.planResult = {
      plan_token: 'tok', operation: 'apply',
      summary: { create: 1, change: 0, destroy: 0, replace: 0, resources: [] },
      destructive_disk_changes: [],
    }
    h.deployError = { response: { status: 409, data: { detail: 'sdn_apply_busy' } } }
    wrap(<StackPlanModal stackId={7} stackName="mystack" operation="apply" onClose={vi.fn()} />)
    const applyBtn = await screen.findByRole('button', { name: /anwenden|^apply$/i })
    fireEvent.click(applyBtn)
    expect(await screen.findByText(/SDN-Deploy läuft|Another SDN deploy/i)).toBeInTheDocument()
  })
})
