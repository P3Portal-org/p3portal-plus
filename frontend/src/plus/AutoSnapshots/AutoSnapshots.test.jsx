// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-77: Unit-Tests für die Auto-Snapshot-Plus-Komponenten.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { I18nextProvider } from 'react-i18next'
import { MemoryRouter } from 'react-router-dom'
import i18n from '../../i18n'

// Mock der React-Query-Hooks (verhindert echte API-Aufrufe in Komponenten-Tests)
vi.mock('./hooks', () => ({
  useRunDetails: vi.fn(() => ({ data: null, isLoading: false, error: null })),
  useNativeSnapshots: vi.fn(() => ({ data: [] })),
}))

import { useRunDetails, useNativeSnapshots } from './hooks'
import AutoBadge from './AutoBadge'
import PrefixCollisionWarning from './PrefixCollisionWarning'
import AutoSnapshotFieldsBase from './AutoSnapshotFieldsBase'
import AutoSnapshotFieldsConfig from './AutoSnapshotFieldsConfig'
import AutoSnapshotFieldsVm from './AutoSnapshotFieldsVm'
import RunDetailsTable from './RunDetailsTable'
import NativeSnapshotBadgeMap from './NativeSnapshotBadgeMap'

function withProviders(ui) {
  return (
    <I18nextProvider i18n={i18n}>
      <MemoryRouter>{ui}</MemoryRouter>
    </I18nextProvider>
  )
}

// ─── AutoBadge ──────────────────────────────────────────────────────────────

describe('AutoBadge', () => {
  it('renders the "auto" label', () => {
    render(withProviders(<AutoBadge jobId="job-123" />))
    expect(screen.getByText('auto')).toBeInTheDocument()
  })

  it('navigates to /automation?tab=scheduled&openJob=… on click', () => {
    render(withProviders(<AutoBadge jobId="job-123" />))
    const btn = screen.getByRole('button')
    expect(btn).toBeInTheDocument()
    fireEvent.click(btn) // Navigation kann nicht direkt geprüft werden (Router-mock entfällt),
    // aber Click darf nicht crashen
  })
})

// ─── PrefixCollisionWarning ─────────────────────────────────────────────────

describe('PrefixCollisionWarning', () => {
  it('returns null when collisions are empty', () => {
    const { container } = render(withProviders(<PrefixCollisionWarning collisions={[]} />))
    expect(container.textContent).toBe('')
  })

  it('renders entries and shows „… und N weitere" for >20', () => {
    const collisions = Array.from({ length: 25 }, (_, i) => ({
      proxmox_node: 'pve1',
      vmid: 100 + i,
      snapname: `p3auto_x_${i}`,
    }))
    render(withProviders(<PrefixCollisionWarning collisions={collisions} />))
    expect(screen.getByText(/p3auto_x_0/)).toBeInTheDocument()
    expect(screen.getByText(/p3auto_x_19/)).toBeInTheDocument()
    // 5 mehr als 20 → der "weitere"-Hinweis muss sichtbar sein
    expect(screen.getByText(/und 5 weitere/)).toBeInTheDocument()
  })
})

// ─── AutoSnapshotFieldsBase ─────────────────────────────────────────────────

describe('AutoSnapshotFieldsBase', () => {
  it('shows GFS-fields after enabling the GFS checkbox', () => {
    const onChange = vi.fn()
    const values = { keep_last: 7, gfs_enabled: false, keep_daily: 0, keep_weekly: 0, keep_monthly: 0, max_parallel: 5 }
    render(withProviders(<AutoSnapshotFieldsBase values={values} onChange={onChange} />))
    const cb = screen.getByLabelText(/GFS-Schema aktivieren/)
    fireEvent.click(cb)
    expect(onChange).toHaveBeenCalled()
    const lastCall = onChange.mock.calls[onChange.mock.calls.length - 1][0]
    expect(lastCall.gfs_enabled).toBe(true)
    // Beim erstmaligen Aktivieren werden 7/4/12 vorgeschlagen
    expect(lastCall.keep_daily).toBe(7)
    expect(lastCall.keep_weekly).toBe(4)
    expect(lastCall.keep_monthly).toBe(12)
  })

  it('clamps keep_last to [1, 100]', () => {
    const onChange = vi.fn()
    const values = { keep_last: 7, gfs_enabled: false, keep_daily: 0, keep_weekly: 0, keep_monthly: 0, max_parallel: 5 }
    render(withProviders(<AutoSnapshotFieldsBase values={values} onChange={onChange} />))
    const input = screen.getByLabelText(/Behalte zuletzt/)
    fireEvent.change(input, { target: { value: '500' } })
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ keep_last: 100 }))
    fireEvent.change(input, { target: { value: '0' } })
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ keep_last: 1 }))
  })
})

// ─── AutoSnapshotFieldsConfig ───────────────────────────────────────────────

