// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-92: Metadaten-Block (name/description/required_role/id, AC-EDIT-2).
import { useTranslation } from 'react-i18next'
import { Field, Section, TextField, inputCls } from './fields'
import { deriveId } from './model'

export default function MetaSection({ model, isEdit, onChange }) {
  const { t } = useTranslation()

  const setName = (name) => {
    const patch = { name }
    // Beim Erstellen die id aus dem Namen ableiten, solange der Nutzer sie nicht
    // manuell überschrieben hat (idTouched).
    if (!isEdit && !model._idTouched) patch.id = deriveId(name)
    onChange(patch)
  }

  return (
    <Section title={t('packer_editor.meta.title')} desc={t('packer_editor.meta.desc')}>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <TextField
          label={t('packer_editor.meta.name') + ' *'}
          value={model.name}
          onChange={setName}
          placeholder={t('packer_editor.meta.name_ph')}
        />
        <Field label={t('packer_editor.meta.id') + ' *'} hint={isEdit ? t('packer_editor.meta.id_locked') : t('packer_editor.meta.id_hint')}>
          <input
            className={inputCls}
            value={model.id ?? ''}
            disabled={isEdit}
            placeholder="debian-13"
            onChange={(e) => onChange({ id: e.target.value, _idTouched: true })}
          />
        </Field>
        <Field label={t('packer_editor.meta.required_role')}>
          <select
            className={inputCls}
            value={model.required_role ?? 'operator'}
            onChange={(e) => onChange({ required_role: e.target.value })}
          >
            <option value="viewer">viewer</option>
            <option value="operator">operator</option>
            <option value="admin">admin</option>
          </select>
        </Field>
        <div className="sm:col-span-2">
          <Field label={t('packer_editor.meta.description')}>
            <textarea
              className={inputCls + ' resize-y min-h-[60px]'}
              value={model.description ?? ''}
              onChange={(e) => onChange({ description: e.target.value })}
              placeholder={t('packer_editor.meta.description_ph')}
            />
          </Field>
        </div>
      </div>
    </Section>
  )
}
