// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-93: Task-Node der n8n-Canvas. Ein Ansible-Modul pro Node, inline
// bearbeitbar: Modul wählen → **zunächst nur Pflichtfelder** (SchemaFieldRenderer
// im progressiven Modus) → optionale Modul-Parameter über „+ Parameter" und
// allgemeine Parameter (when/register/loop/become/tags/notify) über „+ Option"
// gezielt anheften. Reorder (↑/↓), Entfernen, „+ Task" hängt den nächsten an.
// Angeheftete (aber noch leere) Felder werden lokal gehalten — der Node bleibt
// in React Flow gemountet, der State überlebt Modell-Changes. Alle Eingaben
// tragen `nodrag`.
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Handle, Position } from 'reactflow'
import { inputCls } from '../fields'
import ModulePicker from '../ModulePicker'
import SchemaFieldRenderer from '../SchemaFieldRenderer'
import { useModuleSchema } from '../hooks'

const PREFIX = 'ansible.builtin.'
const shortName = (fqcn) => (fqcn?.startsWith(PREFIX) ? fqcn.slice(PREFIX.length) : fqcn)
const toList = (s) => (s ?? '').split(',').map((x) => x.trim()).filter(Boolean)
const fromList = (a) => (Array.isArray(a) ? a.join(', ') : '')

// Reine UX-Vorauswahl: welche Parameter beim Wählen eines häufigen Moduls
// **sofort aufgeklappt** erscheinen (zusätzlich zu den Pflichtfeldern). Die
// Schema-Wahrheit bleibt ansible-doc — das hier steuert nur die Erst-Sicht,
// nicht-existierende Felder werden vom Renderer ignoriert. Unbekanntes Modul →
// nur Pflichtfelder. So sieht man z. B. bei copy gleich src/dest/owner/mode und
// bei apt (0 Pflichtfelder) name/state, statt eines leeren Nodes.
const DEFAULT_FIELDS = {
  'ansible.builtin.copy': ['src', 'dest', 'owner', 'group', 'mode'],
  'ansible.builtin.template': ['src', 'dest', 'owner', 'group', 'mode'],
  'ansible.builtin.file': ['path', 'state', 'owner', 'group', 'mode'],
  'ansible.builtin.apt': ['name', 'state'],
  'ansible.builtin.dnf': ['name', 'state'],
  'ansible.builtin.yum': ['name', 'state'],
  'ansible.builtin.package': ['name', 'state'],
  'ansible.builtin.service': ['name', 'state', 'enabled'],
  'ansible.builtin.systemd': ['name', 'state', 'enabled'],
  'ansible.builtin.lineinfile': ['path', 'line', 'state'],
  'ansible.builtin.blockinfile': ['path', 'block', 'state'],
  'ansible.builtin.user': ['name', 'state', 'groups'],
  'ansible.builtin.group': ['name', 'state'],
  'ansible.builtin.git': ['repo', 'dest', 'version'],
  'ansible.builtin.get_url': ['url', 'dest', 'mode'],
  'ansible.builtin.unarchive': ['src', 'dest'],
  'ansible.builtin.command': ['cmd', 'chdir'],
  'ansible.builtin.shell': ['cmd', 'chdir'],
  'ansible.builtin.apt_key': ['url', 'state'],
  'ansible.builtin.apt_repository': ['repo', 'state'],
}

// Allgemeine Task-Level-Parameter (AC-LEVEL). field = Schlüssel im Task-Modell.
const OPTION_DEFS = [
  { key: 'when', field: 'when', kind: 'text', ph: "ansible_facts.os_family == 'Debian'" },
  { key: 'loop', field: 'loop', kind: 'text', ph: '{{ packages }}' },
  { key: 'register', field: 'register_var', kind: 'text', ph: 'result' },
  { key: 'become', field: 'become', kind: 'bool' },
  { key: 'tags', field: 'tags', kind: 'list', ph: 'web, setup' },
  { key: 'notify', field: 'notify', kind: 'list', ph: 'reload nginx' },
]

function isOptionSet(task, def) {
  const v = task[def.field]
  if (def.kind === 'list') return Array.isArray(v) && v.length > 0
  if (def.kind === 'bool') return v != null
  return !!v
}

// ── Allgemeine Parameter (when/register/…) — progressives Anheften ────────────