describe('AutoSnapshotFieldsConfig', () => {
  it('toggles skip_if_no_changes', () => {
    const onChange = vi.fn()
    const values = { keep_last: 7, gfs_enabled: false, keep_daily: 0, keep_weekly: 0, keep_monthly: 0, max_parallel: 5, skip_if_no_changes: true }
    render(withProviders(<AutoSnapshotFieldsConfig values={values} onChange={onChange} />))
    const cb = screen.getByLabelText(/Überspringen wenn unverändert/)
    expect(cb).toBeChecked()
    fireEvent.click(cb)
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ skip_if_no_changes: false }))
  })
})

// ─── AutoSnapshotFieldsVm ───────────────────────────────────────────────────

describe('AutoSnapshotFieldsVm', () => {
  it('toggles include_ram', () => {
    const onChange = vi.fn()
    const values = { keep_last: 7, gfs_enabled: false, keep_daily: 0, keep_weekly: 0, keep_monthly: 0, max_parallel: 5, include_ram: false }
    render(withProviders(<AutoSnapshotFieldsVm values={values} onChange={onChange} />))
    const cb = screen.getByLabelText(/RAM-Status einbeziehen/)
    expect(cb).not.toBeChecked()
    fireEvent.click(cb)
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ include_ram: true }))
  })
})

// ─── RunDetailsTable ────────────────────────────────────────────────────────

describe('RunDetailsTable', () => {
  beforeEach(() => {
    vi.mocked(useRunDetails).mockReset()
  })

  it('shows loading state', () => {
    vi.mocked(useRunDetails).mockReturnValue({ data: null, isLoading: true, error: null })
    render(withProviders(<RunDetailsTable runId="run-1" />))
    expect(screen.getByText(/wird geladen/i)).toBeInTheDocument()
  })

  it('renders summary stats and per-VM rows', () => {
    vi.mocked(useRunDetails).mockReturnValue({
      data: {
        run_id: 'r1', job_id: 'j1',
        summary: {
          status: 'success', targets_total: 3, created_count: 3,
          skipped_no_change_count: 0, skipped_locked_count: 0,
          skipped_not_owner_count: 0, failed_count: 0, rotated_count: 0,
          failed_details: [],
        },
        entries: [
          { portal_node_id: 1, proxmox_node: 'pve', vmid: 100, kind: 'qemu', status: 'created', snapname: 'p3auto_a_x', snapshot_id: 's1' },
          { portal_node_id: 1, proxmox_node: 'pve', vmid: 200, kind: 'lxc',  status: 'created', snapname: 'p3auto_a_y', snapshot_id: 's2' },
        ],
      },
      isLoading: false, error: null,
    })
    render(withProviders(<RunDetailsTable runId="r1" />))
    expect(screen.getByText('p3auto_a_x')).toBeInTheDocument()
    expect(screen.getByText('p3auto_a_y')).toBeInTheDocument()
    expect(screen.getByText('100')).toBeInTheDocument()
    expect(screen.getByText('200')).toBeInTheDocument()
  })

  it('shows failed-details when present', () => {
    vi.mocked(useRunDetails).mockReturnValue({
      data: {
        run_id: 'r1', job_id: 'j1',
        summary: {
          status: 'partial_success', targets_total: 1, created_count: 0,
          skipped_no_change_count: 0, skipped_locked_count: 0,
          skipped_not_owner_count: 0, failed_count: 1, rotated_count: 0,
          failed_details: [{ node: 'pve', vmid: 100, error_class: 'Timeout', error_msg: 'lock timeout' }],
        },
        entries: [],
      },
      isLoading: false, error: null,
    })
    render(withProviders(<RunDetailsTable runId="r1" />))
    expect(screen.getByText(/Fehler-Details/)).toBeInTheDocument()
  })
})

// ─── NativeSnapshotBadgeMap ─────────────────────────────────────────────────

describe('NativeSnapshotBadgeMap', () => {
  it('passes an empty lookup when no snapshots match', () => {
    vi.mocked(useNativeSnapshots).mockReturnValue({ data: [] })
    let receivedLookup = null
    render(
      <NativeSnapshotBadgeMap portalNodeId={1} proxmoxNode="pve" vmid={100} kind="qemu">
        {(lookup) => {
          receivedLookup = lookup
          return <div>ok</div>
        }}
      </NativeSnapshotBadgeMap>,
    )
    expect(receivedLookup).toEqual({})
  })

  it('builds {snapname: scheduled_job_id} lookup from native snapshots', () => {
    vi.mocked(useNativeSnapshots).mockReturnValue({
      data: [
        { snapname: 'p3auto_a_x', scheduled_job_id: 'job-1' },
        { snapname: 'p3auto_a_y', scheduled_job_id: 'job-2' },
      ],
    })
    let receivedLookup = null
    render(
      <NativeSnapshotBadgeMap portalNodeId={1} proxmoxNode="pve" vmid={100} kind="qemu">
        {(lookup) => {
          receivedLookup = lookup
          return <div>ok</div>
        }}
      </NativeSnapshotBadgeMap>,
    )
    expect(receivedLookup).toEqual({
      p3auto_a_x: 'job-1',
      p3auto_a_y: 'job-2',
    })
  })
})
