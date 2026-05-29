// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-74: Tests für ConfigSnapshots-Komponenten (Tab, NodeTab, OrphanPage).
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { I18nextProvider } from 'react-i18next'
import i18n from '../../i18n'

// ── Mocks ─────────────────────────────────────────────────────────────────────

vi.mock('./hooks', () => ({
  useConfigSnapshots: vi.fn(),
  useConfigSnapshotsByNode: vi.fn(),
  useOrphans: vi.fn(),
  useDeleteSnapshot: vi.fn(),
  useBulkDeleteSnapshots: vi.fn(),
  useDeleteOrphan: vi.fn(),
  useInvalidateSnapshots: vi.fn(),
}))

vi.mock('./api', () => ({
  downloadSnapshot: vi.fn(),
  bulkDownloadSnapshots: vi.fn(),
  fetchSnapshotDetail: vi.fn(),
  fetchDiffLive: vi.fn(),
  fetchDiffAB: vi.fn(),
  restoreSnapshot: vi.fn(),
  uploadSnapshot: vi.fn(),
  createSnapshot: vi.fn(),
  deleteOrphan: vi.fn(),
}))

import {
  useConfigSnapshots,
  useConfigSnapshotsByNode,
  useOrphans,
  useDeleteSnapshot,
  useBulkDeleteSnapshots,
  useDeleteOrphan,
  useInvalidateSnapshots,
} from './hooks'

import ConfigSnapshotsTab from './ConfigSnapshotsTab'
import ConfigSnapshotsNodeTab from './ConfigSnapshotsNodeTab'
import ConfigSnapshotOrphanPage from './ConfigSnapshotOrphanPage'

const MOCK_SNAP = {
  id: 'abc-123',
  name: 'snapshot-config-pve-100-20260528',
  note: 'Before update',
  source: 'manual',
  created_at: '2026-05-28T10:00:00',
  created_by_username: 'admin',
  proxmox_node: 'pve',
  vmid: 100,
  kind: 'qemu',
  is_orphan: false,
}

const MOCK_ORPHAN = {
  id: 'orphan-1',
  name: 'snapshot-config-pve-999-old',
  note: 'Pre-delete',
  kind: 'qemu',
  proxmox_node: 'pve',
  vmid: 999,
  orphaned_at: '2026-05-20T08:00:00',
}

function wrap(ui) {
  return render(<I18nextProvider i18n={i18n}>{ui}</I18nextProvider>)
}

// ── ConfigSnapshotsTab ────────────────────────────────────────────────────────

describe('ConfigSnapshotsTab', () => {
  const defaultProps = {
    portalNodeId: 1,
    proxmoxNode: 'pve',
    vmid: 100,
    kind: 'qemu',
    vmName: 'test-vm',
    vmStatus: 'running',
  }

  beforeEach(() => {
    useDeleteSnapshot.mockReturnValue({ mutateAsync: vi.fn(), isPending: false })
  })

  it('shows loading state', () => {
    useConfigSnapshots.mockReturnValue({ data: undefined, isLoading: true, error: null, refetch: vi.fn() })
    wrap(<ConfigSnapshotsTab {...defaultProps} />)
    expect(screen.getByText(/wird geladen|loading/i)).toBeInTheDocument()
  })

  it('shows empty state when no snapshots', () => {
    useConfigSnapshots.mockReturnValue({ data: [], isLoading: false, error: null, refetch: vi.fn() })
    wrap(<ConfigSnapshotsTab {...defaultProps} />)
    expect(screen.getByText(/noch keine config-snapshots|no config snapshots/i)).toBeInTheDocument()
  })

  it('renders snapshot row when data present', () => {
    useConfigSnapshots.mockReturnValue({ data: [MOCK_SNAP], isLoading: false, error: null, refetch: vi.fn() })
    wrap(<ConfigSnapshotsTab {...defaultProps} />)
    expect(screen.getByText('snapshot-config-pve-100-20260528')).toBeInTheDocument()
    expect(screen.getByText('Before update')).toBeInTheDocument()
  })

  it('shows create and upload buttons', () => {
    useConfigSnapshots.mockReturnValue({ data: [], isLoading: false, error: null, refetch: vi.fn() })
    wrap(<ConfigSnapshotsTab {...defaultProps} />)
    expect(screen.getByRole('button', { name: /\+ snapshot erstellen|\+ create snapshot/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /snapshot hochladen|upload snapshot/i })).toBeInTheDocument()
  })

  it('shows error state', () => {
    useConfigSnapshots.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: { response: { data: { detail: 'Permission denied' } } },
      refetch: vi.fn(),
    })
    wrap(<ConfigSnapshotsTab {...defaultProps} />)
    expect(screen.getByText('Permission denied')).toBeInTheDocument()
  })

  it('shows inline delete confirm on delete button click', () => {
    useConfigSnapshots.mockReturnValue({ data: [MOCK_SNAP], isLoading: false, error: null, refetch: vi.fn() })
    wrap(<ConfigSnapshotsTab {...defaultProps} />)
    const deleteBtn = screen.getAllByRole('button').find(b => /löschen|delete/i.test(b.textContent))
    expect(deleteBtn).toBeTruthy()
    fireEvent.click(deleteBtn)
    expect(screen.getByRole('button', { name: /wirklich|confirm|bestätigen/i })).toBeInTheDocument()
  })
})

