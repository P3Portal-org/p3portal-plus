// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-92: Installer-Builder (proxmox-iso, AC-INST). OS-Profil + Pflichtfelder
// + Add/Remove-Optionale (Baukasten) + synchronisierter Freitext-Editor mit
// Raw-Override (One-Way Form→Text, Architektur § E). Passwörter sind write-only:
// ein gespeicherter Hash erscheint als „●●● gesetzt", neu getippt = Klartext, der
// serverseitig zu $6$-sha512-crypt wird (nie persistiert).
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Field, Section, TextField, NumberField, inputCls } from './fields'
import PlainCodeEditor from './PlainCodeEditor'
import ConfirmModal from '../../components/common/ConfirmModal'

// Optionale Felder pro OS-Profil (Add/Remove-Baukasten, AC-INST-3).
// kind: 'text' (String) | 'lines' (String-Array, je Zeile ein Befehl).
const OPTIONAL_SPECS = {
  'debian-preseed': [
    { key: 'apt_mirror', kind: 'text', labelKey: 'apt_mirror' },
    { key: 'ntp_server', kind: 'text', labelKey: 'ntp_server' },
    { key: 'partition_recipe', kind: 'text', labelKey: 'partition_recipe' },
    { key: 'extra_late_commands', kind: 'lines', labelKey: 'extra_late_commands' },
  ],
  'rhel-kickstart': [
    { key: 'ntp_server', kind: 'text', labelKey: 'ntp_server' },
    { key: 'extra_post_commands', kind: 'lines', labelKey: 'extra_post_commands' },
  ],
  'ubuntu-autoinstall': [
    { key: 'extra_late_commands', kind: 'lines', labelKey: 'extra_late_commands' },
  ],
}

function PackageEditor({ packages, onChange }) {
  const { t } = useTranslation()
  const list = Array.isArray(packages) ? packages : []
  const [input, setInput] = useState('')
  const add = () => {
    const v = input.trim()
    if (v && !list.includes(v)) onChange([...list, v])
    setInput('')
  }
  return (
    <Field label={t('packer_editor.installer.packages')}>
      <div className="flex flex-wrap gap-1.5 mb-1.5">
        {list.map((p) => (
          <span key={p} className="inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded-md bg-portal-bg2 border border-portal-border text-portal-text">
            {p}
            <button type="button" className="text-portal-text3 hover:text-portal-danger" onClick={() => onChange(list.filter((x) => x !== p))}>✕</button>
          </span>
        ))}
        {list.length === 0 && <span className="text-[11px] text-portal-text3">{t('packer_editor.installer.packages_empty')}</span>}
      </div>
      <div className="flex gap-1">
        <input
          className={inputCls}
          value={input}
          placeholder={t('packer_editor.installer.packages_ph')}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); add() } }}
        />
        <button type="button" className="btn-table shrink-0" onClick={add}>+</button>
      </div>
    </Field>
  )
}

function LinesEditor({ label, lines, onChange }) {
  const list = Array.isArray(lines) ? lines : []
  const set = (i, v) => onChange(list.map((x, idx) => (idx === i ? v : x)))
  return (
    <Field label={label}>
      <div className="space-y-1">
        {list.map((line, i) => (
          <div key={i} className="flex gap-1">
            <input className={inputCls + ' font-mono text-xs'} value={line} onChange={(e) => set(i, e.target.value)} />
            <button type="button" className="btn-table-danger shrink-0" onClick={() => onChange(list.filter((_, idx) => idx !== i))}>✕</button>
          </div>
        ))}
        <button type="button" className="btn-table" onClick={() => onChange([...list, ''])}>+</button>
      </div>
    </Field>
  )
}

function PasswordField({ label, plain, hashSet, onChange }) {
  const { t } = useTranslation()
  return (
    <Field label={label} hint={hashSet && !plain ? t('packer_editor.installer.password_set') : undefined}>
      <input
        type="password"
        className={inputCls}
        value={plain ?? ''}
        placeholder={hashSet ? '●●● ' + t('packer_editor.installer.password_set_ph') : ''}
        onChange={(e) => onChange(e.target.value)}
      />
    </Field>
  )
}

