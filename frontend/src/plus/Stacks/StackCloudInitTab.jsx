// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-85: Cloud-Init-Tab im Stack-Editor (AC-UI-1/4, AC-KEY-1/2, AC-IP).
// Setzt Login (username/Passwort/SSH-Keys) + IP (DHCP/statisch) als Stack-Default
// mit Per-VM-Override. Liegt im eigenen verschlüsselten Store (NICHT im YAML),
// daher eigener Speichern-Button (kein Versions-/ETag-/Approval-Bezug, AC-STORE-3).
import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { getSshJobKeyStatus } from '../../api/profile'
import { formatApiError } from '../../api/errors'
import { useCapability } from '../../hooks/useCapability'
import { availablePools, suggestFreeIp } from '../../api/ipam'
import { useStackCloudInit, usePutStackCloudInit } from './hooks'

const inputCls =
  'w-full px-2 py-1.5 text-sm rounded-md border border-portal-border bg-portal-bg2 text-portal-text focus:outline-none focus:ring-1 focus:ring-portal-accent'

// ── Block model (UI state) ───────────────────────────────────────────────────

function blockFromOut(out, vmName) {
  return {
    vm_name: out?.vm_name ?? vmName ?? '',
    enabled: !!out?.enabled,
    username: out?.username || '',
    password: '',                       // write-only: leer = unverändert (EC-6)
    password_set: !!out?.password_set,
    ssh_keys: Array.isArray(out?.ssh_keys) ? out.ssh_keys : [],
    ip_mode: out?.ip_mode || '',        // '' = kein ip_config (Template/cloud-init-Default)
    ip_address_cidr: out?.ip_address_cidr || '',
    ip_gateway: out?.ip_gateway || '',
    dns_servers: out?.dns_servers || '',
    dns_domain: out?.dns_domain || '',
    orphan: !!out?.orphan,
  }
}

function emptyBlock(vmName) {
  return blockFromOut({ enabled: true }, vmName)
}

// PUT-Block: Passwort nur senden wenn getippt (write-only-Merge, EC-6).
function toReqBlock(b) {
  const out = {
    vm_name: b.vm_name,
    enabled: b.enabled,
    username: b.username || null,
    ssh_keys: b.ssh_keys || [],
    ip_mode: b.ip_mode || null,
    ip_address_cidr: b.ip_address_cidr || null,
    ip_gateway: b.ip_gateway || null,
    dns_servers: b.dns_servers || null,
    dns_domain: b.dns_domain || null,
  }
  if (b.password) out.password = b.password
  return out
}

// 422-Detail des Backends ist {errors:[...]}; sonst Standard-Normalisierung.
function ciError(err, fallback) {
  const d = err?.response?.data?.detail
  if (d && Array.isArray(d.errors)) return d.errors.join('; ')
  return formatApiError(err, fallback)
}

