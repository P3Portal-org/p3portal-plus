// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-93: Ansible Visual Editor – Modell-Helper + Schema-Feld-Renderer (Kern) +
// Modul-Picker + Task-Builder + Formular + Liste.
import { useState } from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { I18nextProvider } from 'react-i18next'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import i18n from '../../i18n'

import { deriveId, emptyTask, buildPayload, ensureTaskUids, newModel } from './model'

// React Flow braucht ResizeObserver/Layout-APIs, die jsdom nicht hat. Die
// Canvas wird per E2E/manuell abgedeckt (Muster PROJ-75); die Form-Tests pruefen
// nur Save/Validate und stubben die Canvas weg.
vi.mock('./AnsibleEditorCanvas', () => ({ default: () => <div data-testid="canvas-stub" /> }))

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
  createDefinition: vi.fn(() => Promise.resolve({ id: 'nginx-setup', name: 'Nginx', targets: 'guest', task_count: 1 })),
  updateDefinition: vi.fn(() => Promise.resolve({})),
  validateDefinition: vi.fn(() => Promise.resolve({ ok: true, errors: [], warnings: [] })),
  previewDefinition: vi.fn(() => Promise.resolve({ yaml: '- hosts: managed', meta_yaml: '', files: {}, warnings: [] })),
  listDefinitions: vi.fn(() => Promise.resolve([])),
  deleteDefinition: vi.fn(() => Promise.resolve()),
}))
vi.mock('./api', () => api)

const COPY_SCHEMA = {
  module: 'ansible.builtin.copy',
  params: [
    { name: 'dest', widget: 'text', type: 'path', required: true, description: 'Remote path.' },
    { name: 'mode', widget: 'text', type: 'raw', required: false, description: 'Permissions.' },
    { name: 'force', widget: 'toggle', type: 'bool', required: false },
    { name: 'count', widget: 'number', type: 'int', required: false },
    { name: 'state', widget: 'dropdown', type: 'str', required: false, choices: ['present', 'absent'] },
    { name: 'headers', widget: 'raw_yaml', type: 'dict', required: false, description: 'Headers.' },
  ],
}

vi.mock('./hooks', () => ({
  useDefinitions: () => ({ data: hookState.definitions, isLoading: false, error: null }),
  useDeleteDefinition: () => ({ mutateAsync: api.deleteDefinition }),
  useModules: () => ({
    data: [
      { name: 'ansible.builtin.copy', short_description: 'Copy files to remote locations' },
      { name: 'ansible.builtin.apt', short_description: 'Manages apt-packages' },
    ],
    isLoading: false, error: null,
  }),
  useModuleSchema: () => ({ data: COPY_SCHEMA, isLoading: false, error: null }),
  useDefinition: () => ({ data: null, isLoading: false, error: null }),
}))

const hookState = { definitions: [] }

import SchemaFieldRenderer from './SchemaFieldRenderer'
import ModulePicker from './ModulePicker'
import PlayHeaderSection from './PlayHeaderSection'
import TaskList from './TaskList'
import AnsibleEditorForm from './AnsibleEditorForm'
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

// ── Modell-Helper ─────────────────────────────────────────────────────────────

describe('AnsibleEditor – model helpers', () => {
  it('deriveId slugifies + strips dots', () => {
    expect(deriveId('Nginx Setup!')).toBe('nginx-setup')
    expect(deriveId('My..Playbook')).not.toContain('..')
  })

  it('emptyTask carries a stable _uid', () => {
    const a = emptyTask()
    const b = emptyTask()
    expect(a._uid).toBeTruthy()
    expect(a._uid).not.toBe(b._uid)
  })

  it('buildPayload strips _idTouched and Task._uid', () => {
    const model = { ...newModel(), _idTouched: true, tasks: [emptyTask()] }
    const payload = buildPayload(model)
    expect('_idTouched' in payload).toBe(false)
    expect('_uid' in payload.tasks[0]).toBe(false)
    expect(payload.tasks[0].module).toBeDefined()
  })

  it('ensureTaskUids gives loaded tasks a _uid', () => {
    const loaded = { tasks: [{ module: 'ansible.builtin.ping', params: {} }] }
    const out = ensureTaskUids(loaded)
    expect(out.tasks[0]._uid).toBeTruthy()
  })
})

// ── SchemaFieldRenderer (der generische Kern) ─────────────────────────────────

