// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-93: optionale Task-Level-Felder (AC-LEVEL). when/loop/register/become/
// tags/notify — aufklappbar, nur gesetzte Felder werden ins YAML emittiert.
// notify referenziert nur Handler-Namen (kein Handler-Builder, AC-LEVEL-3).
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Field, inputCls } from './fields'

// Komma-getrennte Liste ↔ Array.
const toList = (s) => (s ?? '').split(',').map((x) => x.trim()).filter(Boolean)
const fromList = (a) => (Array.isArray(a) ? a.join(', ') : '')

function hasAny(task) {
  return !!(task.when || task.loop || task.register_var || task.become != null
    || (task.tags && task.tags.length) || (task.notify && task.notify.length))
}

export default function TaskLevelFields({ task, onChange }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(() => hasAny(task))

  const set = (patch) => onChange(patch)

  if (!open) {
    return (
      <button type="button" className="btn-table text-[11px]" onClick={() => setOpen(true)}>
        + {t('ansible_editor.level.show')}
      </button>
    )
  }

  const becomeSel = task.become === true ? 'true' : task.become === false ? 'false' : ''

  return (
    <div className="rounded-md border border-portal-border bg-portal-bg p-3 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-semibold text-portal-text2">{t('ansible_editor.level.title')}</span>
        <button type="button" className="btn-table text-[11px]" onClick={() => setOpen(false)}>{t('ansible_editor.level.hide')}</button>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <Field label="when" hint={t('ansible_editor.level.when_hint')}>
          <input className={inputCls + ' font-mono'} value={task.when ?? ''} placeholder="ansible_facts.os_family == 'Debian'"
            onChange={(e) => set({ when: e.target.value || null })} />
        </Field>
        <Field label="loop" hint={t('ansible_editor.level.loop_hint')}>
          <input className={inputCls + ' font-mono'} value={typeof task.loop === 'string' ? task.loop : ''} placeholder="{{ packages }}"
            onChange={(e) => set({ loop: e.target.value || null })} />
        </Field>
        <Field label="register" hint={t('ansible_editor.level.register_hint')}>
          <input className={inputCls + ' font-mono'} value={task.register_var ?? ''} placeholder="result"
            onChange={(e) => set({ register_var: e.target.value || null })} />
        </Field>
        <Field label="become" hint={t('ansible_editor.level.become_hint')}>
          <select className={inputCls} value={becomeSel}
            onChange={(e) => set({ become: e.target.value === '' ? null : e.target.value === 'true' })}>
            <option value="">{t('ansible_editor.bool_default')}</option>
            <option value="true">{t('ansible_editor.bool_true')}</option>
            <option value="false">{t('ansible_editor.bool_false')}</option>
          </select>
        </Field>
        <Field label="tags" hint={t('ansible_editor.level.tags_hint')}>
          <input className={inputCls} value={fromList(task.tags)} placeholder="web, setup"
            onChange={(e) => set({ tags: toList(e.target.value) })} />
        </Field>
        <Field label="notify" hint={t('ansible_editor.level.notify_hint')}>
          <input className={inputCls} value={fromList(task.notify)} placeholder="reload nginx"
            onChange={(e) => set({ notify: toList(e.target.value) })} />
        </Field>
      </div>
    </div>
  )
}
