// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-91: deklarativer Firewall-Regel-Editor für Stacks (Gast-Regel ODER
// Security-Group-Regel). Reuse der PROJ-90-Feldstruktur (Richtung/Aktion,
// Macro-XOR-Proto/Port-Toggle, ICMP-Typ-Dropdown, Alias/IPSet-Ref-Dropdown),
// aber rein deklarativ: kein API-Call, kein `pos` — `onSave(rule)` gibt das
// Regel-Objekt im StackFirewallRule-Schema an die Karte zurück (Reihenfolge =
// Listen-Position, AC-MODEL-5).
import { useState } from 'react'

const inputCls =
  'w-full px-2 py-1.5 text-sm rounded-md border border-portal-border bg-portal-bg2 text-portal-text focus:outline-none focus:ring-1 focus:ring-portal-accent'
const labelCls = 'block text-xs font-medium text-portal-text2 mb-1'
const smallCls = 'text-[11px] text-portal-text3 mt-1'

const LOG_LEVELS = ['nolog', 'emerg', 'alert', 'crit', 'err', 'warning', 'notice', 'info', 'debug']
const PROTO_OPTIONS = ['tcp', 'udp', 'icmp', 'icmpv6', 'igmp', 'gre', 'esp', 'ah', 'sctp']
const ICMP_TYPES = ['echo-request', 'echo-reply', 'destination-unreachable', 'time-exceeded', 'redirect', 'parameter-problem']
const CUSTOM = '__custom__'

// Kuratiertes Dropdown + „Eigener Wert…"-Escape (Muster PROJ-90/SdnZoneFormModal).
// Leere Optionsliste → reines Textfeld (Caller kann ohne Dropdown opt-outen).
function ComboField({ id, value, onChange, options, placeholder, emptyLabel, customLabel }) {
  const [custom, setCustom] = useState(
    () => options.length > 0 && value !== '' && !options.includes(value),
  )
  if (options.length === 0) {
    return <input id={id} type="text" value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} className={inputCls} />
  }
  if (custom) {
    return (
      <div className="flex gap-1">
        <input id={id} type="text" value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} className={inputCls} />
        <button type="button" onClick={() => { setCustom(false); onChange('') }} className="btn-table shrink-0">☰</button>
      </div>
    )
  }
  return (
    <select
      id={id}
      value={options.includes(value) ? value : ''}
      onChange={(e) => { if (e.target.value === CUSTOM) { setCustom(true); onChange('') } else onChange(e.target.value) }}
      className={inputCls}
    >
      <option value="">{emptyLabel}</option>
      {options.map((o) => <option key={o} value={o}>{o}</option>)}
      <option value={CUSTOM}>{customLabel}</option>
    </select>
  )
}

// Quell-/Ziel-Feld: Freitext (IP/CIDR/Range) + Dropdown zum Einsetzen eines
// bestehenden Alias / IPSet (aus /datacenter/refs). Alias → bloßer Name, IPSet →
// „+name" (beides vom Server-Adress-Parser akzeptiert, AC-RULE-3).
function AddrField({ id, value, onChange, refs, placeholder, insertLabel }) {
  const aliasRefs = refs.filter((r) => r.type === 'alias')
  const ipsetRefs = refs.filter((r) => r.type === 'ipset')
  const tokenOf = (r) => (r.type === 'ipset' ? `+${r.name}` : r.name)
  return (
    <>
      <input id={id} type="text" value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} className={inputCls} />
      {refs.length > 0 && (
        <select
          aria-label={insertLabel}
          value=""
          onChange={(e) => { if (e.target.value) onChange(e.target.value) }}
          className="mt-1 w-full bg-portal-bg2 border border-portal-border text-portal-text2 px-2 py-1.5 text-xs rounded focus:outline-none focus:border-portal-accent"
        >
          <option value="">＋ {insertLabel}</option>
          {aliasRefs.length > 0 && (
            <optgroup label="Aliases">
              {aliasRefs.map((r) => <option key={`a-${r.name}`} value={tokenOf(r)}>{r.name}{r.comment ? ` – ${r.comment}` : ''}</option>)}
            </optgroup>
          )}
          {ipsetRefs.length > 0 && (
            <optgroup label="IPSets">
              {ipsetRefs.map((r) => <option key={`i-${r.name}`} value={tokenOf(r)}>+{r.name}{r.comment ? ` – ${r.comment}` : ''}</option>)}
            </optgroup>
          )}
        </select>
      )}
    </>
  )
}

