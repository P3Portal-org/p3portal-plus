// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-93: durchsuchbarer Modul-Picker aus GET /modules (AC-MOD-1). Sucht über
// Kurznamen + short_description. Bei Auswahl → onSelect(fqcn).
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useModules } from './hooks'
import { inputCls } from './fields'

const PREFIX = 'ansible.builtin.'
const shortName = (fqcn) => (fqcn?.startsWith(PREFIX) ? fqcn.slice(PREFIX.length) : fqcn)

export default function ModulePicker({ value, onSelect }) {
  const { t } = useTranslation()
  const { data: modules, isLoading, error } = useModules()
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)

  const list = Array.isArray(modules) ? modules : []
  const q = query.trim().toLowerCase()
  const filtered = (q
    ? list.filter((m) => shortName(m.name).includes(q) || (m.short_description || '').toLowerCase().includes(q))
    : list
  ).slice(0, 60)

  if (value) {
    return (
      <div className="flex items-center gap-2">
        <span className="text-xs font-mono text-portal-text">{value}</span>
        <button type="button" className="btn-table" onClick={() => { onSelect(''); setOpen(true) }}>
          {t('ansible_editor.module_change')}
        </button>
      </div>
    )
  }

  return (
    <div className="relative">
      <input
        className={inputCls}
        value={query}
        placeholder={t('ansible_editor.module_search_ph')}
        onChange={(e) => { setQuery(e.target.value); setOpen(true) }}
        onFocus={() => setOpen(true)}
      />
      {isLoading && <p className="text-[11px] text-portal-text3 mt-1">{t('common.loading')}</p>}
      {error && <p className="text-[11px] text-portal-danger mt-1">{t('ansible_editor.modules_error')}</p>}
      {open && !isLoading && !error && (
        <div className="nowheel absolute z-20 left-0 right-0 mt-1 max-h-64 overflow-y-auto rounded-md border border-portal-border bg-portal-bg2 shadow-lg">
          {filtered.length === 0 && (
            <p className="px-3 py-2 text-[11px] text-portal-text3">{t('ansible_editor.modules_empty')}</p>
          )}
          {filtered.map((m) => (
            <button
              key={m.name}
              type="button"
              className="w-full text-left px-3 py-1.5 hover:bg-portal-accent/10 border-b border-portal-border last:border-0"
              onClick={() => { onSelect(m.name); setOpen(false); setQuery('') }}
            >
              <span className="text-xs font-mono text-portal-text">{shortName(m.name)}</span>
              {m.short_description && (
                <span className="block text-[10px] text-portal-text3 truncate">{m.short_description}</span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
