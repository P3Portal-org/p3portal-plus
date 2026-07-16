// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-42 Phase 2: BridgeIpamHint sitzt IM Bridge-Feld (Positions-Regressionstest –
// vorher brach ein col-span-2 das Grid und der Hinweis landete unter „CPU-Typ").
import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { I18nextProvider } from 'react-i18next'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import i18n from '../../i18n'

vi.mock('./hooks', () => ({
  useNodeVmOptions: vi.fn(() => ({ data: { bridges: ['vmbr0'], vnets: [] } })),
  useImageStorages: vi.fn(() => ({ data: [{ name: 'local-lvm' }] })),
  useLxcTemplates: vi.fn(() => ({ data: [] })),
}))
vi.mock('../../hooks/useCapability', () => ({ useCapability: () => true }))
vi.mock('../../api/ipam', () => ({
  availablePools: vi.fn(async () => [
    { id: 1, network_name: 'vmbr0', cidr: '192.168.2.0/24', gateway: '192.168.2.1' },
  ]),
}))

import StackResourceCard from './StackResourceCard'

const VM = {
  type: 'vm', name: 'test', node: 'nested-pve1', template: 'tmpl-debian-13', count: 1,
  cores: 2, sockets: 1, memory: 2048, disk: 32, cpu_type: 'host',
  network: { bridge: 'vmbr0' }, tags: [], start_after_create: true,
}

function wrap(ui) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <I18nextProvider i18n={i18n}>{ui}</I18nextProvider>
    </QueryClientProvider>,
  )
}

describe('BridgeIpamHint – Position im Bridge-Feld', () => {
  it('rendert den Hinweis IM selben Field wie die Bridge-Auswahl', async () => {
    wrap(<StackResourceCard resource={VM} index={0} total={1}
      onChange={vi.fn()} onRemove={vi.fn()} onMove={vi.fn()} onDuplicate={vi.fn()}
      nodeOptions={[]} templateOptions={[]} />)

    const hint = await screen.findByText(/Netzwerk-Vorgabe des Templates/)
    // Der Hinweis muss im „Bridge"-Field-Label stehen (nicht bei CPU-Typ o. Ä.).
    const field = hint.closest('label')
    expect(field).not.toBeNull()
    expect(field).toHaveTextContent('Bridge')
  })

  it('zeigt den Hinweis NICHT, wenn die Bridge keinen Pool hat', async () => {
    const noPool = { ...VM, network: { bridge: 'vmbr9' } }
    wrap(<StackResourceCard resource={noPool} index={0} total={1}
      onChange={vi.fn()} onRemove={vi.fn()} onMove={vi.fn()} onDuplicate={vi.fn()}
      nodeOptions={[]} templateOptions={[]} />)
    await waitFor(() => expect(screen.queryByText(/Netzwerk-Vorgabe des Templates/)).toBeNull())
  })
})
