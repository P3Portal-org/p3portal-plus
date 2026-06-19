// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-91: deklarative Stack-Firewall – Gast-FW-Sektion (enabled/policy/rules),
// Regel-Editor (Reuse PROJ-90-Felder ohne pos), Stack-Security-Group-Karte,
// AC-ENABLE-2-Warnung, Plan-Hinweis (§H) und der Mutations-Block-Error-Mapper.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { I18nextProvider } from 'react-i18next'
import i18n from '../../i18n'

const h = vi.hoisted(() => ({ planResult: null }))

vi.mock('./hooks', () => ({
  useNodeVmOptions: vi.fn(() => ({ data: { bridges: ['vmbr0'], cpu_types: [], tags: [] } })),
  useImageStorages: vi.fn(() => ({ data: [] })),
  useLxcTemplates: vi.fn(() => ({ data: [] })),
  useStackPlan: () => ({
    mutateAsync: () => Promise.resolve(h.planResult),
    isPending: false,
  }),
  useDeployStack: () => ({ mutateAsync: () => Promise.resolve({ kind: 'ok', data: { job_id: 'j1' } }), isPending: false }),
  useDestroyStack: () => ({ mutateAsync: () => Promise.resolve({ kind: 'ok', data: { job_id: 'j1' } }), isPending: false }),
}))
vi.mock('react-router-dom', () => ({ useNavigate: () => () => {} }))
vi.mock('./StackDeployLogView', () => ({ default: () => null }))

import StackFormEditor from './StackFormEditor'
import StackResourceCard from './StackResourceCard'
import StackGuestFirewall from './StackGuestFirewall'
import StackPlanModal from './StackPlanModal'
import { firewallErrMsg } from '../../api/firewall'

function wrap(ui) {
  return render(<I18nextProvider i18n={i18n}>{ui}</I18nextProvider>)
}

const VM = {
  type: 'vm', name: 'web', node: 'pve-01', template: 'debian-12', count: 1,
  cores: 2, sockets: 1, memory: 2048, disk: 32, cpu_type: 'host',
  network: { bridge: 'vmbr0' }, tags: [], start_after_create: true,
}

beforeEach(() => {
  vi.clearAllMocks()
  h.planResult = null
})

// ── StackGuestFirewall: enabled / policy / inert-warning (AC-MODEL/ENABLE) ─────

describe('StackGuestFirewall', () => {
  it('enables the firewall and emits a firewall block', () => {
    const onChange = vi.fn()
    wrap(<StackGuestFirewall t={i18n.t} firewall={undefined} onChange={onChange} />)
    fireEvent.click(screen.getByRole('checkbox'))
    expect(onChange).toHaveBeenCalled()
    expect(onChange.mock.calls[0][0]).toEqual({ enabled: true })
  })

  it('emits undefined when the block becomes empty (byte-genau, AC-MODEL-6)', () => {
    const onChange = vi.fn()
    wrap(<StackGuestFirewall t={i18n.t} firewall={{ enabled: true }} onChange={onChange} />)
    fireEvent.click(screen.getByRole('checkbox')) // enabled true → false, no other fields
    expect(onChange).toHaveBeenCalledWith(undefined)
  })

  it('sets a default policy_out', () => {
    const onChange = vi.fn()
    wrap(<StackGuestFirewall t={i18n.t} firewall={{ enabled: true }} onChange={onChange} />)
    const selects = screen.getAllByRole('combobox')
    // policy_in (0) + policy_out (1)
    fireEvent.change(selects[1], { target: { value: 'DROP' } })
    expect(onChange.mock.calls[0][0]).toMatchObject({ enabled: true, policy_out: 'DROP' })
  })

  it('warns when rules/policies are defined but firewall is not enabled (AC-ENABLE-2)', () => {
    wrap(<StackGuestFirewall t={i18n.t} firewall={{ enabled: false, policy_out: 'DROP', rules: [] }} onChange={vi.fn()} />)
    expect(screen.getByText(/greifen nicht|do not apply/i)).toBeInTheDocument()
  })

  it('does not warn when the firewall is enabled', () => {
    wrap(<StackGuestFirewall t={i18n.t} firewall={{ enabled: true, policy_out: 'DROP', rules: [] }} onChange={vi.fn()} />)
    expect(screen.queryByText(/greifen nicht|do not apply/i)).not.toBeInTheDocument()
  })

  it('opens the rule editor and adds a declarative rule (AC-RULE)', () => {
    const onChange = vi.fn()
    wrap(<StackGuestFirewall t={i18n.t} firewall={{ enabled: true }} onChange={onChange} />)
    fireEvent.click(screen.getByText(/Regel hinzufügen|Add rule/i))
    // modal open: direction default out, action ACCEPT; set a dport
    const dport = screen.getByPlaceholderText('443')
    fireEvent.change(dport, { target: { value: '443' } })
    const proto = screen.getByLabelText(/Protokoll$|^Protocol$/i)
    fireEvent.change(proto, { target: { value: 'tcp' } })
    fireEvent.click(screen.getByRole('button', { name: /^Regel hinzufügen$|^Add rule$/i }))
    expect(onChange).toHaveBeenCalled()
    const next = onChange.mock.calls[onChange.mock.calls.length - 1][0]
    expect(next.rules).toHaveLength(1)
    expect(next.rules[0]).toMatchObject({ type: 'out', action: 'ACCEPT', proto: 'tcp', dport: '443' })
    expect(next.rules[0]).not.toHaveProperty('pos')
  })
})

// ── StackResourceCard: collapsible guest firewall block ───────────────────────