function buildInitial(rule) {
  if (!rule) {
    return {
      type: 'out', action: 'ACCEPT', group: '', enable: true,
      protoMode: 'custom', macro: '', proto: '', sport: '', dport: '', icmp_type: '',
      source: '', dest: '', iface: '', log: '', comment: '',
    }
  }
  const isGroup = rule.type === 'group'
  return {
    type: rule.type || 'out',
    action: isGroup ? 'ACCEPT' : (rule.action || 'ACCEPT'),
    group: isGroup ? (rule.action || '') : '',
    enable: rule.enable !== false,
    protoMode: rule.macro ? 'macro' : 'custom',
    macro: rule.macro || '',
    proto: rule.proto || '',
    sport: rule.sport || '',
    dport: rule.dport || '',
    icmp_type: rule.icmp_type || '',
    source: rule.source || '',
    dest: rule.dest || '',
    iface: rule.iface || '',
    log: rule.log || '',
    comment: rule.comment || '',
  }
}

// Baut das StackFirewallRule-Objekt (ohne pos; leere Felder weggelassen).
function buildRule(form) {
  const out = { type: form.type, enable: form.enable }
  out.action = form.type === 'group' ? form.group.trim() : form.action
  if (form.protoMode === 'macro') {
    if (form.macro.trim()) out.macro = form.macro.trim()
  } else {
    if (form.proto.trim()) out.proto = form.proto.trim()
    if (form.sport.trim()) out.sport = form.sport.trim()
    if (form.dport.trim()) out.dport = form.dport.trim()
    if (form.icmp_type.trim() && /^icmp/i.test(form.proto.trim())) out.icmp_type = form.icmp_type.trim()
  }
  if (form.source.trim()) out.source = form.source.trim()
  if (form.dest.trim()) out.dest = form.dest.trim()
  if (form.iface.trim()) out.iface = form.iface.trim()
  if (form.log) out.log = form.log
  if (form.comment.trim()) out.comment = form.comment.trim()
  return out
}

/**
 * StackFirewallRuleModal – ein deklarativer Regel-Editor. `securityGroupNames`
 * speist das Aktions-Dropdown für `group`-Regeln (stack-eigene + bestehende SGs,
 * AC-SG-2/3); `withGroup=false` blendet die group-Richtung aus (für SG-eigene
 * Regeln, die selbst keine SG referenzieren sollen).
 */
