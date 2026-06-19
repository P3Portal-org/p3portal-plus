// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-82: Stacks-Multi-Disk – Resource-Card-Disk-Sektion + Plan-Modal-Datenverlust.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { I18nextProvider } from 'react-i18next'
import i18n from '../../i18n'

// Shared, per-test-mutable plan for the StackPlanModal mock (vi.mock is hoisted).
const h = vi.hoisted(() => ({ plan: null }))

vi.mock('./hooks', () => ({
  useNodeVmOptions: vi.fn(() => ({ data: undefined })),
  useImageStorages: vi.fn(() => ({ data: [{ name: 'ceph' }, { name: 'local-lvm' }] })),
  useStackPlan: () => ({ mutateAsync: () => Promise.resolve(h.plan), isPending: false }),
  useDeployStack: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDestroyStack: () => ({ mutateAsync: vi.fn(), isPending: false }),
}))
vi.mock('react-router-dom', () => ({ useNavigate: () => () => {} }))
vi.mock('./StackDeployLogView', () => ({ default: () => null }))

import StackResourceCard from './StackResourceCard'
import StackPlanModal from './StackPlanModal'

function wrap(ui) {
  return render(<I18nextProvider i18n={i18n}>{ui}</I18nextProvider>)
}

const VM = {
  type: 'vm', name: 'db', node: 'pve-01', template: 'debian-12', count: 1,
  cores: 2, sockets: 1, memory: 2048, disk: 32, cpu_type: 'host',
  network: { bridge: 'vmbr0' }, tags: [], start_after_create: true,
}

beforeEach(() => {
  vi.clearAllMocks()
  h.plan = {
    plan_token: 'tok', operation: 'apply',
    summary: { create: 0, change: 1, destroy: 0, replace: 0, resources: [] },
    destructive_disk_changes: [],
  }
})

// ── StackResourceCard: extra-disks section (AC-UI-1/2) ────────────────────────

describe('StackResourceCard – extra disks', () => {
  const card = (resource, onChange) =>
    wrap(<StackResourceCard resource={resource} index={0} total={1}
      onChange={onChange} onRemove={vi.fn()} onMove={vi.fn()} onDuplicate={vi.fn()} nodeOptions={[]} templateOptions={[]} />)

  it('shows empty state when no extra disks', () => {
    card(VM, vi.fn())
    expect(screen.getByText(/keine zusätzlichen festplatten|no additional disks/i)).toBeInTheDocument()
  })

  it('adds a disk with auto-computed scsi1 interface (root is scsi0)', () => {
    const onChange = vi.fn()
    card(VM, onChange)
    fireEvent.click(screen.getByRole('button', { name: /festplatte|disk/i }))
    expect(onChange).toHaveBeenCalledWith(0, expect.objectContaining({
      extra_disks: [{ interface: 'scsi1', size: 32, datastore: '' }],
    }))
  })

  it('computes scsi2 for a second scsi disk', () => {
    const onChange = vi.fn()
    card({ ...VM, extra_disks: [{ interface: 'scsi1', size: 100, datastore: 'ceph' }] }, onChange)
    fireEvent.click(screen.getByRole('button', { name: /^\+ (festplatte|disk)/i }))
    expect(onChange).toHaveBeenCalledWith(0, expect.objectContaining({
      extra_disks: expect.arrayContaining([
        { interface: 'scsi1', size: 100, datastore: 'ceph' },
        { interface: 'scsi2', size: 32, datastore: '' },
      ]),
    }))
  })

  it('renders an existing disk (datastore + interface) and removes it', () => {
    const onChange = vi.fn()
    card({ ...VM, extra_disks: [{ interface: 'scsi1', size: 100, datastore: 'ceph' }] }, onChange)
    expect(screen.getByDisplayValue('ceph')).toBeInTheDocument()      // datastore select
    expect(screen.getByText('scsi1')).toBeInTheDocument()             // interface label
    fireEvent.click(screen.getByLabelText(/festplatte entfernen|remove disk/i))
    expect(onChange).toHaveBeenCalledWith(0, expect.objectContaining({ extra_disks: [] }))
  })

  it('bus change recomputes a stable interface (scsi1 → virtio0)', () => {
    const onChange = vi.fn()
    card({ ...VM, extra_disks: [{ interface: 'scsi1', size: 50, datastore: 'ceph' }] }, onChange)
    const busSelect = screen.getByDisplayValue('scsi')   // bus dropdown (not datastore 'ceph')
    fireEvent.change(busSelect, { target: { value: 'virtio' } })
    expect(onChange).toHaveBeenCalledWith(0, expect.objectContaining({
      extra_disks: [{ interface: 'virtio0', size: 50, datastore: 'ceph' }],
    }))
  })
})

// ── StackPlanModal: destructive disk confirmation (AC-REMOVE) ──────────────────

describe('StackPlanModal – disk-loss confirmation', () => {
  it('requires typing the stack name when disks would be lost', async () => {
    h.plan.destructive_disk_changes = [
      { vm: 'db', interface: 'scsi1', reason: 'removed', old_size: 100 },
    ]
    wrap(<StackPlanModal stackId={1} stackName="dbstack" operation="apply" onClose={vi.fn()} />)
    // wait for plan to resolve → review phase
    expect(await screen.findByText(/unwiederbringlich|permanently/i)).toBeInTheDocument()
    const apply = screen.getByRole('button', { name: /anwenden|^apply$/i })
    expect(apply).toBeDisabled()
    fireEvent.change(screen.getByPlaceholderText('dbstack'), { target: { value: 'dbstack' } })
    expect(apply).not.toBeDisabled()
  })

  it('does not gate apply for pure additions (no destructive changes)', async () => {
    h.plan.destructive_disk_changes = []
    h.plan.summary = { create: 1, change: 0, destroy: 0, replace: 0, resources: [] }
    wrap(<StackPlanModal stackId={1} stackName="dbstack" operation="apply" onClose={vi.fn()} />)
    const apply = await screen.findByRole('button', { name: /anwenden|^apply$/i })
    expect(apply).not.toBeDisabled()
    expect(screen.queryByText(/unwiederbringlich|permanently/i)).not.toBeInTheDocument()
  })
})
