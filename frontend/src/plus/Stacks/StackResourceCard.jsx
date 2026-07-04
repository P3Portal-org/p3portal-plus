// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-76 Phase 1: Eine VM-Ressourcen-Karte im Formular-Editor (AC-UI-4).
// PROJ-82: + Sektion „Zusätzliche Festplatten" (Größe/Datastore/Bus → Interface).
// PROJ-86: + LXC-Container-Karte (discriminated union über `type`). Reine VM-
//   Karten bleiben unverändert; ein Dispatcher wählt VM- oder LXC-Body.
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNodeVmOptions, useImageStorages, useLxcTemplates } from './hooks'
import StackGuestFirewall from './StackGuestFirewall'

// PROJ-82: Bus-Grenzen (max Interface-Index, Muster Backend _BUS_MAX_INDEX). Der
// Root klont immer auf scsi0 → eine zusätzliche scsi-Disk beginnt bei scsi1.
const BUS_MAX_INDEX = { scsi: 30, virtio: 15, sata: 5 }
const BUS_MIN_INDEX = { scsi: 1, virtio: 0, sata: 0 } // scsi0 = Root → reserviert
const BUS_LIST = ['scsi', 'virtio', 'sata']
const IFACE_RE = /^(scsi|virtio|sata)(\d+)$/

function parseInterface(iface) {
  const m = IFACE_RE.exec(String(iface || ''))
  return m ? { bus: m[1], index: Number(m[2]) } : { bus: 'scsi', index: null }
}

/** Nächster freier Interface-Index eines Bus (belegte ausgenommen) oder null. */
function nextFreeIndex(bus, takenIndices) {
  const taken = new Set(takenIndices)
  for (let i = BUS_MIN_INDEX[bus]; i <= BUS_MAX_INDEX[bus]; i += 1) {
    if (!taken.has(i)) return i
  }
  return null
}

/**
 * Berechne ein stabiles Interface (`scsiN`/`virtioN`/`sataN`) für einen Bus,
 * unter Berücksichtigung der bereits vergebenen Interfaces. ``excludeIface``
 * lässt das eigene (zu ändernde) Interface aus der Belegung heraus.
 */
function computeInterface(bus, existingDisks, excludeIface) {
  const takenIdx = []
  for (const d of existingDisks) {
    if (excludeIface != null && d.interface === excludeIface) continue
    const p = parseInterface(d.interface)
    if (p.bus === bus && p.index != null) takenIdx.push(p.index)
  }
  const idx = nextFreeIndex(bus, takenIdx)
  // Bus voll → höchster+1 (Backend lehnt mit 422 ab; bewusst sichtbar machen).
  return `${bus}${idx == null ? BUS_MAX_INDEX[bus] + 1 : idx}`
}

// ── PROJ-86: Mountpoint-Index (`mpN`, stabiler Identitäts-Schlüssel, AC-MOUNT) ──
const MP_RE = /^mp(\d+)$/

function parseMpIndex(id) {
  const m = MP_RE.exec(String(id || ''))
  return m ? Number(m[1]) : null
}

/** Niedrigster freier mp-Index (Nutzer tippt keinen Index, AC-MOUNT-2). */
function nextFreeMpIndex(mounts) {
  const taken = new Set(mounts.map((x) => parseMpIndex(x.id)).filter((n) => n != null))
  let i = 0
  while (taken.has(i)) i += 1
  return i
}

// PROJ-87: das Bridge-Dropdown bietet zuerst die stack-deklarierten Netze (AC-MODEL-2),
// danach die bestehenden Node-Bridges und SDN-VNets (Referenz auf vorhandene/geteilte
// Netze). Ein VNet wird – wie eine Bridge – per Name referenziert (net0: bridge=<vnet>).
function mergeBridgeOptions(stackNetworks, nodeBridges, nodeVnets) {
  return [...new Set(
    [...(stackNetworks || []), ...(nodeBridges || []), ...(nodeVnets || [])].filter(Boolean)
  )]
}

// Pflichtfelder sind durch ein abschließendes „ *" im Label markiert. Sie
// bekommen eine design-passende Akzent-Umrandung (theme-Token, kein Roh-Farbwert)
// und einen hervorgehobenen Stern.
const REQUIRED_RING =
  ' [&_input]:border-portal-accent [&_select]:border-portal-accent [&_textarea]:border-portal-accent'

