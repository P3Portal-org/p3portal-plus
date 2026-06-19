// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-92: Packer Visual Editor – Modell-Helper + Formular + Liste.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { I18nextProvider } from 'react-i18next'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import i18n from '../../i18n'

import { deriveId, defaultBootCommand, buildPayload, newModel, OS_PRESETS } from './model'

// CodeMirror durch eine einfache Textarea ersetzen (kein CM6 in jsdom).
vi.mock('./PlainCodeEditor', () => ({
  default: ({ value, onChange, readOnly }) => (
    <textarea
      data-testid="code-editor"
      readOnly={readOnly}
      value={value ?? ''}
      onChange={(e) => onChange?.(e.target.value)}
    />
  ),
}))

const api = vi.hoisted(() => ({
  createDefinition: vi.fn(() => Promise.resolve({ id: 'x', name: 'x', description: '', required_role: 'operator', source_type: 'proxmox-iso' })),
  updateDefinition: vi.fn(() => Promise.resolve({})),
  validateDefinition: vi.fn(() => Promise.resolve({ ok: true, warnings: [] })),
  previewDefinition: vi.fn(() => Promise.resolve({ hcl: 'source "proxmox-iso" "builder" {}', files: {}, meta_yaml: '', warnings: [] })),
  listDefinitions: vi.fn(() => Promise.resolve([])),
  deleteDefinition: vi.fn(() => Promise.resolve()),
}))
vi.mock('./api', () => api)

vi.mock('./hooks', () => ({
  useProxmoxTemplates: () => ({ data: [{ name: 'debian-12', vmid: 9001, node: 'pve' }] }),
  useDefinitions: () => ({ data: hookState.definitions, isLoading: false, error: null }),
  useDeleteDefinition: () => ({ mutateAsync: api.deleteDefinition }),
  usePackerNodes: () => ({ data: [] }),
  usePackerIsos: () => ({ data: [] }),
}))

const hookState = { definitions: [] }

import PackerEditorForm from './PackerEditorForm'
import DefinitionList from './DefinitionList'

function wrap(ui) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <I18nextProvider i18n={i18n}>{ui}</I18nextProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  hookState.definitions = []
})

// ── Pure model helpers ────────────────────────────────────────────────────────

describe('PackerEditor – model helpers', () => {
  it('deriveId slugifies the display name', () => {
    expect(deriveId('Debian 13 Trixie')).toBe('debian-13-trixie')
    expect(deriveId('  --Hello_World!! ')).toBe('hello_world')
    expect(deriveId('UPPER')).toBe('upper')
  })

  it('defaultBootCommand wires the preseed URL for debian (AC-INST-5)', () => {
    const seq = defaultBootCommand('debian-preseed')
    expect(seq.join(' ')).toContain('preseed/url=http://${var.packer_http_ip}:{{ .HTTPPort }}/preseed.cfg')
  })

  it('defaultBootCommand wires the kickstart URL for rhel', () => {
    const seq = defaultBootCommand('rhel-kickstart')
    expect(seq.join(' ')).toContain('inst.ks=http://${var.packer_http_ip}:{{ .HTTPPort }}/kickstart.cfg')
  })

  it('buildPayload keeps the installer for iso, drops it for clone', () => {
    const m = newModel() // iso by default
    expect(buildPayload(m).installer).not.toBeNull()
    const clone = { ...m, source: { ...m.source, type: 'proxmox-clone', clone_template: 'debian-12' } }
    expect(buildPayload(clone).installer).toBeNull()
  })

  it('buildPayload omits empty plain passwords (write-only merge)', () => {
    const m = newModel()
    m.installer.root_password_plain = ''
    m.installer.user_password_plain = ''
    const p = buildPayload(m)
    expect('root_password_plain' in p.installer).toBe(false)
    expect('user_password_plain' in p.installer).toBe(false)
  })

  it('buildPayload passes hcl_override/hcl_content through', () => {
    const m = { ...newModel(), hcl_override: true, hcl_content: 'source "x" "y" {}' }
    const p = buildPayload(m)
    expect(p.hcl_override).toBe(true)
    expect(p.hcl_content).toBe('source "x" "y" {}')
  })

  it('OS_PRESETS map to the right installer profile + derived id', () => {
    const byKey = Object.fromEntries(OS_PRESETS.map((p) => [p.key, p.build()]))
    // Standard-Debian = generisch (en)
    expect(byKey.debian.installer.os_profile).toBe('debian-preseed')
    expect(byKey.debian.id).toBe('debian-13')
    expect(byKey.debian.installer.locale).toBe('en_US.UTF-8')
    // Ubuntu = echtes autoinstall-Profil (nicht preseed)
    expect(byKey.ubuntu.installer.os_profile).toBe('ubuntu-autoinstall')
    // Rocky = kickstart
    expect(byKey.rocky.installer.os_profile).toBe('rhel-kickstart')
    expect(byKey.rocky.name).toBe('Rocky Linux 9')
    // alle Vorlagen sind proxmox-iso (mit Installer)
    OS_PRESETS.forEach((p) => {
      const m = p.build()
      expect(m.source.type).toBe('proxmox-iso')
      expect(m.installer).not.toBeNull()
    })
  })

  it('Debian "meine Vorlage" spiegelt die de_DE-Referenz + Provisioner', () => {
    const m = OS_PRESETS.find((p) => p.key === 'debian-ref').build()
    expect(m.installer.locale).toBe('de_DE.UTF-8')
    expect(m.installer.keyboard).toBe('de')
    expect(m.installer.timezone).toBe('Europe/Berlin')
    expect(m.source.ssh_private_key_name).toBe('sysadm')
    // 3 Provisioner (shell + file cloud.cfg + shell), kein Privat-Key mitgeliefert
    expect(m.provisioners.map((p) => p.type)).toEqual(['shell', 'file', 'shell'])
    expect(m.provisioners[1].source_name).toBe('cloud.cfg')
    expect(m.provisioners[1].source_content).toContain('distro: debian')
    expect(m.side_files).toEqual({})
  })
})