// State-haltende Harness — ein kontrollierter Input ohne State-Update feuert
// das zweite change auf denselben Wert nicht.
function SchemaHarness({ onSpy }) {
  const [params, setParams] = useState({})
  return (
    <SchemaFieldRenderer
      schema={COPY_SCHEMA}
      params={params}
      onParamChange={(name, value) => {
        setParams((p) => {
          const n = { ...p }
          if (value === undefined) delete n[name]
          else n[name] = value
          return n
        })
        onSpy(name, value)
      }}
    />
  )
}

describe('AnsibleEditor – SchemaFieldRenderer', () => {
  it('renders the correct widget per parameter + marks required', () => {
    wrap(<SchemaFieldRenderer schema={COPY_SCHEMA} params={{}} onParamChange={() => {}} />)
    expect(screen.getByText('dest')).toBeInTheDocument()
    // dropdown for state (choices) + bool 3-way for force → at least one combobox
    expect(screen.getAllByRole('combobox').length).toBeGreaterThan(0)
    // raw_yaml renders a code editor (mocked textarea)
    expect(screen.getAllByTestId('code-editor').length).toBeGreaterThan(0)
  })

  it('a text value calls onParamChange; clearing deletes the param', () => {
    const onSpy = vi.fn()
    wrap(<SchemaHarness onSpy={onSpy} />)
    const inputs = screen.getAllByRole('textbox')
    fireEvent.change(inputs[0], { target: { value: '/etc/x' } })
    expect(onSpy).toHaveBeenCalledWith('dest', '/etc/x')
    fireEvent.change(inputs[0], { target: { value: '' } })
    expect(onSpy).toHaveBeenCalledWith('dest', undefined)
  })

  it('raw_yaml field parses YAML to a structured value (AC-SUB)', () => {
    const onChange = vi.fn()
    wrap(<SchemaFieldRenderer schema={COPY_SCHEMA} params={{}} onParamChange={onChange} />)
    const yamlEditor = screen.getAllByTestId('code-editor')[0]
    fireEvent.change(yamlEditor, { target: { value: 'X-Test: 1' } })
    expect(onChange).toHaveBeenCalledWith('headers', { 'X-Test': 1 })
  })

  it('invalid raw_yaml shows an error and does not emit (AC-SUB-2)', () => {
    const onChange = vi.fn()
    wrap(<SchemaFieldRenderer schema={COPY_SCHEMA} params={{}} onParamChange={onChange} />)
    const yamlEditor = screen.getAllByTestId('code-editor')[0]
    fireEvent.change(yamlEditor, { target: { value: 'a: [unclosed' } })
    expect(onChange).not.toHaveBeenCalledWith('headers', expect.anything())
  })

  it('bool widget emits true/false via the 3-way select', () => {
    const onChange = vi.fn()
    wrap(<SchemaFieldRenderer schema={COPY_SCHEMA} params={{}} onParamChange={onChange} />)
    const selects = screen.getAllByRole('combobox')
    // first combobox is the bool 3-way (force) — order: dest(text) mode(text) force(bool) ...
    const boolSel = selects.find((s) => Array.from(s.options).some((o) => o.value === 'true'))
    fireEvent.change(boolSel, { target: { value: 'true' } })
    expect(onChange).toHaveBeenCalledWith('force', true)
  })
})

// ── ModulePicker ──────────────────────────────────────────────────────────────

describe('AnsibleEditor – ModulePicker', () => {
  it('lists modules, filters by search, selects one', () => {
    const onSelect = vi.fn()
    wrap(<ModulePicker value="" onSelect={onSelect} />)
    const search = screen.getByRole('textbox')
    fireEvent.focus(search)
    expect(screen.getByText('copy')).toBeInTheDocument()
    fireEvent.change(search, { target: { value: 'apt' } })
    expect(screen.queryByText('copy')).not.toBeInTheDocument()
    fireEvent.click(screen.getByText('apt'))
    expect(onSelect).toHaveBeenCalledWith('ansible.builtin.apt')
  })

  it('shows the selected module with a change button', () => {
    wrap(<ModulePicker value="ansible.builtin.copy" onSelect={() => {}} />)
    expect(screen.getByText('ansible.builtin.copy')).toBeInTheDocument()
  })
})

// ── PlayHeaderSection ─────────────────────────────────────────────────────────

