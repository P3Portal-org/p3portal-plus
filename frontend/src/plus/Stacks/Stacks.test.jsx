// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-76 Phase 1: Tests für Stacks-Komponenten.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { I18nextProvider } from 'react-i18next'
import i18n from '../../i18n'

// ── Mocks ─────────────────────────────────────────────────────────────────────

vi.mock('./hooks', () => ({
  useStackVersions: vi.fn(),
  useNodeVmOptions: vi.fn(() => ({ data: undefined })),
  useImageStorages: vi.fn(() => ({ data: undefined })),
}))

vi.mock('./api', () => ({
  fetchDiff: vi.fn(() => new Promise(() => {})),
  restoreVersion: vi.fn(),
}))

import { useStackVersions } from './hooks'
import StackResourceCard from './StackResourceCard'
import StackFormEditor from './StackFormEditor'
import StackEtagConflictModal from './StackEtagConflictModal'
import StackPreviewModal from './StackPreviewModal'
import StackVersionList from './StackVersionList'

function wrap(ui) {
  return render(<I18nextProvider i18n={i18n}>{ui}</I18nextProvider>)
}

const VM = {
  type: 'vm', name: 'web', node: 'pve-01', template: 'debian-12', count: 1,
  cores: 2, sockets: 1, memory: 2048, disk: 32, cpu_type: 'host',
  network: { bridge: 'vmbr0' }, tags: ['frontend'], start_after_create: true,
}

beforeEach(() => {
  vi.clearAllMocks()
})

// ── StackResourceCard ───────────────────────────────────────────────────────

describe('StackResourceCard', () => {
  it('renders VM fields and propagates name change', () => {
    const onChange = vi.fn()
    wrap(
      <StackResourceCard resource={VM} index={0} total={1} onChange={onChange} onRemove={vi.fn()} onMove={vi.fn()} />,
    )
    const nameInput = screen.getByDisplayValue('web')
    fireEvent.change(nameInput, { target: { value: 'lb' } })
    expect(onChange).toHaveBeenCalledWith(0, expect.objectContaining({ name: 'lb' }))
  })

  it('disables move-up on first card', () => {
    wrap(<StackResourceCard resource={VM} index={0} total={2} onChange={vi.fn()} onRemove={vi.fn()} onMove={vi.fn()} />)
    const up = screen.getByLabelText(/nach oben|move up/i)
    expect(up).toBeDisabled()
  })

  it('joins tags into a comma string', () => {
    wrap(<StackResourceCard resource={{ ...VM, tags: ['a', 'b'] }} index={0} total={1} onChange={vi.fn()} onRemove={vi.fn()} onMove={vi.fn()} />)
    expect(screen.getByDisplayValue('a, b')).toBeInTheDocument()
  })
})

// ── StackFormEditor ───────────────────────────────────────────────────────────

describe('StackFormEditor', () => {
  it('shows empty-state add button when no resources', () => {
    const onChange = vi.fn()
    wrap(<StackFormEditor model={{ name: 's', resources: [] }} onChange={onChange} />)
    const addFirst = screen.getByText(/erste vm|first vm/i)
    fireEvent.click(addFirst)
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ resources: expect.arrayContaining([expect.objectContaining({ type: 'vm' })]) }))
  })

  it('updates stack name', () => {
    const onChange = vi.fn()
    wrap(<StackFormEditor model={{ name: '', resources: [VM] }} onChange={onChange} />)
    const input = screen.getByPlaceholderText('webserver-cluster')
    fireEvent.change(input, { target: { value: 'cluster' } })
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ name: 'cluster' }))
  })

  it('removes a VM card', () => {
    const onChange = vi.fn()
    wrap(<StackFormEditor model={{ name: 's', resources: [VM] }} onChange={onChange} />)
    fireEvent.click(screen.getByLabelText(/vm entfernen|remove vm/i))
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ resources: [] }))
  })
})

// ── StackEtagConflictModal ────────────────────────────────────────────────────

describe('StackEtagConflictModal', () => {
  const conflict = {
    current_etag: 'f'.repeat(64),
    current_yaml: 'name: current',
    your_yaml: 'name: yours',
    base_yaml: 'name: base',
  }

  it('renders three columns with base/your/current content', () => {
    wrap(<StackEtagConflictModal conflict={conflict} onReload={vi.fn()} onOverride={vi.fn()} onClose={vi.fn()} />)
    expect(screen.getByText('name: current')).toBeInTheDocument()
    expect(screen.getByText('name: yours')).toBeInTheDocument()
    expect(screen.getByText('name: base')).toBeInTheDocument()
  })

  it('calls onOverride with current etag', () => {
    const onOverride = vi.fn()
    wrap(<StackEtagConflictModal conflict={conflict} onReload={vi.fn()} onOverride={onOverride} onClose={vi.fn()} />)
    fireEvent.click(screen.getByText(/überschreiben|override/i))
    expect(onOverride).toHaveBeenCalledWith(conflict.current_etag)
  })
})

// ── StackPreviewModal ─────────────────────────────────────────────────────────

describe('StackPreviewModal', () => {
  it('renders resolved resources', () => {
    const preview = {
      valid: true, errors: [], warnings: [], resource_count: 2,
      resources: [
        { type: 'vm', name: 'web-1', node: 'pve-01', template: 'debian-12', cores: 2, memory: 2048, disk: 32, pool: null },
        { type: 'vm', name: 'web-2', node: 'pve-01', template: 'debian-12', cores: 2, memory: 2048, disk: 32, pool: 'p' },
      ],
    }
    wrap(<StackPreviewModal preview={preview} loading={false} error={null} onClose={vi.fn()} />)
    expect(screen.getByText('web-1')).toBeInTheDocument()
    expect(screen.getByText('web-2')).toBeInTheDocument()
  })

  it('renders warnings', () => {
    const preview = { valid: true, errors: [], warnings: ['pool field ignored'], resources: [], resource_count: 0 }
    wrap(<StackPreviewModal preview={preview} loading={false} error={null} onClose={vi.fn()} />)
    expect(screen.getByText('pool field ignored')).toBeInTheDocument()
  })
})

// ── StackVersionList ───────────────────────────────────────────────────────────

describe('StackVersionList', () => {
  it('renders versions and enables compare only with 2 selected', () => {
    useStackVersions.mockReturnValue({
      data: [
        { version_number: 3, change_summary: 'edit', edited_by_username: 'alice', created_at: '2026-06-03T10:00:00' },
        { version_number: 2, change_summary: 'edit', edited_by_username: 'bob', created_at: '2026-06-02T10:00:00' },
      ],
      isLoading: false, error: null,
    })
    wrap(<StackVersionList stackId={1} canWrite onRestored={vi.fn()} />)
    const compareBtn = screen.getByRole('button', { name: /vergleichen|compare/i })
    expect(compareBtn).toBeDisabled()
    const checks = screen.getAllByRole('checkbox')
    fireEvent.click(checks[0])
    fireEvent.click(checks[1])
    expect(compareBtn).not.toBeDisabled()
  })

  it('shows empty state', () => {
    useStackVersions.mockReturnValue({ data: [], isLoading: false, error: null })
    wrap(<StackVersionList stackId={1} canWrite={false} onRestored={vi.fn()} />)
    expect(screen.getByText(/versionshistorie|version history/i)).toBeInTheDocument()
  })
})
