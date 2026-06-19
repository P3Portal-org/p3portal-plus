// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-92: Source-Block (AC-SRC). Typ-Toggle proxmox-clone | proxmox-iso,
// gemeinsame VM-Settings + SSH, clone-/iso-spezifische Felder + boot_command.
// Die ISO-Datei selbst ist ein Build-Parameter (meta.yaml iso_file), kein
// Source-Modell-Feld → wird beim Bauen pro Build gewählt (Architektur § H).
import { useTranslation } from 'react-i18next'
import { Field, Section, TextField, NumberField, Toggle, ComboField, inputCls } from './fields'
import { defaultBootCommand } from './model'
import { useProxmoxTemplates } from './hooks'

function BootCommandEditor({ lines, osProfile, onChange }) {
  const { t } = useTranslation()
  const list = Array.isArray(lines) ? lines : []
  const set = (i, v) => onChange(list.map((x, idx) => (idx === i ? v : x)))
  const add = () => onChange([...list, ''])
  const remove = (i) => onChange(list.filter((_, idx) => idx !== i))
  const move = (i, d) => {
    const j = i + d
    if (j < 0 || j >= list.length) return
    const next = [...list]
    ;[next[i], next[j]] = [next[j], next[i]]
    onChange(next)
  }
  return (
    <Field label={t('packer_editor.source.boot_command')} hint={t('packer_editor.source.boot_command_hint')}>
      <div className="space-y-1">
        {list.length === 0 && (
          <p className="text-[11px] text-portal-text3">{t('packer_editor.source.boot_command_empty')}</p>
        )}
        {list.map((line, i) => (
          <div key={i} className="flex items-center gap-1">
            <span className="text-[11px] text-portal-text3 w-5 text-right tabular-nums">{i + 1}</span>
            <input
              className={inputCls + ' font-mono text-xs'}
              value={line}
              onChange={(e) => set(i, e.target.value)}
            />
            <button type="button" className="btn-table shrink-0" onClick={() => move(i, -1)} disabled={i === 0} title="↑">↑</button>
            <button type="button" className="btn-table shrink-0" onClick={() => move(i, 1)} disabled={i === list.length - 1} title="↓">↓</button>
            <button type="button" className="btn-table-danger shrink-0" onClick={() => remove(i)} title={t('common.delete')}>✕</button>
          </div>
        ))}
        <div className="flex gap-2 pt-1">
          <button type="button" className="btn-table" onClick={add}>+ {t('packer_editor.source.boot_command_add')}</button>
          <button type="button" className="btn-table" onClick={() => onChange(defaultBootCommand(osProfile))}>
            {t('packer_editor.source.boot_command_default')}
          </button>
        </div>
      </div>
    </Field>
  )
}

