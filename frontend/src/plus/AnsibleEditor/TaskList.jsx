// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-93: geordnete Task-Liste (AC-TASK-1). Hinzufügen / Entfernen / Umsortieren.
// Reihenfolge im Modell = Reihenfolge im generierten Playbook.
import { useTranslation } from 'react-i18next'
import { emptyTask } from './model'
import { Section } from './fields'
import TaskCard from './TaskCard'

export default function TaskList({ tasks, onChange }) {
  const { t } = useTranslation()
  const list = Array.isArray(tasks) ? tasks : []

  const add = () => onChange([...list, emptyTask()])
  const update = (i, next) => onChange(list.map((x, j) => (j === i ? next : x)))
  const remove = (i) => onChange(list.filter((_, j) => j !== i))
  const move = (i, dir) => {
    const j = i + dir
    if (j < 0 || j >= list.length) return
    const next = [...list]
    ;[next[i], next[j]] = [next[j], next[i]]
    onChange(next)
  }

  return (
    <Section
      title={t('ansible_editor.tasks.title')}
      desc={t('ansible_editor.tasks.desc')}
      action={<button type="button" className="btn-primary text-xs" onClick={add}>+ {t('ansible_editor.tasks.add')}</button>}
    >
      {list.length === 0 && (
        <button type="button" onClick={add}
          className="w-full rounded-md border border-dashed border-portal-border py-6 text-xs text-portal-text2 hover:border-portal-accent hover:text-portal-text">
          + {t('ansible_editor.tasks.add_first')}
        </button>
      )}
      <div className="space-y-3">
        {list.map((task, i) => (
          <TaskCard
            key={task._uid ?? i}
            task={task}
            index={i}
            total={list.length}
            onChange={(next) => update(i, next)}
            onRemove={() => remove(i)}
            onMoveUp={() => move(i, -1)}
            onMoveDown={() => move(i, 1)}
          />
        ))}
      </div>
    </Section>
  )
}