// ── Free-IP-Vorschlag (PROJ-42 Phase 2, Plus) ────────────────────────────────
// Entkoppelt vom NIC-Netz (pragmatisch, konsistent mit dem Playbook-Deploy-Feld):
// Pool wählen → „Freie IP vorschlagen" füllt CIDR + Gateway. Gated ipam_plus.
function FreeIpPicker({ onFill }) {
  const { t } = useTranslation()
  const hasIpamPlus = useCapability('ipam_plus')
  const poolsQuery = useQuery({
    queryKey: ['ipam', 'available-pools'],
    queryFn: availablePools,
    enabled: hasIpamPlus,
    staleTime: 30_000,
  })
  const [poolId, setPoolId] = useState('')
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')

  const pools = poolsQuery.data || []
  if (!hasIpamPlus || pools.length === 0) return null

  const suggest = async () => {
    setNote('')
    const pool = pools.find((p) => p.id === Number(poolId))
    if (!pool) return
    setBusy(true)
    try {
      const res = await suggestFreeIp(pool.id)
      if (!res?.ip) { setNote(t('ipam.deploy.exhausted')); return }
      const prefix = (pool.cidr || '').split('/')[1] || '24'
      onFill({ ip_address_cidr: `${res.ip}/${prefix}`, ip_gateway: pool.gateway || '' })
    } catch {
      setNote(t('ipam.deploy.error'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="md:col-span-2 flex flex-wrap items-center gap-2 rounded-md border border-portal-accent/30 bg-portal-accent/5 p-2">
      <span className="text-[11px] text-portal-text2">{t('ipam.deploy.pool_label')}</span>
      <select
        value={poolId}
        onChange={(e) => setPoolId(e.target.value)}
        className="h-7 rounded-md border border-portal-border bg-portal-bg2 px-2 text-xs text-portal-text min-w-[12rem]"
      >
        <option value="">{t('ipam.deploy.pool_select')}</option>
        {pools.map((p) => (
          <option key={p.id} value={p.id}>{p.network_name} · {p.cidr}</option>
        ))}
      </select>
      <button type="button" onClick={suggest} disabled={!poolId || busy} className="btn-table">
        {busy ? '…' : t('ipam.deploy.suggest_btn')}
      </button>
      {note && <span className="text-[11px] text-portal-warn">{note}</span>}
    </div>
  )
}

// ── Shared field group (Default + Override) ──────────────────────────────────

function CloudInitBlockFields({ block, onPatch, profileKey, idPrefix, isLxc = false }) {
  const { t } = useTranslation()
  const set = (k, v) => onPatch({ [k]: v })

  const keysText = (block.ssh_keys || []).join('\n')
  const setKeysText = (text) =>
    set('ssh_keys', text.split('\n').map((s) => s.trim()).filter(Boolean))

  const addProfileKey = () => {
    const pk = profileKey?.public_key
    if (!pk) return
    if ((block.ssh_keys || []).includes(pk)) return
    set('ssh_keys', [...(block.ssh_keys || []), pk])
  }
  const hasProfileKey = !!profileKey?.has_key && !!profileKey?.public_key

  return (
    <div className="space-y-3 mt-3">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {isLxc ? (
          // PROJ-86: LXC-Login ist immer root — kein username-Feld (AC-GUEST-5).
          <div className="flex flex-col gap-1 text-xs">
            <span className="text-portal-text2 font-medium">{t('stacks.cloudinit.login')}</span>
            <span className="px-2 py-1.5 text-sm rounded-md border border-portal-border bg-portal-bg2 text-portal-text2 font-mono">root</span>
          </div>
        ) : (
          <label className="flex flex-col gap-1 text-xs [&_input]:border-portal-accent">
            <span className="text-portal-text2 font-medium">{t('stacks.cloudinit.username')} <span className="text-portal-accent font-semibold">*</span></span>
            <input
              id={`${idPrefix}-user`}
              className={inputCls}
              value={block.username}
              autoComplete="off"
              onChange={(e) => set('username', e.target.value)}
            />
          </label>
        )}
        <label className="flex flex-col gap-1 text-xs">
          <span className="text-portal-text2 font-medium">{t('stacks.cloudinit.password')}</span>
          <input
            id={`${idPrefix}-pw`}
            type="password"
            className={inputCls}
            value={block.password}
            autoComplete="new-password"
            placeholder={block.password_set ? t('stacks.cloudinit.password_set_ph') : t('stacks.cloudinit.password_ph')}
            onChange={(e) => set('password', e.target.value)}
          />
        </label>
      </div>

      <div className="flex flex-col gap-1 text-xs">
        <div className="flex items-center justify-between">
          <span className="text-portal-text2 font-medium">{t('stacks.cloudinit.ssh_keys')}</span>
          <button
            type="button"
            className="btn-table disabled:opacity-40"
            disabled={!hasProfileKey}
            title={hasProfileKey ? t('stacks.cloudinit.profile_key_add') : t('stacks.cloudinit.profile_key_missing')}
            onClick={addProfileKey}
          >{t('stacks.cloudinit.profile_key_add')}</button>
        </div>
        <textarea
          id={`${idPrefix}-keys`}
          rows={3}
          className={`${inputCls} font-mono`}
          value={keysText}
          placeholder={t('stacks.cloudinit.ssh_keys_ph')}
          onChange={(e) => setKeysText(e.target.value)}
        />
        <span className="text-[10px] text-portal-text3">{t('stacks.cloudinit.ssh_keys_hint')}</span>
      </div>

      {/* IP-Modus */}
      <div className="flex flex-col gap-1 text-xs">
        <span className="text-portal-text2 font-medium">{t('stacks.cloudinit.ip_mode')}</span>
        <div className="flex flex-wrap gap-3">
          {['', 'dhcp', 'static'].map((m) => (
            <label key={m || 'none'} className="flex items-center gap-1.5 text-portal-text2">
              <input
                type="radio"
                name={`${idPrefix}-ipmode`}
                checked={block.ip_mode === m}
                onChange={() => set('ip_mode', m)}
                className="accent-[var(--accent)]"
              />
              {t(`stacks.cloudinit.ip_mode_${m || 'none'}`)}
            </label>
          ))}
        </div>
      </div>

      {block.ip_mode === 'static' && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <FreeIpPicker onFill={(patch) => onPatch(patch)} />
          <label className="flex flex-col gap-1 text-xs [&_input]:border-portal-accent">
            <span className="text-portal-text2 font-medium">{t('stacks.cloudinit.ip_cidr')} <span className="text-portal-accent font-semibold">*</span></span>
            <input
              className={inputCls}
              value={block.ip_address_cidr}
              placeholder="10.0.0.5/24"
              onChange={(e) => set('ip_address_cidr', e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 text-xs [&_input]:border-portal-accent">
            <span className="text-portal-text2 font-medium">{t('stacks.cloudinit.ip_gateway')} <span className="text-portal-accent font-semibold">*</span></span>
            <input
              className={inputCls}
              value={block.ip_gateway}
              placeholder="10.0.0.1"
              onChange={(e) => set('ip_gateway', e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-portal-text2 font-medium">{t('stacks.cloudinit.dns_servers')}</span>
            <input
              className={inputCls}
              value={block.dns_servers}
              placeholder="1.1.1.1 8.8.8.8"
              onChange={(e) => set('dns_servers', e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-portal-text2 font-medium">{t('stacks.cloudinit.dns_domain')}</span>
            <input
              className={inputCls}
              value={block.dns_domain}
              placeholder="example.com"
              onChange={(e) => set('dns_domain', e.target.value)}
            />
          </label>
          <p className="md:col-span-2 text-[10px] text-portal-text3">{t('stacks.cloudinit.static_count_hint')}</p>
        </div>
      )}
    </div>
  )
}

// ── Main tab ──────────────────────────────────────────────────────────────────

export default function StackCloudInitTab({ stackId, resources = null, resourceNames = [] }) {
  const { t } = useTranslation()
  const { data, isLoading } = useStackCloudInit(stackId)
  const putMut = usePutStackCloudInit()

  // PROJ-86: `resources` ([{name,type}]) trägt den Typ → LXC-Overrides zeigen
  // „Login: root" statt username (AC-GUEST-5). Fallback auf `resourceNames`
  // (alles VM) für Rückwärtskompatibilität.
  const resList = Array.isArray(resources)
    ? resources.filter((r) => r?.name)
    : (resourceNames || []).map((name) => ({ name, type: 'vm' }))
  const resourceNameList = resList.map((r) => r.name)
  const isLxcName = (name) => resList.find((r) => r.name === name)?.type === 'lxc'

  const [defaultBlock, setDefaultBlock] = useState(() => emptyBlock(''))
  // Map vm_name → block (nur Resources mit Override = custom/suppress + Orphans).
  const [overrides, setOverrides] = useState(() => new Map())
  const [saveError, setSaveError] = useState(null)
  const [saveOk, setSaveOk] = useState(false)
  const seeded = useRef(false)

  // Eigener Profil-SSH-Key (PROJ-14) für „Profil-Key übernehmen" (AC-KEY-1).
  const { data: profileKey } = useQuery({
    queryKey: ['ssh-job-key'],
    queryFn: getSshJobKeyStatus,
    staleTime: 5 * 60_000,
    retry: false,
  })

  const seedFrom = (d) => {
    setDefaultBlock(blockFromOut(d?.default, ''))
    const m = new Map()
    for (const o of d?.overrides || []) m.set(o.vm_name, blockFromOut(o, o.vm_name))
    setOverrides(m)
  }

  // Einmaliges Seeding (kein Clobbern laufender Edits bei Background-Refetch).
  useEffect(() => {
    if (data && !seeded.current) {
      seedFrom(data)
      seeded.current = true
    }
  }, [data])

  if (!stackId) {
    return (
      <div className="bg-white dark:bg-zinc-900 rounded-lg border border-gray-200 dark:border-zinc-700 p-6">
        <p className="text-sm text-portal-text2">{t('stacks.cloudinit.save_stack_first')}</p>
      </div>
    )
  }
  if (isLoading) {
    return <p className="text-sm text-portal-text2 px-1">{t('common.loading')}</p>
  }

  const patchDefault = (patch) => { setSaveOk(false); setDefaultBlock((b) => ({ ...b, ...patch })) }

  const modeOf = (name) => {
    const b = overrides.get(name)
    if (!b) return 'default'
    return b.enabled ? 'custom' : 'suppress'
  }
  const setMode = (name, mode) => {
    setSaveOk(false)
    setOverrides((prev) => {
      const next = new Map(prev)
      if (mode === 'default') {
        next.delete(name)
      } else if (mode === 'custom') {
        const existing = prev.get(name)
        next.set(name, { ...(existing || emptyBlock(name)), enabled: true })
      } else { // suppress
        const existing = prev.get(name)
        next.set(name, { ...(existing || emptyBlock(name)), enabled: false })
      }
      return next
    })
  }
  const patchOverride = (name, patch) => {
    setSaveOk(false)
    setOverrides((prev) => {
      const next = new Map(prev)
      const existing = prev.get(name) || emptyBlock(name)
      next.set(name, { ...existing, ...patch })
      return next
    })
  }
  const deleteOrphan = (name) => {
    setSaveOk(false)
    setOverrides((prev) => {
      const next = new Map(prev)
      next.delete(name)
      return next
    })
  }

  const orphanNames = [...overrides.keys()].filter((n) => !resourceNameList.includes(n))

  const onSave = async () => {
    setSaveError(null)
    setSaveOk(false)
    const body = {
      default: toReqBlock(defaultBlock),
      overrides: [...overrides.values()].map(toReqBlock),
    }
    try {
      const fresh = await putMut.mutateAsync({ id: stackId, body })
      seedFrom(fresh)   // Passwort-Felder leeren, password_set aktualisieren
      setSaveOk(true)
    } catch (err) {
      setSaveError(ciError(err, t('common.error_generic')))
    }
  }

  return (
    <div className="space-y-4">
      <p className="text-xs text-portal-text3">{t('stacks.cloudinit.intro')}</p>

      {/* Stack-Default */}
      <div className="bg-white dark:bg-zinc-900 rounded-lg border border-gray-200 dark:border-zinc-700 p-4">
        <label className="flex items-center gap-2 text-sm font-medium text-gray-900 dark:text-zinc-100">
          <input
            type="checkbox"
            checked={defaultBlock.enabled}
            onChange={(e) => patchDefault({ enabled: e.target.checked })}
            className="accent-[var(--accent)]"
          />
          {t('stacks.cloudinit.default_enable')}
        </label>
        <p className="text-[11px] text-portal-text3 mt-1">{t('stacks.cloudinit.default_hint')}</p>
        {defaultBlock.enabled && (
          <CloudInitBlockFields
            block={defaultBlock}
            onPatch={patchDefault}
            profileKey={profileKey}
            idPrefix="ci-default"
          />
        )}
      </div>

      {/* Per-VM-Overrides */}
      <div className="bg-white dark:bg-zinc-900 rounded-lg border border-gray-200 dark:border-zinc-700 p-4 space-y-3">
        <div>
          <h4 className="text-sm font-semibold text-gray-900 dark:text-zinc-100">{t('stacks.cloudinit.overrides_title')}</h4>
          <p className="text-[11px] text-portal-text3 mt-1">{t('stacks.cloudinit.overrides_hint')}</p>
        </div>

        {resourceNameList.length === 0 ? (
          <p className="text-[11px] text-portal-text3 italic">{t('stacks.cloudinit.no_resources')}</p>
        ) : (
          resourceNameList.map((name) => {
            const mode = modeOf(name)
            const block = overrides.get(name)
            const lxc = isLxcName(name)
            return (
              <div key={name} className="border border-portal-border rounded-md p-3 bg-portal-bg2 space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-medium text-portal-text font-mono truncate flex items-center gap-1.5">
                    {name}
                    {lxc && <span className="text-[10px] px-1 py-0.5 rounded border border-portal-border text-portal-text2 not-italic">LXC</span>}
                  </span>
                  <select
                    className="px-2 py-1 text-xs rounded-md border border-portal-border bg-portal-bg2 text-portal-text"
                    value={mode}
                    onChange={(e) => setMode(name, e.target.value)}
                  >
                    <option value="default">{t('stacks.cloudinit.mode_default')}</option>
                    <option value="custom">{t('stacks.cloudinit.mode_custom')}</option>
                    <option value="suppress">{t('stacks.cloudinit.mode_suppress')}</option>
                  </select>
                </div>
                {mode === 'custom' && block && (
                  <CloudInitBlockFields
                    block={block}
                    onPatch={(patch) => patchOverride(name, patch)}
                    profileKey={profileKey}
                    idPrefix={`ci-ov-${name}`}
                    isLxc={lxc}
                  />
                )}
                {mode === 'suppress' && (
                  <p className="text-[11px] text-portal-warn">{t('stacks.cloudinit.suppress_hint')}</p>
                )}
              </div>
            )
          })
        )}

        {/* Verwaiste Overrides (Name nicht mehr im Modell, EC-4) */}
        {orphanNames.length > 0 && (
          <div className="space-y-2 pt-2 border-t border-portal-border">
            <p className="text-[11px] text-portal-text3">{t('stacks.cloudinit.orphans_hint')}</p>
            {orphanNames.map((name) => (
              <div key={name} className="flex items-center justify-between gap-2 text-xs">
                <span className="font-mono text-portal-text2 truncate">
                  {name} <span className="text-portal-warn">({t('stacks.cloudinit.orphan_badge')})</span>
                </span>
                <button type="button" onClick={() => deleteOrphan(name)} className="btn-table-danger">
                  {t('common.remove')}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {saveError && <p className="text-sm text-portal-danger">{saveError}</p>}
      {saveOk && <p className="text-sm text-portal-success">{t('stacks.cloudinit.saved')}</p>}

      <div className="flex items-center gap-2">
        <p className="text-[11px] text-portal-text3 flex-1">{t('stacks.cloudinit.separate_save_hint')}</p>
        <button onClick={onSave} disabled={putMut.isPending} className="btn-primary">
          {putMut.isPending ? t('common.loading') : t('stacks.cloudinit.save_btn')}
        </button>
      </div>
    </div>
  )
}
