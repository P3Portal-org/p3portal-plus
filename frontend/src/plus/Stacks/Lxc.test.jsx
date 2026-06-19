// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-86: Stacks LXC – Container-Karte (Template/rootfs/swap/unprivileged/
// Features/Mountpoints), Formular „LXC hinzufügen", Cloud-Init „root".
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { I18nextProvider } from 'react-i18next'
import i18n from '../../i18n'

vi.mock('./hooks', () => ({
  useNodeVmOptions: vi.fn(() => ({ data: undefined })),
  useImageStorages: vi.fn(() => ({ data: [{ name: 'local-lvm' }, { name: 'ceph' }] })),
  useLxcTemplates: vi.fn(() => ({
    data: {
      installed: [
        { volid: 'local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst', storage: 'local', portal_node_name: 'pve-01' },
        { volid: 'local:vztmpl/alpine-3.20-default_amd64.tar.xz', storage: 'local', portal_node_name: 'pve-02' },
      ],
    },
  })),
  // CloudInit tab deps (one test renders it):
  useStackCloudInit: vi.fn(() => ({ data: { default: { enabled: false }, overrides: [] }, isLoading: false })),
  usePutStackCloudInit: vi.fn(() => ({ mutateAsync: vi.fn(), isPending: false })),
}))
vi.mock('../../api/profile', () => ({ getSshJobKeyStatus: () => Promise.resolve({ has_key: false }) }))
// CloudInit tab reads the profile key via a direct useQuery → stub it out.
vi.mock('@tanstack/react-query', () => ({ useQuery: () => ({ data: undefined }) }))

import StackResourceCard from './StackResourceCard'
import StackFormEditor from './StackFormEditor'
import StackCloudInitTab from './StackCloudInitTab'

function wrap(ui) {
  return render(<I18nextProvider i18n={i18n}>{ui}</I18nextProvider>)
}

const LXC = {
  type: 'lxc', name: 'ct-web', node: 'pve-01',
  template: 'local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst',
  hostname: 'ct-web', count: 1, cores: 1, memory: 512, swap: 512,
  rootfs_size: 8, rootfs_datastore: 'local-lvm', unprivileged: true,
  network: { bridge: 'vmbr0' }, tags: [], start_after_create: true,
}

beforeEach(() => { vi.clearAllMocks() })

// ── LXC card: dispatcher + LXC-specific fields (AC-RES/COMPUTE/SECURITY) ───────
describe('StackResourceCard – LXC branch', () => {
  it('renders the LXC card with hostname/swap/rootfs fields and an LXC badge', () => {
    wrap(<StackResourceCard resource={LXC} index={0} total={1} onChange={vi.fn()} onRemove={vi.fn()} onMove={vi.fn()} onDuplicate={vi.fn()} />)
    expect(screen.getAllByDisplayValue('ct-web').length).toBeGreaterThan(0) // name + hostname
    expect(screen.getByText('LXC')).toBeInTheDocument()
    // swap + rootfs labels present (LXC-only)
    expect(screen.getByText('Swap (MB)')).toBeInTheDocument()
    expect(screen.getByText('Root-FS (GB)')).toBeInTheDocument()
    // no sockets field (VM-only)
    expect(screen.queryByText('Sockets')).toBeNull()
  })

  it('shows a warning when set to privileged (unprivileged unchecked)', () => {
    const onChange = vi.fn()
    wrap(<StackResourceCard resource={{ ...LXC, unprivileged: false }} index={0} total={1} onChange={onChange} onRemove={vi.fn()} onMove={vi.fn()} onDuplicate={vi.fn()} />)
    expect(screen.getByText(/erweiterten Host-Zugriff|extended host access/i)).toBeInTheDocument()
  })

  it('toggling a feature sets r.features; turning all off removes the block', () => {
    const onChange = vi.fn()
    wrap(<StackResourceCard resource={LXC} index={0} total={1} onChange={onChange} onRemove={vi.fn()} onMove={vi.fn()} onDuplicate={vi.fn()} />)
    fireEvent.click(screen.getByLabelText('Nesting'))
    expect(onChange).toHaveBeenLastCalledWith(0, expect.objectContaining({ features: { nesting: true } }))
  })
})

