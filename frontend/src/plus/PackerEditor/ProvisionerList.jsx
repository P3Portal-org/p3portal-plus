// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-92: geordnete Provisioner-Liste (AC-PROV). shell (inline|script) · file
// (source→destination) · ansible (Playbook). Add/Remove/Reorder ↑↓.
import { useTranslation } from 'react-i18next'
import { Field, TextField, inputCls } from './fields'
import PlainCodeEditor from './PlainCodeEditor'

function InlineLines({ lines, onChange }) {
  const { t } = useTranslation()
  const list = Array.isArray(lines) ? lines : []
  const set = (i, v) => onChange(list.map((x, idx) => (idx === i ? v : x)))
  return (
    <Field label={t('packer_editor.prov.inline_commands')}>
      <div className="space-y-1">
        {list.map((line, i) => (
          <div key={i} className="flex gap-1">
            <input className={inputCls + ' font-mono text-xs'} value={line} onChange={(e) => set(i, e.target.value)} />
            <button type="button" className="btn-table-danger shrink-0" onClick={() => onChange(list.filter((_, idx) => idx !== i))}>✕</button>
          </div>
        ))}
        <button type="button" className="btn-table" onClick={() => onChange([...list, ''])}>+ {t('packer_editor.prov.add_command')}</button>
      </div>
    </Field>
  )
}

function ShellCard({ p, onChange }) {
  const { t } = useTranslation()
  return (
    <div className="space-y-2">
      <div className="flex gap-2">
        {['inline', 'script'].map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => onChange({ mode: m })}
            className={`px-2.5 py-1 text-[11px] rounded-md border transition-colors ${
              (p.mode || 'inline') === m ? 'border-portal-accent bg-portal-accent/10 text-portal-text' : 'border-portal-border text-portal-text2'
            }`}
          >
            {t(`packer_editor.prov.shell_${m}`)}
          </button>
        ))}
      </div>
      {(p.mode || 'inline') === 'inline' ? (
        <InlineLines lines={p.inline} onChange={(v) => onChange({ inline: v })} />
      ) : (
        <>
          <TextField label={t('packer_editor.prov.script_name') + ' *'} value={p.script_name} onChange={(v) => onChange({ script_name: v })} placeholder="setup.sh" />
          <Field label={t('packer_editor.prov.script_content')}>
            <PlainCodeEditor value={p.script_content} onChange={(v) => onChange({ script_content: v })} minHeight="140px" />
          </Field>
        </>
      )}
    </div>
  )
}

function FileCard({ p, onChange }) {
  const { t } = useTranslation()
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <TextField label={t('packer_editor.prov.source_name') + ' *'} value={p.source_name} onChange={(v) => onChange({ source_name: v })} placeholder="cloud.cfg" />
        <TextField label={t('packer_editor.prov.destination') + ' *'} value={p.destination} onChange={(v) => onChange({ destination: v })} placeholder="/etc/cloud/cloud.cfg" />
      </div>
      <Field label={t('packer_editor.prov.source_content')}>
        <PlainCodeEditor value={p.source_content} onChange={(v) => onChange({ source_content: v })} minHeight="140px" />
      </Field>
    </div>
  )
}

function AnsibleCard({ p, onChange }) {
  const { t } = useTranslation()
  return (
    <div className="space-y-2">
      <TextField label={t('packer_editor.prov.playbook_name') + ' *'} value={p.playbook_name} onChange={(v) => onChange({ playbook_name: v })} placeholder="playbook.yml" />
      <Field label={t('packer_editor.prov.playbook_content')}>
        <PlainCodeEditor value={p.playbook_content} onChange={(v) => onChange({ playbook_content: v })} minHeight="160px" />
      </Field>
    </div>
  )
}

const TYPE_LABEL = { shell: 'prov.type_shell', file: 'prov.type_file', ansible: 'prov.type_ansible' }

function emptyProvisioner(type) {
  if (type === 'file') return { type: 'file', source_name: '', source_content: '', destination: '' }
  if (type === 'ansible') return { type: 'ansible', playbook_name: '', playbook_content: '', extra_vars: {} }
  return { type: 'shell', mode: 'inline', inline: [''], script_name: null, script_content: '' }
}

export default function ProvisionerList({ provisioners, onChange }) {
  const { t } = useTranslation()
  const list = Array.isArray(provisioners) ? provisioners : []

  const update = (i, patch) => onChange(list.map((p, idx) => (idx === i ? { ...p, ...patch } : p)))
  const remove = (i) => onChange(list.filter((_, idx) => idx !== i))
  const add = (type) => onChange([...list, emptyProvisioner(type)])
  const move = (i, d) => {
    const j = i + d
    if (j < 0 || j >= list.length) return
    const next = [...list]
    ;[next[i], next[j]] = [next[j], next[i]]
    onChange(next)
  }

  return (
    <div className="rounded-lg border border-portal-border bg-portal-bg2/40 p-4 space-y-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h4 className="text-sm font-semibold text-portal-text">{t('packer_editor.prov.title')}</h4>
          <p className="text-[11px] text-portal-text3 leading-snug mt-0.5">{t('packer_editor.prov.desc')}</p>
        </div>
        <div className="flex gap-1">
          {['shell', 'file', 'ansible'].map((type) => (
            <button key={type} type="button" className="btn-table" onClick={() => add(type)}>
              + {t(`packer_editor.${TYPE_LABEL[type]}`)}
            </button>
          ))}
        </div>
      </div>

      {list.length === 0 && <p className="text-[11px] text-portal-text3">{t('packer_editor.prov.empty')}</p>}

      {list.map((p, i) => (
        <div key={i} className="rounded-md border border-portal-border bg-portal-bg p-3 space-y-2">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-semibold text-portal-text">
              <span className="text-portal-text3">#{i + 1}</span> {t(`packer_editor.${TYPE_LABEL[p.type]}`)}
            </span>
            <div className="flex gap-1">
              <button type="button" className="btn-table" onClick={() => move(i, -1)} disabled={i === 0}>↑</button>
              <button type="button" className="btn-table" onClick={() => move(i, 1)} disabled={i === list.length - 1}>↓</button>
              <button type="button" className="btn-table-danger" onClick={() => remove(i)}>{t('common.delete')}</button>
            </div>
          </div>
          {p.type === 'shell' && <ShellCard p={p} onChange={(patch) => update(i, patch)} />}
          {p.type === 'file' && <FileCard p={p} onChange={(patch) => update(i, patch)} />}
          {p.type === 'ansible' && <AnsibleCard p={p} onChange={(patch) => update(i, patch)} />}
        </div>
      ))}
    </div>
  )
}
