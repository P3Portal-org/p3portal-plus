// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-93: schema-getriebener Feld-Renderer mit Progressive Disclosure (n8n-Stil).
// Zeigt **zunächst nur die Pflichtfelder** eines Moduls; optionale Parameter
// werden über „+ Parameter" gezielt angeheftet. Kein hartkodiertes Modul-Wissen:
// das BE liefert pro Parameter widget/type/required/default/choices/description.
//
// Sichtbar = required ∪ (gesetzt in params) ∪ angeheftet (pinned). Ein leerer
// Wert löscht den Parameter aus params; ein angehefteter optionaler kann per „×"
// wieder entfernt werden. Werte (AC-JINJA/AC-SUB) wie zuvor: text→Jinja direkt,
// number/bool→Input + „ƒx"-Jinja-Umschalter, list/dict/suboptions→Raw-YAML
// (clientseitig js-yaml-geparst).
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import yaml from 'js-yaml'
import { inputCls } from './fields'
import PlainCodeEditor from './PlainCodeEditor'

function isEmpty(v) {
  if (v === undefined || v === null) return true
  if (typeof v === 'string') return v.trim() === ''
  return false
}

// ── Raw-YAML-Feld (list/dict/suboptions) ──────────────────────────────────────

function RawYamlField({ value, onChange }) {
  const { t } = useTranslation()
  const [text, setText] = useState(() => {
    if (value === undefined || value === null) return ''
    if (typeof value === 'string') return value
    try { return yaml.dump(value, { lineWidth: 120 }).trimEnd() } catch { return '' }
  })
  const [error, setError] = useState(null)

  const handle = (next) => {
    setText(next)
    if (next.trim() === '') { setError(null); onChange(undefined); return }
    try {
      const parsed = yaml.load(next)
      setError(null)
      onChange(parsed)
    } catch (e) {
      setError(e?.reason || e?.message || t('ansible_editor.raw_yaml_invalid'))
    }
  }

  return (
    <div className="nodrag">
      <PlainCodeEditor value={text} onChange={handle} minHeight="70px" />
      <span className="text-[10px] text-portal-text3">{t('ansible_editor.raw_yaml_hint')}</span>
      {error && <span className="block text-[11px] text-portal-danger">⚠ {error}</span>}
    </div>
  )
}

// ── Jinja-Umschalter für number / bool ────────────────────────────────────────

function JinjaToggle({ active, onToggle }) {
  const { t } = useTranslation()
  return (
    <button
      type="button"
      onClick={onToggle}
      title={t('ansible_editor.jinja_toggle')}
      className={`nodrag shrink-0 px-1.5 rounded-md border text-[11px] font-mono ${
        active ? 'border-portal-accent text-portal-accent' : 'border-portal-border text-portal-text3 hover:text-portal-text2'
      }`}
    >ƒx</button>
  )
}

function NumberOrJinja({ value, onChange }) {
  const [jinja, setJinja] = useState(() => typeof value === 'string')
  if (jinja) {
    return (
      <div className="flex gap-1">
        <input className={inputCls + ' nodrag font-mono'} value={value ?? ''} placeholder="{{ my_var }}"
          onChange={(e) => onChange(e.target.value === '' ? undefined : e.target.value)} />
        <JinjaToggle active onToggle={() => setJinja(false)} />
      </div>
    )
  }
  return (
    <div className="flex gap-1">
      <input type="number" className={inputCls + ' nodrag'} value={value ?? ''}
        onChange={(e) => onChange(e.target.value === '' ? undefined : Number(e.target.value))} />
      <JinjaToggle active={false} onToggle={() => setJinja(true)} />
    </div>
  )
}

function BoolOrJinja({ value, onChange }) {
  const { t } = useTranslation()
  const [jinja, setJinja] = useState(() => typeof value === 'string')
  if (jinja) {
    return (
      <div className="flex gap-1">
        <input className={inputCls + ' nodrag font-mono'} value={typeof value === 'string' ? value : ''} placeholder="{{ my_flag }}"
          onChange={(e) => onChange(e.target.value === '' ? undefined : e.target.value)} />
        <JinjaToggle active onToggle={() => setJinja(false)} />
      </div>
    )
  }
  const sel = value === true ? 'true' : value === false ? 'false' : ''
  return (
    <div className="flex gap-1">
      <select className={inputCls + ' nodrag'} value={sel}
        onChange={(e) => onChange(e.target.value === '' ? undefined : e.target.value === 'true')}>
        <option value="">{t('ansible_editor.bool_default')}</option>
        <option value="true">{t('ansible_editor.bool_true')}</option>
        <option value="false">{t('ansible_editor.bool_false')}</option>
      </select>
      <JinjaToggle active={false} onToggle={() => setJinja(true)} />
    </div>
  )
}

// ── Ein Parameter-Feld (Label + Widget + optional Entfernen) ──────────────────