// ── PackerEditorForm ──────────────────────────────────────────────────────────

describe('PackerEditorForm', () => {
  it('renders meta + source (iso default) + installer section', () => {
    wrap(<PackerEditorForm isEdit={false} onClose={vi.fn()} onSaved={vi.fn()} />)
    expect(screen.getByText(i18n.t('packer_editor.meta.title'))).toBeInTheDocument()
    expect(screen.getByText(i18n.t('packer_editor.source.title'))).toBeInTheDocument()
    // Installer-Builder ist nur bei iso sichtbar (Default = iso).
    expect(screen.getByText(i18n.t('packer_editor.installer.title'))).toBeInTheDocument()
  })

  it('switching to clone hides the installer and shows the clone template field', () => {
    wrap(<PackerEditorForm isEdit={false} onClose={vi.fn()} onSaved={vi.fn()} />)
    fireEvent.click(screen.getByText(i18n.t('packer_editor.source.type_clone')))
    expect(screen.queryByText(i18n.t('packer_editor.installer.title'))).not.toBeInTheDocument()
    expect(screen.getByText((c) => c.startsWith(i18n.t('packer_editor.source.clone_template')))).toBeInTheDocument()
  })

  it('a prefill button fills the form (Rocky → name + id)', () => {
    wrap(<PackerEditorForm isEdit={false} onClose={vi.fn()} onSaved={vi.fn()} />)
    fireEvent.click(screen.getByText('Rocky / Alma (RHEL 9)'))
    expect(screen.getByDisplayValue('Rocky Linux 9')).toBeInTheDocument()
    expect(screen.getByDisplayValue('rocky-linux-9')).toBeInTheDocument()
  })

  it('derives the id from the name on create', () => {
    wrap(<PackerEditorForm isEdit={false} onClose={vi.fn()} onSaved={vi.fn()} />)
    const nameInput = screen.getByPlaceholderText(i18n.t('packer_editor.meta.name_ph'))
    fireEvent.change(nameInput, { target: { value: 'Debian 13' } })
    expect(screen.getByDisplayValue('debian-13')).toBeInTheDocument()
  })

  it('Validate calls the validate API', async () => {
    wrap(<PackerEditorForm isEdit={false} onClose={vi.fn()} onSaved={vi.fn()} />)
    fireEvent.click(screen.getByText(i18n.t('packer_editor.validate_btn')))
    await waitFor(() => expect(api.validateDefinition).toHaveBeenCalled())
    expect(await screen.findByText(i18n.t('packer_editor.validation_ok'))).toBeInTheDocument()
  })

  it('Save (create) calls createDefinition and onSaved', async () => {
    const onSaved = vi.fn()
    wrap(<PackerEditorForm isEdit={false} onClose={vi.fn()} onSaved={onSaved} />)
    fireEvent.change(screen.getByPlaceholderText(i18n.t('packer_editor.meta.name_ph')), { target: { value: 'D13' } })
    fireEvent.click(screen.getByText(i18n.t('packer_editor.save_btn')))
    await waitFor(() => expect(api.createDefinition).toHaveBeenCalled())
    expect(onSaved).toHaveBeenCalled()
  })

  it('shows a friendly message on 409 foreign_definition_exists', async () => {
    api.createDefinition.mockRejectedValueOnce({ response: { status: 409, data: { detail: 'foreign_definition_exists' } } })
    wrap(<PackerEditorForm isEdit={false} onClose={vi.fn()} onSaved={vi.fn()} />)
    fireEvent.change(screen.getByPlaceholderText(i18n.t('packer_editor.meta.name_ph')), { target: { value: 'D13' } })
    fireEvent.click(screen.getByText(i18n.t('packer_editor.save_btn')))
    expect(await screen.findByText(i18n.t('packer_editor.err_foreign'))).toBeInTheDocument()
  })

  it('HCL tab loads the generated projection via /preview', async () => {
    wrap(<PackerEditorForm isEdit={false} onClose={vi.fn()} onSaved={vi.fn()} />)
    fireEvent.click(screen.getByText(i18n.t('packer_editor.tab_hcl')))
    await waitFor(() => expect(api.previewDefinition).toHaveBeenCalled())
    expect(await screen.findByText((c) => c.includes('source "proxmox-iso"'))).toBeInTheDocument()
  })

  it('HCL tab: "edit directly" enables raw override seeded with the generated HCL', async () => {
    wrap(<PackerEditorForm isEdit={false} onClose={vi.fn()} onSaved={vi.fn()} />)
    fireEvent.click(screen.getByText(i18n.t('packer_editor.tab_hcl')))
    await waitFor(() => expect(api.previewDefinition).toHaveBeenCalled())
    fireEvent.click(screen.getByText(i18n.t('packer_editor.hcl_edit')))
    // Override-Banner + editierbarer Editor mit der generierten HCL als Startinhalt
    expect(await screen.findByText((c) => c.includes('HCL wird direkt bearbeitet'))).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.getByTestId('code-editor')).toHaveValue('source "proxmox-iso" "builder" {}'),
    )
  })

  it('HCL tab previews a brand-new (unnamed) definition via placeholder id/name', async () => {
    wrap(<PackerEditorForm isEdit={false} onClose={vi.fn()} onSaved={vi.fn()} />)
    fireEvent.click(screen.getByText(i18n.t('packer_editor.tab_hcl')))
    await waitFor(() => expect(api.previewDefinition).toHaveBeenCalled())
    const payload = api.previewDefinition.mock.calls[0][0]
    expect(payload.id).toBe('preview')
    expect(payload.name).toBe('Preview')
  })
})

