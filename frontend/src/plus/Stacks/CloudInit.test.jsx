// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-85: Stacks Cloud-Init-Login – Tab (Default/Override/Orphan/Profil-Key) + Banner.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { I18nextProvider } from 'react-i18next'
import i18n from '../../i18n'

// vi.mock ist hoisted → mutable Container für Daten/Spies pro Test.
const h = vi.hoisted(() => ({
  ci: null,
  profileKey: { has_key: false },
  putSpy: vi.fn(() => Promise.resolve({ default: { vm_name: '', enabled: false }, overrides: [] })),
}))

vi.mock('./hooks', () => ({
  useStackCloudInit: () => ({ data: h.ci, isLoading: false }),
  usePutStackCloudInit: () => ({ mutateAsync: h.putSpy, isPending: false }),
}))
// Profil-Key kommt über useQuery (inline) – deterministisch mocken (kein Provider nötig).
vi.mock('@tanstack/react-query', () => ({ useQuery: () => ({ data: h.profileKey }) }))

import StackCloudInitTab from './StackCloudInitTab'
import CloudInitHintBanner from './CloudInitHintBanner'

function wrap(ui) {
  return render(<I18nextProvider i18n={i18n}>{ui}</I18nextProvider>)
}

beforeEach(() => {
  vi.clearAllMocks()
  h.ci = { default: { vm_name: '', enabled: false }, overrides: [] }
  h.profileKey = { has_key: false }
  // Echo eines aktiven Default (password_set) → die Felder bleiben nach dem
  // Speichern sichtbar (seedFrom nutzt die Response); Body-Asserts bleiben gültig.
  h.putSpy = vi.fn(() =>
    Promise.resolve({ default: { vm_name: '', enabled: true, password_set: true }, overrides: [] }),
  )
})

// ── CloudInitHintBanner (AC-UI-2) ─────────────────────────────────────────────

describe('CloudInitHintBanner', () => {
  it('shows the inactive hint when no cloud-init data', () => {
    wrap(<CloudInitHintBanner data={undefined} />)
    expect(screen.getByText(/inaktiv|inactive/i)).toBeInTheDocument()
  })

  it('shows the active hint with default + override count', () => {
    wrap(<CloudInitHintBanner data={{ default: { enabled: true }, overrides: [{ enabled: true }, { enabled: false }] }} />)
    expect(screen.getByText(/aktiv|active/i)).toBeInTheDocument()
  })
})

// ── StackCloudInitTab ─────────────────────────────────────────────────────────

describe('StackCloudInitTab', () => {
  it('shows "save first" for an unsaved stack (no stackId)', () => {
    wrap(<StackCloudInitTab stackId={null} resourceNames={[]} />)
    expect(screen.getByText(/zuerst speichern|save the stack first/i)).toBeInTheDocument()
  })

  it('seeds the default block and shows the password-set placeholder (AC-UI-4)', async () => {
    h.ci = { default: { vm_name: '', enabled: true, username: 'admin', password_set: true, ssh_keys: [] }, overrides: [] }
    wrap(<StackCloudInitTab stackId={7} resourceNames={['web']} />)
    expect(await screen.findByDisplayValue('admin')).toBeInTheDocument()
    expect(screen.getByPlaceholderText(/gesetzt|set/i)).toBeInTheDocument()
  })

  it('only sends the password when typed (write-only merge, EC-6)', async () => {
    h.ci = { default: { vm_name: '', enabled: true, username: 'admin', password_set: true, ssh_keys: ['ssh-ed25519 AAAA x'] }, overrides: [] }
    wrap(<StackCloudInitTab stackId={7} resourceNames={['web']} />)
    await screen.findByDisplayValue('admin')
    // Ohne Tippen: kein password im Body.
    fireEvent.click(screen.getByRole('button', { name: /cloud-init speichern|save cloud-init/i }))
    await waitFor(() => expect(h.putSpy).toHaveBeenCalled())
    let body = h.putSpy.mock.calls[0][0].body
    expect(body.default).not.toHaveProperty('password')
    // Mit Tippen: password im Body (Feld via Platzhalter, password_set=true).
    fireEvent.change(screen.getByPlaceholderText(/gesetzt|set/i), { target: { value: 'secret123' } })
    fireEvent.click(screen.getByRole('button', { name: /cloud-init speichern|save cloud-init/i }))
    await waitFor(() => expect(h.putSpy).toHaveBeenCalledTimes(2))
    body = h.putSpy.mock.calls[1][0].body
    expect(body.default.password).toBe('secret123')
  })

  it('adds the profile key to the ssh_keys list (AC-KEY-1)', async () => {
    h.ci = { default: { vm_name: '', enabled: true, username: 'admin', ssh_keys: [] }, overrides: [] }
    h.profileKey = { has_key: true, public_key: 'ssh-ed25519 AAAAPROFILE me@host' }
    wrap(<StackCloudInitTab stackId={7} resourceNames={['web']} />)
    await screen.findByDisplayValue('admin')
    fireEvent.click(screen.getByRole('button', { name: /profil-key übernehmen|use profile key/i }))
    expect(screen.getByDisplayValue(/AAAAPROFILE/)).toBeInTheDocument()
  })

  it('custom override reveals fields and is sent as enabled override (AC-ACT-2)', async () => {
    wrap(<StackCloudInitTab stackId={7} resourceNames={['web']} />)
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'custom' } })
    // Override-Felder erscheinen (eigenes Benutzerfeld).
    expect(screen.getByLabelText(/Benutzername|Username/i)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /cloud-init speichern|save cloud-init/i }))
    await waitFor(() => expect(h.putSpy).toHaveBeenCalled())
    const body = h.putSpy.mock.calls[0][0].body
    expect(body.overrides).toEqual([expect.objectContaining({ vm_name: 'web', enabled: true })])
  })

  it('suppress override is sent as a disabled override (AC-ACT-3)', async () => {
    wrap(<StackCloudInitTab stackId={7} resourceNames={['web']} />)
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'suppress' } })
    expect(screen.getByText(/erbt ihren Login aus dem Template|inherits its login from the template/i)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /cloud-init speichern|save cloud-init/i }))
    await waitFor(() => expect(h.putSpy).toHaveBeenCalled())
    const body = h.putSpy.mock.calls[0][0].body
    expect(body.overrides).toEqual([expect.objectContaining({ vm_name: 'web', enabled: false })])
  })

  it('shows orphan overrides with a badge and drops them on delete (EC-4)', async () => {
    h.ci = { default: { vm_name: '', enabled: false }, overrides: [{ vm_name: 'gone', enabled: true, orphan: true }] }
    wrap(<StackCloudInitTab stackId={7} resourceNames={['web']} />)
    expect(await screen.findByText('gone')).toBeInTheDocument()
    expect(screen.getByText(/verwaist|orphaned/i)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /entfernen|remove/i }))
    fireEvent.click(screen.getByRole('button', { name: /cloud-init speichern|save cloud-init/i }))
    await waitFor(() => expect(h.putSpy).toHaveBeenCalled())
    const body = h.putSpy.mock.calls[0][0].body
    expect(body.overrides).toEqual([])
  })
})
