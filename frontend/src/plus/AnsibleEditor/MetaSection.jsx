// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-93: Metadaten als schlanke Top-Leiste über der Canvas (name/id/category/
// required_role/description, AC-EDIT-2). Kompakt-horizontal statt großer Karte,
// damit die Canvas im Mittelpunkt steht.
import { useTranslation } from 'react-i18next'
import { Field, inputCls } from './fields'
import { deriveId } from './model'

export default function MetaSection({ model, isEdit, onChange }) {
  const { t } = useTranslation()

  const setName = (name) => {
    const patch = { name }
    if (!isEdit && !model._idTouched) patch.id = deriveId(name)
    onChange(patch)
  }

  return (
    <div className="rounded-lg border border-portal-border bg-portal-bg2/40 px-3 py-2.5">
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-[2fr_1.4fr_1fr_1fr] gap-2.5 items-end">
        <Field label={t('ansible_editor.meta.name') + ' *'}>
          <input className={inputCls} value={model.name ?? ''}
            placeholder={t('ansible_editor.meta.name_ph')} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label={t('ansible_editor.meta.id') + ' *'} hint={isEdit ? t('ansible_editor.meta.id_locked') : undefined}>
          <input className={inputCls} value={model.id ?? ''} disabled={isEdit} placeholder="nginx-setup"
            onChange={(e) => onChange({ id: e.target.value, _idTouched: true })} />
        </Field>
        <Field label={t('ansible_editor.meta.category')}>
          <select className={inputCls} value={model.category ?? ''}
            onChange={(e) => onChange({ category: e.target.value || null })}>
            <option value="">{t('ansible_editor.meta.category_none')}</option>
            <option value="vm_deployment">vm_deployment</option>
            <option value="lxc_deployment">lxc_deployment</option>
            <option value="vm_lxc_config">vm_lxc_config</option>
          </select>
        </Field>
        <Field label={t('ansible_editor.meta.required_role')}>
          <select className={inputCls} value={model.required_role ?? 'operator'}
            onChange={(e) => onChange({ required_role: e.target.value })}>
            <option value="viewer">viewer</option>
            <option value="operator">operator</option>
            <option value="admin">admin</option>
          </select>
        </Field>
      </div>
      <input className={inputCls + ' mt-2'} value={model.description ?? ''}
        placeholder={t('ansible_editor.meta.description_ph')}
        onChange={(e) => onChange({ description: e.target.value })} />
    </div>
  )
}
