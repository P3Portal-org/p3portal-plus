// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-93: eine Task-Karte (AC-TASK). Name + Modul (ModulePicker) + die
// schema-getriebenen Modul-Parameter (SchemaFieldRenderer) + optionale
// Task-Level-Felder. Lädt das Modul-Schema bei Modulwahl.
import { useTranslation } from 'react-i18next'
import { useModuleSchema } from './hooks'
import { Field, inputCls } from './fields'
import ModulePicker from './ModulePicker'
import SchemaFieldRenderer from './SchemaFieldRenderer'
import TaskLevelFields from './TaskLevelFields'

export default function TaskCard({ task, index, total, onChange, onRemove, onMoveUp, onMoveDown }) {
  const { t } = useTranslation()
  const { data: schema, isLoading, error } = useModuleSchema(task.module)

  const setModule = (module) => onChange({ ...task, module, params: {} })
  const setParam = (name, value) => {
    const params = { ...task.params }
    if (value === undefined) delete params[name]
    else params[name] = value
    onChange({ ...task, params })
  }

  return (
    <div className="rounded-lg border border-portal-border bg-portal-bg p-3 space-y-3">
      <div className="flex items-center gap-2">
        <span className="text-[11px] font-mono text-portal-text3 shrink-0">#{index + 1}</span>
        <input
          className={inputCls + ' flex-1'}
          value={task.name ?? ''}
          placeholder={t('ansible_editor.task.name_ph')}
          onChange={(e) => onChange({ ...task, name: e.target.value })}
        />
        <button type="button" className="btn-table" disabled={index === 0} onClick={onMoveUp} title={t('ansible_editor.task.up')}>↑</button>
        <button type="button" className="btn-table" disabled={index === total - 1} onClick={onMoveDown} title={t('ansible_editor.task.down')}>↓</button>
        <button type="button" className="btn-table-danger" onClick={onRemove}>{t('common.delete')}</button>
      </div>

      <Field label={t('ansible_editor.task.module') + ' *'} hint={t('ansible_editor.task.module_hint')}>
        <ModulePicker value={task.module} onSelect={setModule} />
      </Field>

      {task.module && (
        <>
          {isLoading && <p className="text-xs text-portal-text2">{t('common.loading')}</p>}
          {error && <p className="text-xs text-portal-danger">{t('ansible_editor.schema_error')}</p>}
          {!isLoading && !error && (
            <SchemaFieldRenderer schema={schema} params={task.params} onParamChange={setParam} />
          )}
          <TaskLevelFields task={task} onChange={(patch) => onChange({ ...task, ...patch })} />
        </>
      )}
    </div>
  )
}