export default function StackFirewallRuleModal({
  t, rule, refs = [], macros = [], securityGroupNames = [], withGroup = true, onSave, onClose,
}) {
  const isEdit = Boolean(rule)
  const [form, setForm] = useState(() => buildInitial(rule))
  const [error, setError] = useState('')

  const set = (key) => (e) => {
    const v = e.target.type === 'checkbox' ? e.target.checked : e.target.value
    setForm((prev) => ({ ...prev, [key]: v }))
  }
  const setVal = (key) => (v) => setForm((prev) => ({ ...prev, [key]: v }))
  const isIcmp = /^icmp/i.test(form.proto.trim())

  const handleSubmit = (e) => {
    e.preventDefault()
    if (form.type === 'group' && !form.group.trim()) {
      setError(t('stacks.firewall.rule.group_required')); return
    }
    onSave(buildRule(form))
    onClose()
  }

  const customLabel = t('stacks.form.custom_value')

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50">
      <div
        className="relative bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-700 shadow-2xl w-full max-w-2xl rounded-xl flex flex-col max-h-[92vh]"
        role="dialog"
        aria-modal="true"
        aria-labelledby="stack-fw-rule-title"
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200 dark:border-zinc-700 shrink-0">
          <h2 id="stack-fw-rule-title" className="text-sm font-semibold text-gray-900 dark:text-white">
            {isEdit ? t('stacks.firewall.rule.edit_title') : t('stacks.firewall.rule.add_title')}
          </h2>
          <button onClick={onClose} aria-label={t('common.close')} className="btn-ghost">✕</button>
        </div>

        <form id="stack-fw-rule-form" onSubmit={handleSubmit} className="overflow-y-auto px-5 py-5 space-y-4 flex-1">
          {error && (
            <div className="text-sm text-portal-danger bg-portal-danger/10 border border-portal-danger/30 px-3 py-2 rounded">{error}</div>
          )}

          {/* Richtung + Aktion + enable */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className={labelCls} htmlFor="sfw-type">{t('stacks.firewall.rule.direction')} *</label>
              <select id="sfw-type" value={form.type} onChange={set('type')} className={inputCls}>
                <option value="in">{t('stacks.firewall.rule.dir_in')}</option>
                <option value="out">{t('stacks.firewall.rule.dir_out')}</option>
                {withGroup && <option value="group">{t('stacks.firewall.rule.dir_group')}</option>}
              </select>
            </div>
            <div>
              <label className={labelCls} htmlFor="sfw-action">{t('stacks.firewall.rule.action')} *</label>
              {form.type === 'group' ? (
                <ComboField
                  id="sfw-action"
                  value={form.group}
                  onChange={setVal('group')}
                  options={securityGroupNames}
                  placeholder={t('stacks.firewall.rule.group_ph')}
                  emptyLabel={t('stacks.firewall.rule.group_select')}
                  customLabel={customLabel}
                />
              ) : (
                <select id="sfw-action" value={form.action} onChange={set('action')} className={inputCls}>
                  <option value="ACCEPT">ACCEPT</option>
                  <option value="DROP">DROP</option>
                  <option value="REJECT">REJECT</option>
                </select>
              )}
            </div>
          </div>

          <label className="flex items-center gap-2 text-sm text-portal-text2 cursor-pointer">
            <input type="checkbox" checked={form.enable} onChange={set('enable')} className="accent-[var(--accent)]" />
            {t('stacks.firewall.rule.enabled')}
          </label>

          {/* Quelle / Ziel */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className={labelCls} htmlFor="sfw-source">{t('stacks.firewall.rule.source')}</label>
              <AddrField id="sfw-source" value={form.source} onChange={setVal('source')} refs={refs}
                placeholder="10.0.0.0/24" insertLabel={t('stacks.firewall.rule.insert_ref')} />
              <p className={smallCls}>{t('stacks.firewall.rule.addr_hint')}</p>
            </div>
            <div>
              <label className={labelCls} htmlFor="sfw-dest">{t('stacks.firewall.rule.dest')}</label>
              <AddrField id="sfw-dest" value={form.dest} onChange={setVal('dest')} refs={refs}
                placeholder="192.168.1.5" insertLabel={t('stacks.firewall.rule.insert_ref')} />
            </div>
          </div>

          {/* Protokoll: Macro XOR Proto/Ports (EC-4) – nicht bei group-Regeln */}
          {form.type !== 'group' && (
            <div className="rounded-lg border border-portal-border p-3 space-y-3">
              <div className="flex items-center gap-4 text-sm flex-wrap">
                <span className="text-xs font-medium text-portal-text3">{t('stacks.firewall.rule.proto_mode')}:</span>
                <label className="flex items-center gap-1.5 cursor-pointer">
                  <input type="radio" name="sfwProtoMode" value="custom" checked={form.protoMode === 'custom'} onChange={set('protoMode')} className="accent-[var(--accent)]" />
                  {t('stacks.firewall.rule.proto_custom')}
                </label>
                <label className="flex items-center gap-1.5 cursor-pointer">
                  <input type="radio" name="sfwProtoMode" value="macro" checked={form.protoMode === 'macro'} onChange={set('protoMode')} className="accent-[var(--accent)]" />
                  {t('stacks.firewall.rule.proto_macro')}
                </label>
              </div>

              {form.protoMode === 'macro' ? (
                <div>
                  <label className={labelCls} htmlFor="sfw-macro">Macro</label>
                  <ComboField
                    id="sfw-macro"
                    value={form.macro}
                    onChange={setVal('macro')}
                    options={macros.map((m) => m.macro)}
                    placeholder="HTTPS"
                    emptyLabel={t('stacks.firewall.rule.macro_select')}
                    customLabel={customLabel}
                  />
                  <p className={smallCls}>{t('stacks.firewall.rule.macro_hint')}</p>
                </div>
              ) : (
                <div className="grid grid-cols-3 gap-3">
                  <div>
                    <label className={labelCls} htmlFor="sfw-proto">{t('stacks.firewall.rule.proto')}</label>
                    <ComboField id="sfw-proto" value={form.proto} onChange={setVal('proto')} options={PROTO_OPTIONS} placeholder="tcp" emptyLabel={t('stacks.firewall.rule.proto_select')} customLabel={customLabel} />
                  </div>
                  {isIcmp ? (
                    <div className="col-span-2">
                      <label className={labelCls} htmlFor="sfw-icmp">{t('stacks.firewall.rule.icmp_type')}</label>
                      <ComboField id="sfw-icmp" value={form.icmp_type} onChange={setVal('icmp_type')} options={ICMP_TYPES} placeholder="echo-request" emptyLabel={t('stacks.firewall.rule.any')} customLabel={customLabel} />
                    </div>
                  ) : (
                    <>
                      <div>
                        <label className={labelCls} htmlFor="sfw-sport">{t('stacks.firewall.rule.sport')}</label>
                        <input id="sfw-sport" type="text" value={form.sport} onChange={set('sport')} placeholder="1024:65535" className={inputCls} />
                      </div>
                      <div>
                        <label className={labelCls} htmlFor="sfw-dport">{t('stacks.firewall.rule.dport')}</label>
                        <input id="sfw-dport" type="text" value={form.dport} onChange={set('dport')} placeholder="443" className={inputCls} />
                      </div>
                    </>
                  )}
                </div>
              )}
            </div>
          )}

          {/* iface (nicht bei group) + log */}
          <div className="grid grid-cols-2 gap-4">
            {form.type !== 'group' && (
              <div>
                <label className={labelCls} htmlFor="sfw-iface">{t('stacks.firewall.rule.iface')}</label>
                <input id="sfw-iface" type="text" value={form.iface} onChange={set('iface')} placeholder="net0" className={inputCls} />
              </div>
            )}
            <div className={form.type === 'group' ? 'col-span-2' : ''}>
              <label className={labelCls} htmlFor="sfw-log">{t('stacks.firewall.rule.log')}</label>
              <select id="sfw-log" value={form.log} onChange={set('log')} className={inputCls}>
                <option value="">{t('stacks.firewall.rule.no_log')}</option>
                {LOG_LEVELS.map((l) => <option key={l} value={l}>{l}</option>)}
              </select>
            </div>
          </div>

          {/* Kommentar */}
          <div>
            <label className={labelCls} htmlFor="sfw-comment">{t('stacks.firewall.rule.comment')}</label>
            <input id="sfw-comment" type="text" value={form.comment} onChange={set('comment')} className={inputCls} />
          </div>
        </form>

        <div className="px-5 py-3 border-t border-gray-100 dark:border-zinc-800 flex items-center justify-end gap-2 shrink-0">
          <button type="button" onClick={onClose} className="btn-secondary">{t('common.cancel')}</button>
          <button type="submit" form="stack-fw-rule-form" className="btn-primary">
            {isEdit ? t('common.save') : t('stacks.firewall.rule.add_btn')}
          </button>
        </div>
      </div>
    </div>
  )
}
