// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-76 Phase 1: Eine VM-Ressourcen-Karte im Formular-Editor (AC-UI-4).
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNodeVmOptions } from './hooks'

function Field({ label, children }) {
  return (
    <label className="flex flex-col gap-1 text-xs">
      <span className="text-portal-text2 font-medium">{label}</span>
      {children}
    </label>
  )
}

const inputCls =
  'w-full px-2 py-1.5 text-sm rounded-md border border-portal-border bg-portal-bg2 text-portal-text focus:outline-none focus:ring-1 focus:ring-portal-accent'

const MANUAL = '__manual__'

/**
 * Echtes <select>-Dropdown mit Optionen; fällt auf ein Text-Feld zurück, wenn
 * keine Optionen vorliegen (Cluster-API leer/offline) oder der Nutzer „Eigener
 * Wert…" wählt (z. B. Template, das die API nicht gelistet hat).
 */
function ComboField({ value, onChange, options, placeholder, customLabel }) {
  const { t } = useTranslation()
  const opts = Array.isArray(options) ? options : []
  // Start immer im Dropdown-Modus; ein nicht-gelisteter Wert (Default wie 'host'/
  // 'vmbr0' oder aus YAML geladen) wird als zusätzliche Option angezeigt, nicht
  // als Text-Modus erzwungen. „Eigener Wert…" wechselt bewusst in den Text-Modus.
  const [manual, setManual] = useState(false)

  // Keine Optionen → freies Textfeld (Fallback)
  if (opts.length === 0) {
    return (
      <input
        className={inputCls}
        value={value ?? ''}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
      />
    )
  }

  if (manual) {
    return (
      <div className="flex gap-1">
        <input
          className={inputCls}
          value={value ?? ''}
          placeholder={placeholder}
          autoFocus
          onChange={(e) => onChange(e.target.value)}
        />
        <button
          type="button"
          className="btn-table shrink-0"
          onClick={() => setManual(false)}
          title={t('stacks.form.use_list')}
        >☰</button>
      </div>
    )
  }

  const showCurrentValueOpt = value != null && value !== '' && !opts.includes(value)
  return (
    <select
      className={inputCls}
      value={value ?? ''}
      onChange={(e) => {
        if (e.target.value === MANUAL) { setManual(true); return }
        onChange(e.target.value)
      }}
    >
      <option value="">{placeholder}</option>
      {showCurrentValueOpt && <option value={value}>{value}</option>}
      {opts.map((o) => <option key={o} value={o}>{o}</option>)}
      <option value={MANUAL}>{customLabel}</option>
    </select>
  )
}