function Field({ label, children }) {
  const required = typeof label === 'string' && /\*\s*$/.test(label)
  const text = required ? label.replace(/\s*\*\s*$/, '') : label
  return (
    <label className={'flex flex-col gap-1 text-xs' + (required ? REQUIRED_RING : '')}>
      <span className="text-portal-text2 font-medium">
        {text}
        {required && <span className="text-portal-accent font-semibold"> *</span>}
      </span>
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
  // Optionen dürfen Strings ODER { value, label } sein (Template zeigt ID+Node
  // im Label, speichert aber weiter den Namen als Wert).
  const opts = (Array.isArray(options) ? options : []).map((o) =>
    o && typeof o === 'object'
      ? { value: String(o.value), label: String(o.label ?? o.value) }
      : { value: String(o), label: String(o) },
  )
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

  const showCurrentValueOpt = value != null && value !== '' && !opts.some((o) => o.value === value)
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
      {opts.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      <option value={MANUAL}>{customLabel}</option>
    </select>
  )
}

/** Gemeinsame Karten-Kopfzeile (Reorder/Duplizieren/Entfernen) für VM + LXC. */
function CardHeader({ index, total, name, titleLabel, badge, onMove, onDuplicate, onRemove }) {
  const { t } = useTranslation()
  return (
    <div className="flex items-center justify-between gap-2">
      <h4 className="text-sm font-semibold text-gray-900 dark:text-zinc-100 flex items-center gap-2 min-w-0">
        <span className="text-portal-text3">#{index + 1}</span>
        <span className="shrink-0">{titleLabel}</span>
        {badge}
        {name ? <span className="text-portal-text2 font-normal truncate">— {name}</span> : null}
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
  )
}

// ── PROJ-91: collapsible Gast-Firewall-Block (VM + LXC) ───────────────────────
// Ein Badge zeigt an, ob die Firewall aktiv/definiert ist; eingeklappt by default,
// damit die Karte schlank bleibt. Reuse von StackGuestFirewall (Regel-Editor).
function GuestFirewallBlock({ t, firewall, onChange, refs, macros, securityGroupNames }) {
  const fw = firewall || {}
  const ruleCount = Array.isArray(fw.rules) ? fw.rules.length : 0
  const configured = fw.enabled || fw.policy_in || fw.policy_out || ruleCount > 0
  // Eingeklappt, außer es ist bereits etwas konfiguriert (dann offen, damit der
  // Nutzer den Zustand sieht).
  const [open, setOpen] = useState(configured)
  return (
    <div className="border-t border-portal-border/60 pt-2 space-y-2">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2 text-xs text-portal-text2 font-medium w-full"
      >
        <span className="text-portal-text3">{open ? '▾' : '▸'}</span>
        <span>{t('stacks.firewall.section')}</span>
        {configured && (
          <span className="text-[10px] px-1.5 py-0.5 rounded border border-portal-accent/40 text-portal-accent">
            {fw.enabled ? t('stacks.firewall.badge_active') : t('stacks.firewall.badge_inert')}
            {ruleCount > 0 ? ` · ${ruleCount}` : ''}
          </span>
        )}
      </button>
      {open && (
        <StackGuestFirewall
          t={t}
          firewall={firewall}
          onChange={onChange}
          refs={refs}
          macros={macros}
          securityGroupNames={securityGroupNames}
        />
      )}
    </div>
  )
}

// ── VM-Karte (PROJ-76/82, unverändert) ────────────────────────────────────────
function VmCard({ resource, index, total, onChange, onRemove, onMove, onDuplicate, nodeOptions, templateOptions, stackNetworks = [], fwRefs = [], fwMacros = [], securityGroupNames = [] }) {
  const { t } = useTranslation()
  const r = resource

  const set = (key, val) => onChange(index, { ...r, [key]: val })
  const setNet = (key, val) => onChange(index, { ...r, network: { ...(r.network || {}), [key]: val } })
  const num = (v) => (v === '' || v == null ? '' : Number(v))

  // Node-abhängige Optionen (Bridges / CPU-Typen / vorhandene Tags) aus Proxmox.
  const { data: nodeOpts } = useNodeVmOptions(r.node)

  // PROJ-82: image-fähige Datastores des Node (Dropdown der Zusatz-Disks).
  const { data: imageStorages } = useImageStorages(r.node)
  const datastoreNames = Array.isArray(imageStorages)
    ? [...new Set(imageStorages.map((s) => s.name || s.storage).filter(Boolean))]
    : []

  // ── Zusätzliche Festplatten (PROJ-82) ──────────────────────────────────────
  const extraDisks = Array.isArray(r.extra_disks) ? r.extra_disks : []
  const setDisks = (next) => set('extra_disks', next)

  const addDisk = () => {
    const iface = computeInterface('scsi', extraDisks, null)
    setDisks([...extraDisks, { interface: iface, size: 32, datastore: '' }])
  }
  const removeDisk = (di) => setDisks(extraDisks.filter((_, i) => i !== di))
  const setDiskField = (di, key, val) =>
    setDisks(extraDisks.map((d, i) => (i === di ? { ...d, [key]: val } : d)))
  // Bus wechseln → neues stabiles Interface (nächster freier Index des Bus).
  const changeDiskBus = (di, bus) => {
    const cur = extraDisks[di]
    const iface = computeInterface(bus, extraDisks, cur.interface)
    setDisks(extraDisks.map((d, i) => (i === di ? { ...d, interface: iface } : d)))
  }

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

  // Template-Auswahl: NUR Vorlagen der gewählten Node (kein Fallback auf alle —
  // sonst wählt man eine Kopie, die physisch auf einer anderen Node liegt → beim
  // Deploy Proxmox-500 "unable to find configuration file for VM <id>"). Label zeigt
  // Name (ID vmid · Node); gespeichert wird weiter der Name (portabler Stack).
  // Manuelle Eingabe bleibt über ComboField möglich.
  const tplRows = Array.isArray(templateOptions) ? templateOptions : []
  const seenTpl = new Set()
  const templateChoices = []
  for (const tpl of tplRows) {
    if (!r.node || tpl.node !== r.node) continue
    const nm = String(tpl.name || tpl.template || '')
    if (!nm || seenTpl.has(nm)) continue
    seenTpl.add(nm)
    templateChoices.push({
      value: nm,
      label: tpl.vmid != null ? `${nm} (ID ${tpl.vmid}${tpl.node ? ` · ${tpl.node}` : ''})` : nm,
    })
  }
  // Warnung: aktuell gewähltes Template liegt nicht auf der gewählten Node.
  const templateMissingOnNode = !!r.node && !!r.template && !seenTpl.has(String(r.template))

  return (
    <div className="border border-gray-200 dark:border-zinc-700 rounded-lg bg-white dark:bg-zinc-900 p-4 space-y-3" draggable={false}>
      <CardHeader
        index={index}
        total={total}
        name={r.name}
        titleLabel={t('stacks.form.vm_card.title')}
        onMove={onMove}
        onDuplicate={onDuplicate}
        onRemove={onRemove}
      />

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
            options={templateChoices}
            placeholder={t('stacks.form.select_ph')}
            customLabel={t('stacks.form.custom_value')}
          />
          {templateMissingOnNode && (
            <span className="text-[10px] text-portal-warn">
              {t('stacks.form.template_not_on_node', { node: r.node })}
            </span>
          )}
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
            options={mergeBridgeOptions(stackNetworks, nodeOpts?.bridges, nodeOpts?.vnets)}
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
              checked={r.agent !== false}
              onChange={(e) => set('agent', e.target.checked)}
              className="accent-[var(--accent)]"
            />
            {t('stacks.form.field.agent')}
          </span>
          <span className="text-[10px] text-portal-text3 ml-6">{t('stacks.form.agent_hint')}</span>
        </label>
      </div>

      {/* PROJ-82: Zusätzliche Festplatten */}
      <div className="space-y-2 pt-1">
        <div className="flex items-center justify-between">
          <span className="text-xs text-portal-text2 font-medium">
            {t('stacks.form.extra_disks.title')}
            {extraDisks.length > 0 ? ` (${extraDisks.length})` : ''}
          </span>
          <button type="button" onClick={addDisk} className="btn-table" title={t('stacks.form.extra_disks.add')}>
            + {t('stacks.form.extra_disks.add')}
          </button>
        </div>
        <p className="text-[10px] text-portal-text3">{t('stacks.form.extra_disks.hint')}</p>

        {extraDisks.length === 0 ? (
          <p className="text-[11px] text-portal-text3 italic">{t('stacks.form.extra_disks.empty')}</p>
        ) : (
          <div className="space-y-2">
            {extraDisks.map((d, di) => {
              const bus = parseInterface(d.interface).bus
              return (
                <div key={di} className="grid grid-cols-2 md:grid-cols-4 gap-2 items-end border border-portal-border rounded-md p-2 bg-portal-bg2">
                  <Field label={t('stacks.form.extra_disks.size')}>
                    <input
                      type="number"
                      min={1}
                      max={16384}
                      className={inputCls}
                      value={d.size ?? ''}
                      onChange={(e) => setDiskField(di, 'size', num(e.target.value))}
                    />
                  </Field>
                  <Field label={t('stacks.form.extra_disks.datastore')}>
                    <ComboField
                      value={d.datastore ?? ''}
                      onChange={(v) => setDiskField(di, 'datastore', v)}
                      options={datastoreNames}
                      placeholder={t('stacks.form.select_ph')}
                      customLabel={t('stacks.form.custom_value')}
                    />
                  </Field>
                  <Field label={t('stacks.form.extra_disks.bus')}>
                    <select
                      className={inputCls}
                      value={bus}
                      onChange={(e) => changeDiskBus(di, e.target.value)}
                    >
                      {BUS_LIST.map((b) => <option key={b} value={b}>{b}</option>)}
                    </select>
                    <span className="text-[10px] text-portal-text3 font-mono">{d.interface}</span>
                  </Field>
                  <button
                    type="button"
                    onClick={() => removeDisk(di)}
                    className="btn-table-danger justify-self-start"
                    aria-label={t('stacks.form.extra_disks.remove')}
                  >{t('common.remove')}</button>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* PROJ-91: Gast-Firewall */}
      <GuestFirewallBlock
        t={t}
        firewall={r.firewall}
        onChange={(val) => set('firewall', val)}
        refs={fwRefs}
        macros={fwMacros}
        securityGroupNames={securityGroupNames}
      />
    </div>
  )
}

// ── PROJ-86: LXC-Container-Karte ──────────────────────────────────────────────
function LxcCard({ resource, index, total, onChange, onRemove, onMove, onDuplicate, nodeOptions, stackNetworks = [], fwRefs = [], fwMacros = [], securityGroupNames = [] }) {
  const { t } = useTranslation()
  const r = resource

  const set = (key, val) => onChange(index, { ...r, [key]: val })
  const setNet = (key, val) => onChange(index, { ...r, network: { ...(r.network || {}), [key]: val } })
  const num = (v) => (v === '' || v == null ? '' : Number(v))

  const { data: nodeOpts } = useNodeVmOptions(r.node)
  const { data: imageStorages } = useImageStorages(r.node)
  const datastoreNames = Array.isArray(imageStorages)
    ? [...new Set(imageStorages.map((s) => s.name || s.storage).filter(Boolean))]
    : []

  // Node-Namen
  const nodeNames = [...new Set((nodeOptions || []).filter(Boolean))]

  // LXC-Template-File-IDs (`volid`), node-abhängig gefiltert. Fallback: alle
  // installierten, wenn der Node keine Treffer hat oder noch keiner gewählt ist.
  const { data: lxcTpl } = useLxcTemplates()
  const installed = Array.isArray(lxcTpl?.installed) ? lxcTpl.installed : []
  const tplNodeOf = (it) => it.portal_node_name ?? it.node
  let tplIds = installed
    .filter((it) => !r.node || tplNodeOf(it) === r.node)
    .map((it) => it.volid)
    .filter(Boolean)
  if (tplIds.length === 0) {
    tplIds = installed.map((it) => it.volid).filter(Boolean)
  }
  tplIds = [...new Set(tplIds.map(String))]

  // Node-Kapazität (weiche Hinweise)
  const maxcpu = typeof nodeOpts?.maxcpu === 'number' ? nodeOpts.maxcpu : null
  const maxmemMB = typeof nodeOpts?.maxmem === 'number' ? Math.floor(nodeOpts.maxmem / 1048576) : null
  const coresOver = maxcpu != null && Number(r.cores ?? 1) > maxcpu
  const memOver = maxmemMB != null && Number(r.memory ?? 512) > maxmemMB

  // Tags
  const currentTags = Array.isArray(r.tags)
    ? r.tags
    : (r.tags ? String(r.tags).split(',').map((s) => s.trim()).filter(Boolean) : [])
  const tagsStr = currentTags.join(', ')
  const addTag = (tg) => { if (!currentTags.includes(tg)) set('tags', [...currentTags, tg]) }
  const availableTags = Array.isArray(nodeOpts?.tags)
    ? nodeOpts.tags.filter((tg) => !currentTags.includes(tg))
    : []

  // ── Features (alle aus → kein features-Block) ──────────────────────────────
  const feat = r.features || {}
  const setFeat = (key, val) => {
    const next = { ...feat, [key]: val }
    // Leere Werte / alles-aus → features-Block entfernen (Default).
    const active = next.nesting || next.keyctl || next.fuse || (next.mount && next.mount.length)
    set('features', active ? next : undefined)
  }
  const privileged = r.unprivileged === false

  // ── Mountpoints (PROJ-86, Pendant zu PROJ-82-Disks) ────────────────────────
  const mounts = Array.isArray(r.mounts) ? r.mounts : []
  const setMounts = (next) => set('mounts', next)
  const addMount = () => {
    const id = `mp${nextFreeMpIndex(mounts)}`
    setMounts([...mounts, { id, size: 8, datastore: '', path: '/data', backup: false }])
  }
  const removeMount = (mi) => setMounts(mounts.filter((_, i) => i !== mi))
  const setMountField = (mi, key, val) =>
    setMounts(mounts.map((m, i) => (i === mi ? { ...m, [key]: val } : m)))

  return (
    <div className="border border-gray-200 dark:border-zinc-700 rounded-lg bg-white dark:bg-zinc-900 p-4 space-y-3" draggable={false}>
      <CardHeader
        index={index}
        total={total}
        name={r.name}
        titleLabel={t('stacks.form.lxc_card.title')}
        badge={<span className="text-[10px] px-1.5 py-0.5 rounded border border-portal-border text-portal-text2">LXC</span>}
        onMove={onMove}
        onDuplicate={onDuplicate}
        onRemove={onRemove}
      />

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
        <Field label={t('stacks.form.field.hostname') + ' *'}>
          <input className={inputCls} value={r.hostname ?? ''} placeholder="container-01" onChange={(e) => set('hostname', e.target.value)} />
        </Field>

        <Field label={t('stacks.form.field.template') + ' *'}>
          <ComboField
            value={r.template ?? ''}
            onChange={(v) => set('template', v)}
            options={tplIds}
            placeholder={t('stacks.form.lxc_template_ph')}
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

        <Field label={t('stacks.form.field.memory')}>
          <input type="number" min={16} max={1048576} className={inputCls} value={r.memory ?? 512} onChange={(e) => set('memory', num(e.target.value))} />
          {maxmemMB != null && memOver && <span className="text-[10px] text-portal-warn">⚠</span>}
        </Field>
        <Field label={t('stacks.form.field.swap')}>
          <input type="number" min={0} max={1048576} className={inputCls} value={r.swap ?? 512} onChange={(e) => set('swap', num(e.target.value))} />
        </Field>
        <Field label={t('stacks.form.field.rootfs_size')}>
          <input type="number" min={1} max={16384} className={inputCls} value={r.rootfs_size ?? 8} onChange={(e) => set('rootfs_size', num(e.target.value))} />
        </Field>

        <Field label={t('stacks.form.field.rootfs_datastore')}>
          <ComboField
            value={r.rootfs_datastore ?? ''}
            onChange={(v) => set('rootfs_datastore', v)}
            options={datastoreNames}
            placeholder={t('stacks.form.select_ph')}
            customLabel={t('stacks.form.custom_value')}
          />
        </Field>
        <Field label={t('stacks.form.field.bridge')}>
          <ComboField
            value={r.network?.bridge ?? ''}
            onChange={(v) => setNet('bridge', v)}
            options={mergeBridgeOptions(stackNetworks, nodeOpts?.bridges, nodeOpts?.vnets)}
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
      </div>

      {/* Sicherheit: unprivileged (Default) vs. privileged (Warnung, AC-SEC) */}
      <div className="space-y-1 pt-1">
        <label className="flex items-center gap-2 text-xs text-portal-text2">
          <input
            type="checkbox"
            checked={r.unprivileged !== false}
            onChange={(e) => set('unprivileged', e.target.checked)}
            className="accent-[var(--accent)]"
          />
          {t('stacks.form.field.unprivileged')}
        </label>
        {privileged && (
          <p className="text-[11px] text-portal-warn">⚠ {t('stacks.form.privileged_warn')}</p>
        )}
      </div>

      {/* Container-Features (alle aus → kein features-Block) */}
      <div className="space-y-2 pt-1">
        <span className="text-xs text-portal-text2 font-medium">{t('stacks.form.features.title')}</span>
        <div className="flex flex-wrap gap-4">
          {['nesting', 'keyctl', 'fuse'].map((f) => (
            <label key={f} className="flex items-center gap-1.5 text-xs text-portal-text2">
              <input
                type="checkbox"
                checked={feat[f] === true}
                onChange={(e) => setFeat(f, e.target.checked)}
                className="accent-[var(--accent)]"
              />
              {t(`stacks.form.features.${f}`)}
            </label>
          ))}
        </div>
        <Field label={t('stacks.form.features.mount')}>
          <input
            className={inputCls}
            value={feat.mount ?? ''}
            placeholder="nfs;cifs"
            onChange={(e) => setFeat('mount', e.target.value || undefined)}
          />
          <span className="text-[10px] text-portal-text3">{t('stacks.form.features.mount_hint')}</span>
        </Field>
      </div>

      {/* Mountpoints (Pendant zu PROJ-82-Disks) */}
      <div className="space-y-2 pt-1">
        <div className="flex items-center justify-between">
          <span className="text-xs text-portal-text2 font-medium">
            {t('stacks.form.mounts.title')}
            {mounts.length > 0 ? ` (${mounts.length})` : ''}
          </span>
          <button type="button" onClick={addMount} className="btn-table" title={t('stacks.form.mounts.add')}>
            + {t('stacks.form.mounts.add')}
          </button>
        </div>
        <p className="text-[10px] text-portal-text3">{t('stacks.form.mounts.hint')}</p>

        {mounts.length === 0 ? (
          <p className="text-[11px] text-portal-text3 italic">{t('stacks.form.mounts.empty')}</p>
        ) : (
          <div className="space-y-2">
            {mounts.map((m, mi) => (
              <div key={mi} className="grid grid-cols-2 md:grid-cols-5 gap-2 items-end border border-portal-border rounded-md p-2 bg-portal-bg2">
                <Field label={t('stacks.form.mounts.size')}>
                  <input
                    type="number"
                    min={1}
                    max={16384}
                    className={inputCls}
                    value={m.size ?? ''}
                    onChange={(e) => setMountField(mi, 'size', num(e.target.value))}
                  />
                </Field>
                <Field label={t('stacks.form.mounts.datastore')}>
                  <ComboField
                    value={m.datastore ?? ''}
                    onChange={(v) => setMountField(mi, 'datastore', v)}
                    options={datastoreNames}
                    placeholder={t('stacks.form.select_ph')}
                    customLabel={t('stacks.form.custom_value')}
                  />
                </Field>
                <Field label={t('stacks.form.mounts.path')}>
                  <input
                    className={inputCls}
                    value={m.path ?? ''}
                    placeholder="/data"
                    onChange={(e) => setMountField(mi, 'path', e.target.value)}
                  />
                  <span className="text-[10px] text-portal-text3 font-mono">{m.id}</span>
                </Field>
                <label className="flex items-center gap-1.5 text-xs text-portal-text2 mt-5">
                  <input
                    type="checkbox"
                    checked={m.backup === true}
                    onChange={(e) => setMountField(mi, 'backup', e.target.checked)}
                    className="accent-[var(--accent)]"
                  />
                  {t('stacks.form.mounts.backup')}
                </label>
                <button
                  type="button"
                  onClick={() => removeMount(mi)}
                  className="btn-table-danger justify-self-start"
                  aria-label={t('stacks.form.mounts.remove')}
                >{t('common.remove')}</button>
              </div>
            ))}
          </div>
        )}
      </div>

      <label className="flex items-center gap-2 text-xs text-portal-text2">
        <input
          type="checkbox"
          checked={r.start_after_create !== false}
          onChange={(e) => set('start_after_create', e.target.checked)}
          className="accent-[var(--accent)]"
        />
        {t('stacks.form.field.start_after_create')}
      </label>

      {/* PROJ-91: Gast-Firewall */}
      <GuestFirewallBlock
        t={t}
        firewall={r.firewall}
        onChange={(val) => set('firewall', val)}
        refs={fwRefs}
        macros={fwMacros}
        securityGroupNames={securityGroupNames}
      />
    </div>
  )
}

/**
 * Dispatcher: wählt anhand `resource.type` die VM- oder LXC-Karte. Reine VM-
 * Resourcen rendern byte-identisch zu PROJ-76/82 (AC-RES-1, kein Regression).
 */
export default function StackResourceCard(props) {
  if (props.resource?.type === 'lxc') return <LxcCard {...props} />
  return <VmCard {...props} />
}