// ── ConfigSnapshotsNodeTab ────────────────────────────────────────────────────

describe('ConfigSnapshotsNodeTab', () => {
  beforeEach(() => {
    useInvalidateSnapshots.mockReturnValue(vi.fn())
    useBulkDeleteSnapshots.mockReturnValue({ mutateAsync: vi.fn(), isPending: false })
  })

  it('shows loading state', () => {
    useConfigSnapshotsByNode.mockReturnValue({ data: undefined, isLoading: true, error: null, refetch: vi.fn() })
    wrap(<ConfigSnapshotsNodeTab portalNodeId={1} active={true} />)
    expect(screen.getByText(/wird geladen|loading/i)).toBeInTheDocument()
  })

  it('shows empty state when no snapshots', () => {
    useConfigSnapshotsByNode.mockReturnValue({ data: [], isLoading: false, error: null, refetch: vi.fn() })
    wrap(<ConfigSnapshotsNodeTab portalNodeId={1} active={true} />)
    expect(screen.getByText(/noch keine config-snapshots|no config snapshots/i)).toBeInTheDocument()
  })

  it('renders snapshot row', () => {
    useConfigSnapshotsByNode.mockReturnValue({ data: [MOCK_SNAP], isLoading: false, error: null, refetch: vi.fn() })
    wrap(<ConfigSnapshotsNodeTab portalNodeId={1} active={true} />)
    expect(screen.getByText('snapshot-config-pve-100-20260528')).toBeInTheDocument()
  })

  it('shows search filter input', () => {
    useConfigSnapshotsByNode.mockReturnValue({ data: [], isLoading: false, error: null, refetch: vi.fn() })
    wrap(<ConfigSnapshotsNodeTab portalNodeId={1} active={true} />)
    expect(screen.getByPlaceholderText(/suchen|search/i)).toBeInTheDocument()
  })

  it('bulk action bar hidden when nothing selected', () => {
    useConfigSnapshotsByNode.mockReturnValue({ data: [MOCK_SNAP], isLoading: false, error: null, refetch: vi.fn() })
    const { container } = wrap(<ConfigSnapshotsNodeTab portalNodeId={1} active={true} />)
    expect(container.querySelector('[data-testid="bulk-bar"]')).toBeNull()
  })

  it('does not fetch when not active', () => {
    useConfigSnapshotsByNode.mockReturnValue({ data: undefined, isLoading: false, error: null, refetch: vi.fn() })
    wrap(<ConfigSnapshotsNodeTab portalNodeId={1} active={false} />)
    expect(useConfigSnapshotsByNode).toHaveBeenCalledWith(
      expect.objectContaining({ portalNodeId: 1 }),
      false,
    )
  })
})

// ── ConfigSnapshotOrphanPage ──────────────────────────────────────────────────

describe('ConfigSnapshotOrphanPage', () => {
  beforeEach(() => {
    useDeleteOrphan.mockReturnValue({ mutateAsync: vi.fn(), isPending: false })
  })

  it('shows loading state', () => {
    useOrphans.mockReturnValue({ data: undefined, isLoading: true, error: null, refetch: vi.fn() })
    wrap(<ConfigSnapshotOrphanPage />)
    expect(screen.getByText(/laden|loading/i)).toBeInTheDocument()
  })

  it('shows empty state', () => {
    useOrphans.mockReturnValue({ data: [], isLoading: false, error: null, refetch: vi.fn() })
    wrap(<ConfigSnapshotOrphanPage />)
    expect(screen.getByText(/keine.*verwaist|no orphan/i)).toBeInTheDocument()
  })

  it('renders orphan row', () => {
    useOrphans.mockReturnValue({ data: [MOCK_ORPHAN], isLoading: false, error: null, refetch: vi.fn() })
    wrap(<ConfigSnapshotOrphanPage />)
    expect(screen.getByText('snapshot-config-pve-999-old')).toBeInTheDocument()
  })

  it('shows count in header', () => {
    useOrphans.mockReturnValue({ data: [MOCK_ORPHAN], isLoading: false, error: null, refetch: vi.fn() })
    wrap(<ConfigSnapshotOrphanPage />)
    expect(screen.getByText(/1/)).toBeInTheDocument()
  })

  it('renders without page header when embedded=true', () => {
    useOrphans.mockReturnValue({ data: [], isLoading: false, error: null, refetch: vi.fn() })
    const { container } = wrap(<ConfigSnapshotOrphanPage embedded />)
    expect(container.querySelector('header')).toBeNull()
  })

  it('renders page header when not embedded', () => {
    useOrphans.mockReturnValue({ data: [], isLoading: false, error: null, refetch: vi.fn() })
    const { container } = wrap(<ConfigSnapshotOrphanPage />)
    expect(container.querySelector('header')).not.toBeNull()
  })
})