export default function StackResourceCard({
  resource,
  index,
  total,
  onChange,
  onRemove,
  onMove,
  onDuplicate,
  nodeOptions = [],
  templateOptions = [],
}) {
  const { t } = useTranslation()
  const r = resource

  const set = (key, val) => onChange(index, { ...r, [key]: val })
  const setNet = (key, val) => onChange(index, { ...r, network: { ...(r.network || {}), [key]: val } })
  const num = (v) => (v === '' || v == null ? '' : Number(v))

  // Node-abhängige Optionen (Bridges / CPU-Typen / vorhandene Tags) aus Proxmox.
  const { data: nodeOpts } = useNodeVmOptions(r.node)

  const currentTags = Array.isArray(r.tags)
    ? r.tags
    : (r.tags ? String(r.tags).split(',').map((s) => s.trim()).filter(Boolean) : [])
  const tagsStr = currentTags.join(', ')
  const addTag = (tg) => {
    if (currentTags.includes(tg)) return
    set('tags', [...currentTags, tg])
  }
  const availableTags = Array.isArray(nodeOpts?.tags)
    ? nodeOpts.tags.filter((tg) => !currentTags.includes(tg))
    : []

  // Node-Kapazität (weiche Hinweise — kein hartes Limit, CPU-Overcommit ist normal).
  const maxcpu = typeof nodeOpts?.maxcpu === 'number' ? nodeOpts.maxcpu : null
  const maxmemMB = typeof nodeOpts?.maxmem === 'number' ? Math.floor(nodeOpts.maxmem / 1048576) : null
  const maxmemGB = typeof nodeOpts?.maxmem === 'number' ? (nodeOpts.maxmem / 1073741824).toFixed(0) : null
  const coresOver = maxcpu != null && Number(r.cores ?? 1) > maxcpu
  const memOver = maxmemMB != null && Number(r.memory ?? 2048) > maxmemMB

  // Node-Namen (Strings)
  const nodeNames = [...new Set((nodeOptions || []).filter(Boolean))]

  // Template-Namen, node-abhängig gefiltert (Fallback: alle, wenn der Node
  // keine Treffer hat oder noch keiner gewählt ist).
  const tplRows = Array.isArray(templateOptions) ? templateOptions : []
  let tplNames = tplRows
    .filter((tpl) => !r.node || tpl.node === r.node)
    .map((tpl) => tpl.name || tpl.template)
    .filter(Boolean)
  if (tplNames.length === 0) {
    tplNames = tplRows.map((tpl) => tpl.name || tpl.template).filter(Boolean)
  }
  tplNames = [...new Set(tplNames.map(String))]

  return (
    <div className="border border-gray-200 dark:border-zinc-700 rounded-lg bg-white dark:bg-zinc-900 p-4 space-y-3" draggable={false}>
      {/* Header */}
      <div className="flex items-center justify-between gap-2">
        <h4 className="text-sm font-semibold text-gray-900 dark:text-zinc-100 flex items-center gap-2 min-w-0">
          <span className="text-portal-text3">#{index + 1}</span>
          <span className="shrink-0">{t('stacks.form.vm_card.title')}</span>
          {r.name ? <span className="text-portal-text2 font-normal truncate">— {r.name}</span> : null}
        </h4>
        <div className="flex items-center gap-1 shrink-0">
          <button
            type="button"
            onClick={() => onMove(index, index - 1)}
            disabled={index === 0}
            className="btn-table disabled:opacity-30"
            aria-label={t('stacks.form.move_up')}
            title={t('stacks.form.move_up')}
          >↑</button>
          <button
            type="button"
            onClick={() => onMove(index, index + 1)}
            disabled={index === total - 1}
            className="btn-table disabled:opacity-30"
            aria-label={t('stacks.form.move_down')}
            title={t('stacks.form.move_down')}
          >↓</button>
          <button
            type="button"
            onClick={() => onDuplicate(index)}
            className="btn-table"
            aria-label={t('stacks.form.duplicate_vm')}
            title={t('stacks.form.duplicate_vm')}
          >{t('stacks.form.duplicate_vm')}</button>
          <button
            type="button"
            onClick={() => onRemove(index)}
            className="btn-table-danger"
            aria-label={t('stacks.form.remove_vm')}
          >{t('common.remove')}</button>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <Field label={t('stacks.form.field.name') + ' *'}>
          <input className={inputCls} value={r.name ?? ''} onChange={(e) => set('name', e.target.value)} />
        </Field>
        <Field label={t('stacks.form.field.node') + ' *'}>
          <ComboField
            value={r.node ?? ''}
            onChange={(v) => set('node', v)}
            options={nodeNames}
            placeholder={t('stacks.form.select_ph')}
            customLabel={t('stacks.form.custom_value')}
          />
        </Field>
        <Field label={t('stacks.form.field.template') + ' *'}>
          <ComboField
            value={r.template ?? ''}
            onChange={(v) => set('template', v)}
            options={tplNames}
            placeholder={t('stacks.form.select_ph')}
            customLabel={t('stacks.form.custom_value')}
          />
        </Field>

        <Field label={t('stacks.form.field.count')}>
          <input type="number" min={1} max={50} className={inputCls} value={r.count ?? 1} onChange={(e) => set('count', num(e.target.value))} />
          <span className="text-[10px] text-portal-text3">{t('stacks.form.count_hint')}</span>
        </Field>
        <Field label={t('stacks.form.field.vmid')}>
          <input
            type="number"
            min={100}
            max={999999999}
            className={inputCls}
            value={r.vmid ?? ''}
            placeholder={t('stacks.form.vmid_auto')}
            onChange={(e) => set('vmid', e.target.value === '' ? undefined : Number(e.target.value))}
          />
          <span className="text-[10px] text-portal-text3">{t('stacks.form.vmid_hint')}</span>
        </Field>
        <Field label={t('stacks.form.field.cores')}>
          <input type="number" min={1} max={128} className={inputCls} value={r.cores ?? 1} onChange={(e) => set('cores', num(e.target.value))} />
          {maxcpu != null && (
            <span className={`text-[10px] ${coresOver ? 'text-portal-warn' : 'text-portal-text3'}`}>
              {t('stacks.form.of_n_cores', { n: maxcpu })}{coresOver ? ' ⚠' : ''}
            </span>
          )}
        </Field>
        <Field label={t('stacks.form.field.sockets')}>
          <input type="number" min={1} max={4} className={inputCls} value={r.sockets ?? 1} onChange={(e) => set('sockets', num(e.target.value))} />
        </Field>

        <Field label={t('stacks.form.field.memory')}>
          <input type="number" min={512} max={1048576} className={inputCls} value={r.memory ?? 2048} onChange={(e) => set('memory', num(e.target.value))} />
          {maxmemGB != null && (
            <span className={`text-[10px] ${memOver ? 'text-portal-warn' : 'text-portal-text3'}`}>
              {t('stacks.form.of_n_ram', { gb: maxmemGB })}{memOver ? ' ⚠' : ''}
            </span>
          )}
        </Field>
        <Field label={t('stacks.form.field.disk')}>
          <input type="number" min={1} max={16384} className={inputCls} value={r.disk ?? 32} onChange={(e) => set('disk', num(e.target.value))} />
        </Field>
        <Field label={t('stacks.form.field.cpu_type')}>
          <ComboField
            value={r.cpu_type ?? 'host'}
            onChange={(v) => set('cpu_type', v)}
            options={nodeOpts?.cpu_types || []}
            placeholder={t('stacks.form.select_ph')}
            customLabel={t('stacks.form.custom_value')}
          />
        </Field>

        <Field label={t('stacks.form.field.bridge')}>
          <ComboField
            value={r.network?.bridge ?? ''}
            onChange={(v) => setNet('bridge', v)}
            options={nodeOpts?.bridges || []}
            placeholder="vmbr0"
            customLabel={t('stacks.form.custom_value')}
          />
        </Field>
        <Field label={t('stacks.form.field.vlan_tag')}>
          <input type="number" min={1} max={4094} className={inputCls} value={r.network?.tag ?? ''} onChange={(e) => setNet('tag', e.target.value === '' ? undefined : Number(e.target.value))} />
        </Field>
        <Field label={t('stacks.form.field.pool')}>
          <input className={inputCls} value={r.pool ?? ''} onChange={(e) => set('pool', e.target.value || undefined)} />
        </Field>

        <div className="flex flex-col gap-1 text-xs col-span-2">
          <span className="text-portal-text2 font-medium">{t('stacks.form.field.tags')}</span>
          <input
            className={inputCls}
            value={tagsStr}
            placeholder="web, production"
            onChange={(e) => set('tags', e.target.value.split(',').map((s) => s.trim()).filter(Boolean))}
          />
          {availableTags.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-1">
              {availableTags.slice(0, 24).map((tg) => (
                <button
                  type="button"
                  key={tg}
                  onClick={() => addTag(tg)}
                  className="text-[10px] px-1.5 py-0.5 rounded border border-portal-border text-portal-text2 hover:border-portal-accent hover:text-portal-white transition-colors"
                  title={t('stacks.form.add_tag', { tag: tg })}
                >+ {tg}</button>
              ))}
            </div>
          )}
        </div>
        <label className="flex items-center gap-2 text-xs text-portal-text2 mt-5 col-span-2 md:col-span-1">
          <input
            type="checkbox"
            checked={r.start_after_create !== false}
            onChange={(e) => set('start_after_create', e.target.checked)}
            className="accent-[var(--accent)]"
          />
          {t('stacks.form.field.start_after_create')}
        </label>
        <label className="flex flex-col gap-0.5 text-xs text-portal-text2 mt-5 col-span-2 md:col-span-1">
          <span className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={r.agent === true}
              onChange={(e) => set('agent', e.target.checked)}
              className="accent-[var(--accent)]"
            />
            {t('stacks.form.field.agent')}
          </span>
          <span className="text-[10px] text-portal-text3 ml-6">{t('stacks.form.agent_hint')}</span>
        </label>
      </div>
    </div>
  )
}