function TaskOptions({ task, patchTask }) {
  const { t } = useTranslation()
  const [pinned, setPinned] = useState(() => new Set(OPTION_DEFS.filter((d) => isOptionSet(task, d)).map((d) => d.key)))
  const [pickerOpen, setPickerOpen] = useState(false)

  const visible = OPTION_DEFS.filter((d) => isOptionSet(task, d) || pinned.has(d.key))
  const hidden = OPTION_DEFS.filter((d) => !isOptionSet(task, d) && !pinned.has(d.key))

  const pin = (key) => setPinned((s) => new Set(s).add(key))
  const unpin = (def) => {
    setPinned((s) => { const n = new Set(s); n.delete(def.key); return n })
    patchTask({ [def.field]: def.kind === 'list' ? [] : null })
  }

  const renderField = (def) => {
    if (def.kind === 'bool') {
      const sel = task.become === true ? 'true' : task.become === false ? 'false' : ''
      return (
        <select className={inputCls + ' nodrag'} value={sel}
          onChange={(e) => patchTask({ become: e.target.value === '' ? null : e.target.value === 'true' })}>
          <option value="">{t('ansible_editor.bool_default')}</option>
          <option value="true">{t('ansible_editor.bool_true')}</option>
          <option value="false">{t('ansible_editor.bool_false')}</option>
        </select>
      )
    }
    if (def.kind === 'list') {
      return (
        <input className={inputCls + ' nodrag'} value={fromList(task[def.field])} placeholder={def.ph}
          onChange={(e) => patchTask({ [def.field]: toList(e.target.value) })} />
      )
    }
    return (
      <input className={inputCls + ' nodrag font-mono'} value={task[def.field] ?? ''} placeholder={def.ph}
        onChange={(e) => patchTask({ [def.field]: e.target.value || null })} />
    )
  }

  return (
    <div className="space-y-2 pt-2 mt-1 border-t border-portal-border">
      {visible.map((def) => (
        <div key={def.key} className="space-y-0.5">
          <div className="flex items-center gap-1">
            <span className="text-[11px] font-medium text-portal-info font-mono">{def.key}</span>
            <button type="button" onClick={() => unpin(def)}
              className="nodrag ml-auto text-portal-text3 hover:text-portal-danger text-xs leading-none">×</button>
          </div>
          {renderField(def)}
        </div>
      ))}
      {hidden.length > 0 && (
        <div className="nodrag relative">
          <button type="button" onClick={() => setPickerOpen((o) => !o)}
            className="text-[11px] text-portal-info hover:underline">
            + {t('ansible_editor.canvas.add_option')}
          </button>
          {pickerOpen && (
            <div className="absolute z-30 left-0 mt-1 w-44 rounded-md border border-portal-border bg-portal-bg2 shadow-lg">
              {hidden.map((def) => (
                <button key={def.key} type="button"
                  className="w-full text-left px-2 py-1 hover:bg-portal-info/10 border-b border-portal-border last:border-0 text-[11px] font-mono text-portal-text"
                  onClick={() => { pin(def.key); setPickerOpen(false) }}>{def.key}</button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Task-Node ─────────────────────────────────────────────────────────────────

export default function TaskNode({ data }) {
  const { t } = useTranslation()
  const { task, index, total, patchTask, setParam, removeTask, moveTask, addAfter } = data
  const { data: schema, isLoading } = useModuleSchema(task.module || null)
  const [pinnedParams, setPinnedParams] = useState(() => DEFAULT_FIELDS[task.module] ?? [])

  const pin = (name) => setPinnedParams((p) => (p.includes(name) ? p : [...p, name]))
  const unpin = (name) => setPinnedParams((p) => p.filter((x) => x !== name))
  // Modul wählen → die üblichen Felder dieses Moduls gleich aufklappen.
  const selectModule = (m) => { patchTask({ module: m }); setPinnedParams(DEFAULT_FIELDS[m] ?? []) }
  const changeModule = () => { patchTask({ module: '', params: {} }); setPinnedParams([]) }

  return (
    <div className="w-[340px] rounded-xl border border-portal-border bg-portal-bg shadow-md">
      <Handle type="target" position={Position.Left} className="!bg-portal-text3 !w-2 !h-2 !border-0" />

      {/* Kopf: Modulname + Aktionen */}
      <div className="flex items-center gap-1.5 px-3 py-2 border-b border-portal-border rounded-t-xl bg-portal-bg2/40">
        <span className="shrink-0 w-5 h-5 rounded-md bg-portal-accent/10 text-portal-accent text-[10px] font-bold grid place-items-center">{index + 1}</span>
        <span className="text-xs font-semibold text-portal-text font-mono truncate">
          {task.module ? shortName(task.module) : t('ansible_editor.canvas.pick_module')}
        </span>
        <div className="ml-auto flex items-center gap-0.5">
          <button type="button" disabled={index === 0} onClick={() => moveTask('up')}
            className="nodrag px-1 text-portal-text3 hover:text-portal-text disabled:opacity-30 text-xs" title={t('ansible_editor.task.up')}>↑</button>
          <button type="button" disabled={index === total - 1} onClick={() => moveTask('down')}
            className="nodrag px-1 text-portal-text3 hover:text-portal-text disabled:opacity-30 text-xs" title={t('ansible_editor.task.down')}>↓</button>
          <button type="button" onClick={removeTask}
            className="nodrag px-1 text-portal-text3 hover:text-portal-danger text-sm leading-none" title={t('common.delete')}>×</button>
        </div>
      </div>

      <div className="px-3 py-2.5 space-y-2.5">
        {!task.module ? (
          <ModulePicker value="" onSelect={selectModule} />
        ) : (
          <>
            <div className="flex items-center gap-1.5">
              <span className="text-[11px] text-portal-text3 font-mono shrink-0">{shortName(task.module)}</span>
              <button type="button" onClick={changeModule}
                className="nodrag ml-auto text-[11px] text-portal-text3 hover:text-portal-accent">{t('ansible_editor.module_change')}</button>
            </div>

            <input className={inputCls + ' nodrag text-xs'} value={task.name ?? ''}
              placeholder={t('ansible_editor.task.name_ph')}
              onChange={(e) => patchTask({ name: e.target.value })} />

            {isLoading && <p className="text-[11px] text-portal-text3">{t('common.loading')}</p>}
            {schema && (
              <SchemaFieldRenderer
                schema={schema}
                params={task.params}
                pinned={pinnedParams}
                onParamChange={(name, value) => setParam(name, value)}
                onPin={pin}
                onUnpin={unpin}
              />
            )}

            {schema && <TaskOptions task={task} patchTask={patchTask} />}
          </>
        )}
      </div>

      {/* „+ Task" hängt den nächsten an */}
      <button type="button" onClick={addAfter}
        title={t('ansible_editor.canvas.add_task')}
        className="nodrag absolute -right-3 top-1/2 -translate-y-1/2 z-10 w-6 h-6 rounded-full bg-portal-accent text-white text-sm font-bold grid place-items-center shadow hover:brightness-110">+</button>
      <Handle type="source" position={Position.Right} className="!bg-portal-text3 !w-2 !h-2 !border-0" />
    </div>
  )
}