describe('AnsibleEditor – PlayHeaderSection', () => {
  it('shows the localhost hint only for the localhost target (AC-PLAY-3)', () => {
    const { rerender } = wrap(<PlayHeaderSection header={{ targets: 'guest' }} onChange={() => {}} />)
    expect(screen.queryByText(/Proxmox-REST/)).not.toBeInTheDocument()
    rerender(
      <I18nextProvider i18n={i18n}><PlayHeaderSection header={{ targets: 'localhost' }} onChange={() => {}} /></I18nextProvider>,
    )
    expect(screen.getByText(/Proxmox-REST/)).toBeInTheDocument()
  })
})

// ── TaskList ──────────────────────────────────────────────────────────────────

describe('AnsibleEditor – TaskList', () => {
  it('adds the first task', () => {
    const onChange = vi.fn()
    wrap(<TaskList tasks={[]} onChange={onChange} />)
    fireEvent.click(screen.getByText(/Ersten Task hinzufügen/))
    expect(onChange).toHaveBeenCalled()
    expect(onChange.mock.calls[0][0]).toHaveLength(1)
  })
})

// ── AnsibleEditorForm ─────────────────────────────────────────────────────────

describe('AnsibleEditor – Form', () => {
  it('save (new) calls createDefinition without FE-only state', async () => {
    const onSaved = vi.fn()
    wrap(<AnsibleEditorForm isEdit={false} onClose={() => {}} onSaved={onSaved} />)
    // Pflicht: name + id setzen
    fireEvent.change(screen.getByPlaceholderText('Nginx einrichten'), { target: { value: 'Nginx' } })
    fireEvent.click(screen.getByText('Speichern'))
    await waitFor(() => expect(api.createDefinition).toHaveBeenCalled())
    const payload = api.createDefinition.mock.calls[0][0]
    expect('_idTouched' in payload).toBe(false)
    expect(onSaved).toHaveBeenCalled()
  })

  it('validate surfaces errors and warnings', async () => {
    api.validateDefinition.mockResolvedValueOnce({ ok: false, errors: ['Task 1: dest fehlt'], warnings: ['Task ohne Namen'] })
    wrap(<AnsibleEditorForm isEdit={false} onClose={() => {}} onSaved={() => {}} />)
    fireEvent.click(screen.getByText('Validieren'))
    await waitFor(() => expect(screen.getByText(/dest fehlt/)).toBeInTheDocument())
    expect(screen.getByText(/Task ohne Namen/)).toBeInTheDocument()
  })

  it('a 409 conflict shows a friendly message', async () => {
    api.createDefinition.mockRejectedValueOnce({ response: { status: 409, data: { detail: 'foreign_definition_exists' } } })
    wrap(<AnsibleEditorForm isEdit={false} onClose={() => {}} onSaved={() => {}} />)
    fireEvent.change(screen.getByPlaceholderText('Nginx einrichten'), { target: { value: 'X' } })
    fireEvent.click(screen.getByText('Speichern'))
    await waitFor(() => expect(screen.getByText(/per ZIP\/Git/)).toBeInTheDocument())
  })

  it('a 400 validation_failed surfaces the backend errors', async () => {
    api.createDefinition.mockRejectedValueOnce({
      response: { status: 400, data: { detail: { error: 'validation_failed', errors: ['Modul existiert nicht'] } } },
    })
    wrap(<AnsibleEditorForm isEdit={false} onClose={() => {}} onSaved={() => {}} />)
    fireEvent.change(screen.getByPlaceholderText('Nginx einrichten'), { target: { value: 'X' } })
    fireEvent.click(screen.getByText('Speichern'))
    await waitFor(() => expect(screen.getByText(/Modul existiert nicht/)).toBeInTheDocument())
  })
})

// ── DefinitionList ────────────────────────────────────────────────────────────

describe('AnsibleEditor – DefinitionList', () => {
  it('shows the empty state', () => {
    wrap(<DefinitionList onNew={() => {}} onEdit={() => {}} />)
    expect(screen.getByText(/Noch keine editor-eigene Definition/)).toBeInTheDocument()
  })

  it('lists definitions with target + task count', () => {
    hookState.definitions = [{ id: 'nginx-setup', name: 'Nginx', targets: 'guest', task_count: 3 }]
    wrap(<DefinitionList onNew={() => {}} onEdit={() => {}} />)
    expect(screen.getByText('Nginx')).toBeInTheDocument()
    expect(screen.getByText('nginx-setup')).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
  })
})