function ParamField({ param, value, onChange, onRemove }) {
  const [showInfo, setShowInfo] = useState(false)
  const set = (v) => onChange(param.name, isEmpty(v) ? undefined : v)
  let widget
  if (param.widget === 'raw_yaml') {
    widget = <RawYamlField value={value} onChange={(v) => onChange(param.name, v)} />
  } else if (param.widget === 'dropdown') {
    widget = (
      <select className={inputCls + ' nodrag'} value={value ?? ''} onChange={(e) => set(e.target.value)}>
        <option value="">{param.default != null ? String(param.default) : '—'}</option>
        {(param.choices || []).map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
    )
  } else if (param.widget === 'number') {
    widget = <NumberOrJinja value={value} onChange={(v) => onChange(param.name, v)} />
  } else if (param.widget === 'toggle') {
    widget = <BoolOrJinja value={value} onChange={(v) => onChange(param.name, v)} />
  } else {
    widget = (
      <input className={inputCls + ' nodrag'} value={value ?? ''}
        placeholder={param.default != null ? String(param.default) : ''}
        onChange={(e) => set(e.target.value)} />
    )
  }
  return (
    <div className="space-y-0.5">
      <div className="flex items-center gap-1">
        <span className="text-[11px] font-medium text-portal-text2 font-mono">
          {param.name}{param.required && <span className="text-portal-accent"> *</span>}
        </span>
        {param.description && (
          <button type="button" onClick={() => setShowInfo((s) => !s)} title={param.description}
            className={`nodrag shrink-0 w-3.5 h-3.5 rounded-full border text-[9px] font-semibold leading-none grid place-items-center ${
              showInfo ? 'border-portal-accent text-portal-accent' : 'border-portal-text3 text-portal-text3 hover:border-portal-text2 hover:text-portal-text2'
            }`}>i</button>
        )}
        {onRemove && (
          <button type="button" onClick={onRemove} aria-label="remove"
            className="nodrag ml-auto text-portal-text3 hover:text-portal-danger text-xs leading-none">×</button>
        )}
      </div>
      {widget}
      {showInfo && param.description && <span className="block text-[10px] text-portal-text3 leading-tight">{param.description}</span>}
    </div>
  )
}

// ── Renderer (Progressive Disclosure) ─────────────────────────────────────────

export default function SchemaFieldRenderer({ schema, params, pinned = [], onParamChange, onPin, onUnpin }) {
  const { t } = useTranslation()
  const [pickerOpen, setPickerOpen] = useState(false)
  const [query, setQuery] = useState('')
  if (!schema) return <p className="text-[11px] text-portal-text3">{t('common.loading')}</p>

  // Progressive Disclosure (nur Pflichtfelder + angeheftete) gilt im Node-Modus
  // (onPin gesetzt). Ohne Pin-Callbacks (Alt-/Formular-Pfad) werden alle Felder
  // gezeigt — abwärtskompatibel, bis der Canvas-Umbau die letzten Konsumenten
  // ablöst.
  const progressive = typeof onPin === 'function'
  const all = schema.params || []
  const pinnedSet = new Set(pinned)
  const isVisible = (p) => !progressive || p.required || params?.[p.name] !== undefined || pinnedSet.has(p.name)
  const visible = all.filter(isVisible)
  const hidden = progressive ? all.filter((p) => !isVisible(p)) : []

  return (
    <div className="space-y-2">
      {visible.length === 0 && hidden.length === 0 && (
        <p className="text-[11px] text-portal-text3">{t('ansible_editor.no_params')}</p>
      )}
      {visible.map((p) => (
        <ParamField
          key={p.name}
          param={p}
          value={params?.[p.name]}
          onChange={onParamChange}
          onRemove={p.required ? undefined : () => { onParamChange(p.name, undefined); onUnpin?.(p.name) }}
        />
      ))}

      {hidden.length > 0 && (
        <div className="nodrag relative">
          <button type="button"
            onClick={() => { setPickerOpen((o) => !o); setQuery('') }}
            className="text-xs text-portal-accent hover:underline">
            + {t('ansible_editor.add_param')} ({hidden.length})
          </button>
          {pickerOpen && (
            <div className="absolute z-30 left-0 mt-1 w-72 rounded-md border border-portal-border bg-portal-bg2 shadow-lg">
              <input
                autoFocus
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={t('ansible_editor.param_search_ph')}
                className="w-full px-2.5 py-2 text-xs rounded-t-md border-b border-portal-border bg-transparent text-portal-text focus:outline-none"
              />
              <div className="nowheel max-h-72 overflow-y-auto overscroll-contain">
                {(() => {
                  const q = query.trim().toLowerCase()
                  const list = q
                    ? hidden.filter((p) => p.name.toLowerCase().includes(q) || (p.description || '').toLowerCase().includes(q))
                    : hidden
                  if (list.length === 0) {
                    return <p className="px-2.5 py-2 text-[11px] text-portal-text3">{t('ansible_editor.modules_empty')}</p>
                  }
                  return list.map((p) => (
                    <button key={p.name} type="button"
                      className="w-full text-left px-2.5 py-1.5 hover:bg-portal-accent/10 border-b border-portal-border last:border-0"
                      onClick={() => { onPin?.(p.name); setPickerOpen(false); setQuery('') }}>
                      <span className="text-xs font-mono text-portal-text">{p.name}</span>
                      {p.required && <span className="text-portal-accent"> *</span>}
                      {p.description && <span className="block text-[10px] text-portal-text3 line-clamp-2 leading-tight">{p.description}</span>}
                    </button>
                  ))
                })()}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