describe('StackResourceCard – guest firewall block', () => {
  it('renders the firewall section in a VM card (collapsed by default)', () => {
    wrap(<StackResourceCard
      resource={VM} index={0} total={1}
      onChange={vi.fn()} onRemove={vi.fn()} onMove={vi.fn()} onDuplicate={vi.fn()}
      nodeOptions={['pve-01']} templateOptions={[]} />)
    // section toggle present
    expect(screen.getByText(/^Firewall$/i)).toBeInTheDocument()
    // collapsed → enabled checkbox not yet shown
    expect(screen.queryByText(/Firewall am Gast aktivieren|Enable firewall on the guest/i)).not.toBeInTheDocument()
  })

  it('expands the firewall section on click', () => {
    wrap(<StackResourceCard
      resource={VM} index={0} total={1}
      onChange={vi.fn()} onRemove={vi.fn()} onMove={vi.fn()} onDuplicate={vi.fn()}
      nodeOptions={['pve-01']} templateOptions={[]} />)
    fireEvent.click(screen.getByText(/^Firewall$/i))
    expect(screen.getByText(/Firewall am Gast aktivieren|Enable firewall on the guest/i)).toBeInTheDocument()
  })

  it('shows the section pre-expanded when a firewall block exists', () => {
    wrap(<StackResourceCard
      resource={{ ...VM, firewall: { enabled: true, rules: [] } }} index={0} total={1}
      onChange={vi.fn()} onRemove={vi.fn()} onMove={vi.fn()} onDuplicate={vi.fn()}
      nodeOptions={['pve-01']} templateOptions={[]} />)
    expect(screen.getByText(/Firewall am Gast aktivieren|Enable firewall on the guest/i)).toBeInTheDocument()
  })
})

// ── StackFormEditor: stack-owned security groups section (AC-MODEL-3/4) ────────

describe('StackFormEditor – security groups section', () => {
  it('shows the empty state and adds a first security group', () => {
    const onChange = vi.fn()
    wrap(<StackFormEditor model={{ name: 's', resources: [], networks: [], security_groups: [] }} onChange={onChange} />)
    fireEvent.click(screen.getByText(/Erste Security-Group hinzufügen|Add first security group/i))
    expect(onChange).toHaveBeenCalled()
    const next = onChange.mock.calls[0][0]
    expect(next.security_groups).toHaveLength(1)
    expect(next.security_groups[0]).toMatchObject({ name: '' })
  })

  it('flags an invalid security-group name (>10 chars)', () => {
    wrap(<StackFormEditor
      model={{ name: 's', resources: [], security_groups: [{ name: 'way-too-long-name', rules: [] }] }}
      onChange={vi.fn()} />)
    expect(screen.getByText(/≤10/i)).toBeInTheDocument()
  })

  it('removes the only security group and clears the list (undefined)', () => {
    const onChange = vi.fn()
    wrap(<StackFormEditor
      model={{ name: 's', resources: [], security_groups: [{ name: 'web', rules: [] }] }}
      onChange={onChange} />)
    fireEvent.click(screen.getByLabelText(/Security-Group entfernen|Remove security group/i))
    expect(onChange.mock.calls[0][0].security_groups).toBeUndefined()
  })

  it('offers stack-declared SG names in a guest group-rule action dropdown', () => {
    // SG "web-egress" declared → guest group rule should list it.
    wrap(<StackFormEditor
      model={{ name: 's', resources: [{ ...VM, firewall: { enabled: true, rules: [{ type: 'group', action: 'web-egress' }] } }], security_groups: [{ name: 'web-egress', rules: [] }] }}
      onChange={vi.fn()} />)
    // the guest firewall section is pre-expanded (has a rule); its rule summary shows the group ref
    expect(screen.getByText(/group → web-egress/i)).toBeInTheDocument()
  })
})

// ── StackPlanModal: informative firewall hint (§H) ────────────────────────────

describe('StackPlanModal – firewall hint', () => {
  it('shows the informative firewall hint when guests/groups are present', async () => {
    h.planResult = {
      plan_token: 'tok', operation: 'apply',
      summary: { create: 1, change: 0, destroy: 0, replace: 0, resources: [] },
      destructive_disk_changes: [],
    }
    wrap(<StackPlanModal stackId={7} stackName="mystack" operation="apply"
      firewallHint={{ guests: 2, groups: 1 }} onClose={vi.fn()} />)
    expect(await screen.findByText(/Firewall:/i)).toBeInTheDocument()
  })

  it('shows no firewall hint when there are no firewall artifacts', async () => {
    h.planResult = {
      plan_token: 'tok', operation: 'apply',
      summary: { create: 1, change: 0, destroy: 0, replace: 0, resources: [] },
      destructive_disk_changes: [],
    }
    wrap(<StackPlanModal stackId={7} stackName="mystack" operation="apply"
      firewallHint={null} onClose={vi.fn()} />)
    expect(await screen.findByText(/erstellen|create/i)).toBeInTheDocument()
    expect(screen.queryByText(/^Firewall:/i)).not.toBeInTheDocument()
  })
})

// ── Mutations-Block error mapper (AC-MUT-1) ───────────────────────────────────

describe('firewallErrMsg – guest_firewall_managed_by_stack (AC-MUT-1)', () => {
  it('maps the 409 object to a clear "edit via the stack definition" message', () => {
    const err = { response: { status: 409, data: { detail: { error: 'guest_firewall_managed_by_stack', stack_id: 5, stack_name: 'mystack' } } } }
    const msg = firewallErrMsg(err)
    expect(msg).toMatch(/Stack/)
    expect(msg).toMatch(/mystack/)
    expect(msg).toMatch(/Stack-Definition/)
  })

  it('still maps a plain 409 (name collision) generically', () => {
    const err = { response: { status: 409, data: { detail: 'name already taken' } } }
    expect(firewallErrMsg(err)).toBe('name already taken')
  })
})