// ── Mountpoints (AC-MOUNT, auto mp index) ─────────────────────────────────────
describe('StackResourceCard – LXC mountpoints', () => {
  it('adding a mountpoint assigns mp0, a second adds mp1', () => {
    const onChange = vi.fn()
    const { rerender } = wrap(<StackResourceCard resource={LXC} index={0} total={1} onChange={onChange} onRemove={vi.fn()} onMove={vi.fn()} onDuplicate={vi.fn()} />)
    fireEvent.click(screen.getByTitle('Mountpoint'))
    const m0 = onChange.mock.calls.at(-1)[1].mounts
    expect(m0).toHaveLength(1)
    expect(m0[0].id).toBe('mp0')

    rerender(<I18nextProvider i18n={i18n}><StackResourceCard resource={{ ...LXC, mounts: m0 }} index={0} total={1} onChange={onChange} onRemove={vi.fn()} onMove={vi.fn()} onDuplicate={vi.fn()} /></I18nextProvider>)
    fireEvent.click(screen.getByTitle('Mountpoint'))
    const m1 = onChange.mock.calls.at(-1)[1].mounts
    expect(m1).toHaveLength(2)
    expect(m1[1].id).toBe('mp1')
  })

  it('removing a mountpoint shrinks the list', () => {
    const onChange = vi.fn()
    const withMount = { ...LXC, mounts: [{ id: 'mp0', size: 8, datastore: 'local-lvm', path: '/data', backup: false }] }
    wrap(<StackResourceCard resource={withMount} index={0} total={1} onChange={onChange} onRemove={vi.fn()} onMove={vi.fn()} onDuplicate={vi.fn()} />)
    fireEvent.click(screen.getByLabelText(/Mountpoint entfernen|Remove mount point/i))
    expect(onChange).toHaveBeenLastCalledWith(0, expect.objectContaining({ mounts: [] }))
  })
})

// ── StackFormEditor: add LXC (AC-MIX) ─────────────────────────────────────────
describe('StackFormEditor – add LXC', () => {
  it('empty state offers both VM and LXC; clicking LXC appends an lxc resource', () => {
    const onChange = vi.fn()
    wrap(<StackFormEditor model={{ name: 's', resources: [] }} onChange={onChange} />)
    fireEvent.click(screen.getByText(/Ersten LXC hinzufügen|Add first LXC/i))
    const res = onChange.mock.calls.at(-1)[0].resources
    expect(res).toHaveLength(1)
    expect(res[0].type).toBe('lxc')
    expect(res[0].unprivileged).toBe(true)
  })

  it('appends an LXC next to an existing VM (mixed stack)', () => {
    const onChange = vi.fn()
    const VM = { type: 'vm', name: 'web', node: 'pve-01', template: 'debian-12', count: 1, cores: 1, sockets: 1, memory: 2048, disk: 32, cpu_type: 'host', network: { bridge: 'vmbr0' }, tags: [], start_after_create: true }
    wrap(<StackFormEditor model={{ name: 's', resources: [VM] }} onChange={onChange} />)
    fireEvent.click(screen.getByText(/LXC hinzufügen|Add LXC/i))
    const res = onChange.mock.calls.at(-1)[0].resources
    expect(res).toHaveLength(2)
    expect(res[1].type).toBe('lxc')
  })
})

// ── Cloud-Init tab: LXC = root, no username (AC-GUEST-5) ───────────────────────
describe('StackCloudInitTab – LXC login is root', () => {
  it('LXC override shows "root" login and no username field', () => {
    wrap(<StackCloudInitTab stackId={7} resources={[{ name: 'ct-web', type: 'lxc' }]} />)
    // switch the override to "custom" so the fields render
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'custom' } })
    expect(screen.getByText('root')).toBeInTheDocument()
    expect(screen.queryByText(/Benutzername|Username/)).toBeNull()
  })

  it('VM override keeps the username field', () => {
    wrap(<StackCloudInitTab stackId={7} resources={[{ name: 'web', type: 'vm' }]} />)
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'custom' } })
    expect(screen.getByText(/Benutzername|Username/)).toBeInTheDocument()
  })
})