export default function SourceSection({ source, osProfile, onChange, onTypeChange }) {
  const { t } = useTranslation()
  const s = source || {}
  const isIso = s.type === 'proxmox-iso'
  const { data: templates } = useProxmoxTemplates()
  const templateNames = [...new Set((templates || []).map((x) => x.name).filter(Boolean))]

  const set = (patch) => onChange(patch)

  return (
    <Section title={t('packer_editor.source.title')} desc={t('packer_editor.source.desc')}>
      {/* Typ-Toggle */}
      <div className="flex gap-2">
        {['proxmox-iso', 'proxmox-clone'].map((type) => (
          <button
            key={type}
            type="button"
            onClick={() => onTypeChange(type)}
            className={`px-3 py-1.5 text-xs rounded-md border transition-colors ${
              s.type === type
                ? 'border-portal-accent bg-portal-accent/10 text-portal-text font-medium'
                : 'border-portal-border text-portal-text2 hover:text-portal-text'
            }`}
          >
            {t(`packer_editor.source.type_${type === 'proxmox-iso' ? 'iso' : 'clone'}`)}
          </button>
        ))}
      </div>

      {/* Erklärung der aktiven Bauweise (ISO = neu / Clone = bestehendes klonen) */}
      <div className="rounded-md border border-portal-info/30 bg-portal-info/10 px-3 py-2 text-[11px] leading-relaxed text-portal-text2">
        {isIso ? t('packer_editor.source.type_help_iso') : t('packer_editor.source.type_help_clone')}
      </div>

      {/* Clone-spezifisch */}
      {!isIso && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <ComboField
            label={t('packer_editor.source.clone_template') + ' *'}
            value={s.clone_template}
            onChange={(v) => set({ clone_template: v })}
            options={templateNames}
            placeholder={t('packer_editor.source.clone_template_ph')}
            hint={t('packer_editor.source.clone_template_hint')}
          />
          <div className="flex items-end pb-1">
            <Toggle label={t('packer_editor.source.full_clone')} checked={s.full_clone} onChange={(v) => set({ full_clone: v })} />
          </div>
        </div>
      )}

      {/* ISO-Hinweis: ISO-Datei = Build-Parameter */}
      {isIso && (
        <p className="text-[11px] text-portal-text3">{t('packer_editor.source.iso_build_param')}</p>
      )}

      {/* Gemeinsame VM-Settings */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        <NumberField label={t('packer_editor.source.cores')} value={s.cores} onChange={(v) => set({ cores: v })} min={1} max={512} />
        <NumberField label={t('packer_editor.source.memory_mb')} value={s.memory_mb} onChange={(v) => set({ memory_mb: v })} min={128} />
        <NumberField label={t('packer_editor.source.disk_size_gb')} value={s.disk_size_gb} onChange={(v) => set({ disk_size_gb: v })} min={1} />
        <TextField label={t('packer_editor.source.network_bridge')} value={s.network_bridge} onChange={(v) => set({ network_bridge: v })} placeholder="vmbr0" />
        <TextField label={t('packer_editor.source.network_model')} value={s.network_model} onChange={(v) => set({ network_model: v })} placeholder="virtio" />
        <TextField label={t('packer_editor.source.scsi_controller')} value={s.scsi_controller} onChange={(v) => set({ scsi_controller: v })} placeholder="virtio-scsi-pci" />
      </div>
      <div className="flex flex-wrap gap-4">
        <Toggle label={t('packer_editor.source.qemu_agent')} checked={s.qemu_agent} onChange={(v) => set({ qemu_agent: v })} />
        <Toggle label={t('packer_editor.source.cloud_init')} checked={s.cloud_init} onChange={(v) => set({ cloud_init: v })} />
        <Toggle label={t('packer_editor.source.network_firewall')} checked={s.network_firewall} onChange={(v) => set({ network_firewall: v })} />
      </div>
      <TextField label={t('packer_editor.source.template_description')} value={s.template_description} onChange={(v) => set({ template_description: v })} placeholder={t('packer_editor.source.template_description_ph')} />

      {/* SSH-Connection (beide Typen) */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <TextField label={t('packer_editor.source.ssh_username')} value={s.ssh_username} onChange={(v) => set({ ssh_username: v })} placeholder="root" />
        <TextField label={t('packer_editor.source.ssh_timeout')} value={s.ssh_timeout} onChange={(v) => set({ ssh_timeout: v })} placeholder="20m" />
        <TextField label={t('packer_editor.source.ssh_private_key_name')} value={s.ssh_private_key_name} onChange={(v) => set({ ssh_private_key_name: v })} placeholder="sysadm" />
      </div>

      {/* ISO-spezifisch: boot/http */}
      {isIso && (
        <>
          <div className="grid grid-cols-2 gap-3">
            <TextField label={t('packer_editor.source.boot_wait')} value={s.boot_wait} onChange={(v) => set({ boot_wait: v })} placeholder="5s" />
            <NumberField label={t('packer_editor.source.http_port')} value={s.http_port} onChange={(v) => set({ http_port: v })} min={1} max={65535} />
          </div>
          <BootCommandEditor lines={s.boot_command} osProfile={osProfile} onChange={(v) => set({ boot_command: v })} />
        </>
      )}
    </Section>
  )
}