// ── DefinitionList ────────────────────────────────────────────────────────────

describe('DefinitionList', () => {
  it('shows the empty state and a New button', () => {
    wrap(<DefinitionList onNew={vi.fn()} onEdit={vi.fn()} />)
    expect(screen.getByText(i18n.t('packer_editor.list.empty'))).toBeInTheDocument()
    expect(screen.getByText('+ ' + i18n.t('packer_editor.list.new'))).toBeInTheDocument()
  })

  it('lists definitions and triggers edit', () => {
    hookState.definitions = [{ id: 'debian-13', name: 'Debian 13', description: '', required_role: 'operator', source_type: 'proxmox-iso' }]
    const onEdit = vi.fn()
    wrap(<DefinitionList onNew={vi.fn()} onEdit={onEdit} />)
    expect(screen.getByText('Debian 13')).toBeInTheDocument()
    fireEvent.click(screen.getByText(i18n.t('common.edit')))
    expect(onEdit).toHaveBeenCalledWith('debian-13')
  })

  it('deletes a definition after confirm', async () => {
    hookState.definitions = [{ id: 'debian-13', name: 'Debian 13', description: '', required_role: 'operator', source_type: 'proxmox-iso' }]
    wrap(<DefinitionList onNew={vi.fn()} onEdit={vi.fn()} />)
    fireEvent.click(screen.getByText(i18n.t('common.delete')))
    // ConfirmModal confirm button
    const confirmBtn = screen.getAllByText(i18n.t('common.delete')).at(-1)
    fireEvent.click(confirmBtn)
    await waitFor(() => expect(api.deleteDefinition).toHaveBeenCalledWith('debian-13'))
  })
})
