// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-93: Nebendateien-Editor (AC-FILE). Freie Dateien unter files/, die kein
// Provisioner/Installer erzeugt — z. B. der von einem copy-Task referenzierte
// index.html. name → inhalt; Pfad-/Traversal-Härtung serverseitig.
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { inputCls } from './fields'
import PlainCodeEditor from './PlainCodeEditor'

export default function SideFilesPanel({ sideFiles, onChange }) {
  const { t } = useTranslation()
  const files = sideFiles || {}
  const names = Object.keys(files)
  const [newName, setNewName] = useState('')

  const setContent = (name, content) => onChange({ ...files, [name]: content })
  const remove = (name) => {
    const next = { ...files }
    delete next[name]
    onChange(next)
  }
  const add = () => {
    const n = newName.trim()
    if (n && !Object.prototype.hasOwnProperty.call(files, n)) onChange({ ...files, [n]: '' })
    setNewName('')
  }

  return (
    <div className="rounded-lg border border-portal-border bg-portal-bg2/40 p-4 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <h4 className="text-sm font-semibold text-portal-text">{t('ansible_editor.files.title')}</h4>
      </div>
      <p className="text-[11px] text-portal-text3">{t('ansible_editor.files.hint')}</p>

      {names.length === 0 && <p className="text-[11px] text-portal-text3">{t('ansible_editor.files.empty')}</p>}

      {names.map((name) => (
        <div key={name} className="rounded-md border border-portal-border bg-portal-bg p-3 space-y-2">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-mono font-semibold text-portal-text">{name}</span>
            <button type="button" className="btn-table-danger" onClick={() => remove(name)}>{t('common.delete')}</button>
          </div>
          <PlainCodeEditor value={files[name]} onChange={(v) => setContent(name, v)} minHeight="120px" />
        </div>
      ))}

      <div className="flex gap-1">
        <input
          className={inputCls + ' font-mono text-xs'}
          value={newName}
          placeholder={t('ansible_editor.files.name_ph')}
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); add() } }}
        />
        <button type="button" className="btn-table shrink-0" onClick={add}>+ {t('ansible_editor.files.add')}</button>
      </div>
    </div>
  )
}