export default function InstallerBuilder({ installer, onChange, previewFn }) {
  const { t } = useTranslation()
  const inst = installer || {}
  const profile = inst.os_profile || 'debian-preseed'
  const specs = OPTIONAL_SPECS[profile] || []
  const optional = inst.optional || {}

  const [genText, setGenText] = useState('')      // read-only generierte Vorschau (raw_override=false)
  const [genLoading, setGenLoading] = useState(false)
  const [genError, setGenError] = useState(null)
  const [addKey, setAddKey] = useState('')
  const [confirmOff, setConfirmOff] = useState(false) // Override-verwerfen (P3 ConfirmModal)

  const set = (patch) => onChange(patch)
  const setOpt = (key, value) => set({ optional: { ...optional, [key]: value } })
  const removeOpt = (key) => {
    const next = { ...optional }
    delete next[key]
    set({ optional: next })
  }

  const activeOptKeys = specs.filter((s) => Object.prototype.hasOwnProperty.call(optional, s.key))
  const availableOptKeys = specs.filter((s) => !Object.prototype.hasOwnProperty.call(optional, s.key))

  const addOptField = () => {
    const spec = specs.find((s) => s.key === addKey)
    if (!spec) return
    setOpt(spec.key, spec.kind === 'lines' ? [] : '')
    setAddKey('')
  }

  // Generierte Vorschau holen (read-only, raw_override=false).
  const refreshPreview = async () => {
    setGenLoading(true)
    setGenError(null)
    try {
      const preview = await previewFn()
      const entry = Object.entries(preview?.files || {}).find(([name]) => name.startsWith('http/'))
      setGenText(entry ? entry[1] : t('packer_editor.installer.no_preview'))
    } catch (err) {
      setGenError(err?.response?.data?.detail ?? t('common.error_generic'))
    } finally {
      setGenLoading(false)
    }
  }

  // In den Override-Modus wechseln: zuerst Vorschau als Startinhalt holen.
  const enableOverride = async () => {
    setGenLoading(true)
    setGenError(null)
    try {
      const preview = await previewFn()
      const entry = Object.entries(preview?.files || {}).find(([name]) => name.startsWith('http/'))
      set({ raw_override: true, raw_content: entry ? entry[1] : '' })
    } catch (err) {
      // Auch ohne Vorschau Override erlauben (leerer Start).
      set({ raw_override: true, raw_content: inst.raw_content || '' })
      setGenError(err?.response?.data?.detail ?? null)
    } finally {
      setGenLoading(false)
    }
  }

  const disableOverride = () => setConfirmOff(true)

  const ro = !!inst.raw_override

  return (
    <>
    <Section
      title={t('packer_editor.installer.title')}
      desc={t('packer_editor.installer.desc')}
      action={
        <select
          className="text-xs px-2 py-1 rounded-md border border-portal-border bg-portal-bg2 text-portal-text"
          value={profile}
          onChange={(e) => set({ os_profile: e.target.value })}
        >
          <option value="debian-preseed">{t('packer_editor.installer.profile_debian')}</option>
          <option value="ubuntu-autoinstall">{t('packer_editor.installer.profile_ubuntu')}</option>
          <option value="rhel-kickstart">{t('packer_editor.installer.profile_rhel')}</option>
        </select>
      }
    >
      {ro && (
        <div className="rounded-md border border-portal-warn/40 bg-portal-warn/10 p-2 text-[11px] text-portal-warn">
          {t('packer_editor.installer.override_active')}
        </div>
      )}

      {/* Pflichtfelder (read-only im Override-Modus) */}
      <div className={`grid grid-cols-2 sm:grid-cols-3 gap-3 ${ro ? 'opacity-60' : ''}`}>
        <TextField label={t('packer_editor.installer.hostname')} value={inst.hostname} onChange={(v) => set({ hostname: v })} disabled={ro} placeholder="template-host" />
        <TextField label={t('packer_editor.installer.locale')} value={inst.locale} onChange={(v) => set({ locale: v })} disabled={ro} placeholder="en_US.UTF-8" />
        <TextField label={t('packer_editor.installer.keyboard')} value={inst.keyboard} onChange={(v) => set({ keyboard: v })} disabled={ro} placeholder="us" />
        <TextField label={t('packer_editor.installer.timezone')} value={inst.timezone} onChange={(v) => set({ timezone: v })} disabled={ro} placeholder="UTC" />
        <TextField label={t('packer_editor.installer.language')} value={inst.language} onChange={(v) => set({ language: v })} disabled={ro} placeholder="en" />
        <TextField label={t('packer_editor.installer.country')} value={inst.country} onChange={(v) => set({ country: v })} disabled={ro} placeholder="US" />
        <PasswordField label={t('packer_editor.installer.root_password') + ' *'} plain={inst.root_password_plain} hashSet={!!inst.root_password_hash} onChange={(v) => !ro && set({ root_password_plain: v })} />
        <TextField label={t('packer_editor.installer.username')} value={inst.username} onChange={(v) => set({ username: v })} disabled={ro} placeholder="sysadm" />
        <NumberField label={t('packer_editor.installer.user_uid')} value={inst.user_uid} onChange={(v) => set({ user_uid: v })} disabled={ro} min={0} max={65535} />
        <PasswordField label={t('packer_editor.installer.user_password')} plain={inst.user_password_plain} hashSet={!!inst.user_password_hash} onChange={(v) => !ro && set({ user_password_plain: v })} />
      </div>

      <div className={ro ? 'opacity-60 pointer-events-none' : ''}>
        <Field label={t('packer_editor.installer.ssh_public_key')} hint={t('packer_editor.installer.ssh_public_key_hint')}>
          <input className={inputCls + ' font-mono text-xs'} value={inst.ssh_public_key ?? ''} onChange={(e) => set({ ssh_public_key: e.target.value })} placeholder="ssh-ed25519 AAAA…" />
        </Field>
        <div className="mt-3">
          <PackageEditor packages={inst.packages} onChange={(v) => set({ packages: v })} />
        </div>

        {/* Optionale Felder (Add/Remove-Baukasten) */}
        <div className="mt-3 space-y-3">
          {activeOptKeys.map((spec) => (
            <div key={spec.key} className="relative">
              {spec.kind === 'lines' ? (
                <LinesEditor label={t(`packer_editor.installer.opt.${spec.labelKey}`)} lines={optional[spec.key]} onChange={(v) => setOpt(spec.key, v)} />
              ) : (
                <TextField label={t(`packer_editor.installer.opt.${spec.labelKey}`)} value={optional[spec.key]} onChange={(v) => setOpt(spec.key, v)} />
              )}
              <button type="button" className="absolute top-0 right-0 text-[11px] text-portal-text3 hover:text-portal-danger" onClick={() => removeOpt(spec.key)}>
                {t('packer_editor.installer.opt_remove')}
              </button>
            </div>
          ))}
          {availableOptKeys.length > 0 && (
            <div className="flex gap-1 items-center">
              <select className={inputCls + ' max-w-[16rem]'} value={addKey} onChange={(e) => setAddKey(e.target.value)}>
                <option value="">{t('packer_editor.installer.opt_add_ph')}</option>
                {availableOptKeys.map((s) => <option key={s.key} value={s.key}>{t(`packer_editor.installer.opt.${s.labelKey}`)}</option>)}
              </select>
              <button type="button" className="btn-table shrink-0" disabled={!addKey} onClick={addOptField}>{t('packer_editor.installer.opt_add')}</button>
            </div>
          )}
        </div>
      </div>

      {/* Freitext-Editor (synchronisiert / Override) */}
      <div className="border-t border-portal-border pt-3 space-y-2">
        <div className="flex items-center justify-between gap-2">
          <h5 className="text-xs font-semibold text-portal-text2">{t('packer_editor.installer.raw_title')}</h5>
          <div className="flex gap-2">
            {!ro && <button type="button" className="btn-table" disabled={genLoading} onClick={refreshPreview}>{genLoading ? '…' : t('packer_editor.installer.raw_refresh')}</button>}
            {!ro && <button type="button" className="btn-table" disabled={genLoading} onClick={enableOverride}>{t('packer_editor.installer.raw_edit')}</button>}
            {ro && <button type="button" className="btn-table" onClick={disableOverride}>{t('packer_editor.installer.raw_regenerate')}</button>}
          </div>
        </div>
        {genError && <p className="text-[11px] text-portal-danger">{genError}</p>}
        {ro ? (
          <PlainCodeEditor value={inst.raw_content} onChange={(v) => set({ raw_content: v })} minHeight="240px" />
        ) : (
          <PlainCodeEditor value={genText} readOnly minHeight="180px" />
        )}
      </div>
    </Section>
    {confirmOff && (
      <ConfirmModal
        title={t('packer_editor.installer.override_off_title')}
        body={t('packer_editor.installer.override_off_confirm')}
        confirmLabel={t('common.confirm')}
        cancelLabel={t('common.cancel')}
        variant="danger"
        onConfirm={() => set({ raw_override: false, raw_content: '' })}
        onClose={() => setConfirmOff(false)}
      />
    )}
    </>
  )
}
