// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-91: kompakte, deklarative Regel-Liste (geteilt von der Gast-Firewall-
// Sektion und der Stack-Security-Group-Karte). Zeigt je Regel eine Zusammen-
// fassungs-Zeile in der YAML-Reihenfolge (= Auswertungs-Reihenfolge, top-down)
// mit Hoch/Runter/Bearbeiten/Entfernen; „Regel hinzufügen" öffnet den Modal.
import { useState } from 'react'
import StackFirewallRuleModal from './StackFirewallRuleModal'

// Einzeilige Zusammenfassung einer Regel (Richtung · Aktion · Proto/Port · Quelle→Ziel).
function ruleSummary(r) {
  const dir = r.type === 'group' ? `group → ${r.action}` : `${r.type} ${r.action}`
  const proto = r.macro
    ? r.macro
    : [r.proto, r.dport ? `dport ${r.dport}` : '', r.sport ? `sport ${r.sport}` : '']
      .filter(Boolean).join(' ')
  const addr = [r.source ? `src ${r.source}` : '', r.dest ? `dst ${r.dest}` : ''].filter(Boolean).join(' ')
  return [dir, proto, addr].filter(Boolean).join('  ·  ')
}

export default function StackFirewallRuleList({
  t, rules, onChange, refs = [], macros = [], securityGroupNames = [], withGroup = true,
}) {
  const list = Array.isArray(rules) ? rules : []
  // null = zu, { index } = Bearbeiten, { index: null } = Neu.
  const [editing, setEditing] = useState(null)

  const move = (from, to) => {
    if (to < 0 || to >= list.length) return
    const arr = list.slice()
    const [item] = arr.splice(from, 1)
    arr.splice(to, 0, item)
    onChange(arr)
  }
  const remove = (i) => onChange(list.filter((_, idx) => idx !== i))
  const save = (rule) => {
    const arr = list.slice()
    if (editing?.index == null) arr.push(rule)
    else arr[editing.index] = rule
    onChange(arr)
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs text-portal-text2 font-medium">
          {t('stacks.firewall.rules')}{list.length > 0 ? ` (${list.length})` : ''}
        </span>
        <button type="button" onClick={() => setEditing({ index: null })} className="btn-table">
          + {t('stacks.firewall.add_rule')}
        </button>
      </div>

      {list.length === 0 ? (
        <p className="text-[11px] text-portal-text3 italic">{t('stacks.firewall.no_rules')}</p>
      ) : (
        <div className="rounded-md border border-portal-border overflow-hidden">
          {list.map((r, i) => (
            <div
              key={i}
              className={`flex items-center gap-2 px-2 py-1.5 text-xs ${i > 0 ? 'border-t border-portal-border/60' : ''} ${r.enable === false ? 'opacity-50' : ''}`}
            >
              <span className="text-portal-text3 font-mono shrink-0">{i + 1}.</span>
              <span className="font-mono text-portal-text truncate flex-1" title={ruleSummary(r)}>{ruleSummary(r)}</span>
              {r.enable === false && <span className="text-[10px] text-portal-text3 shrink-0">{t('stacks.firewall.disabled')}</span>}
              <div className="flex items-center gap-1 shrink-0">
                <button type="button" onClick={() => move(i, i - 1)} disabled={i === 0} className="btn-table disabled:opacity-30" aria-label={t('stacks.form.move_up')} title={t('stacks.form.move_up')}>↑</button>
                <button type="button" onClick={() => move(i, i + 1)} disabled={i === list.length - 1} className="btn-table disabled:opacity-30" aria-label={t('stacks.form.move_down')} title={t('stacks.form.move_down')}>↓</button>
                <button type="button" onClick={() => setEditing({ index: i })} className="btn-table" aria-label={t('common.edit')}>{t('common.edit')}</button>
                <button type="button" onClick={() => remove(i)} className="btn-table-danger" aria-label={t('stacks.firewall.remove_rule')}>{t('common.remove')}</button>
              </div>
            </div>
          ))}
        </div>
      )}

      {editing && (
        <StackFirewallRuleModal
          t={t}
          rule={editing.index == null ? null : list[editing.index]}
          refs={refs}
          macros={macros}
          securityGroupNames={securityGroupNames}
          withGroup={withGroup}
          onSave={save}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  )
}
