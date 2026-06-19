// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-91: eine stack-eigene Security-Group-Karte (AC-MODEL-4). Ein benannter,
// wiederverwendbarer Regelsatz auf Stack-Ebene; beim Deploy als Cluster-SG
// `p3s<id>-<name>` angelegt, beim Destroy mitgelöscht. Gäste referenzieren sie
// über eine `group`-Regel mit `action = <lokaler Name>` (AC-SG-2). Hooksfrei,
// `t` als Prop (Muster NetworkCard).
import StackFirewallRuleList from './StackFirewallRuleList'

const inputCls =
  'w-full px-2 py-1.5 text-sm rounded-md border border-portal-border bg-portal-bg2 text-portal-text focus:outline-none focus:ring-1 focus:ring-portal-accent'

// Lokaler SG-Name wie Backend `_SG_NAME_RE` + ≤10 Zeichen (Präfix-Längen-Cap).
const SG_NAME_RE = /^[A-Za-z][A-Za-z0-9_-]*$/

export default function StackSecurityGroupCard({ t, group, index, refs = [], macros = [], onChange, onRemove }) {
  const g = group || {}
  const set = (key, val) => onChange(index, { ...g, [key]: val })
  const nameInvalid = g.name && (!SG_NAME_RE.test(g.name) || g.name.length > 10)

  return (
    <div className="border border-portal-border rounded-lg bg-portal-bg2 p-3 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <h4 className="text-sm font-semibold text-gray-900 dark:text-zinc-100 flex items-center gap-2 min-w-0">
          <span className="text-portal-text3">#{index + 1}</span>
          <span className="shrink-0">{t('stacks.security_groups.card_title')}</span>
          {g.name ? <span className="text-portal-text2 font-normal truncate font-mono">— {g.name}</span> : null}
        </h4>
        <button
          type="button"
          onClick={() => onRemove(index)}
          className="btn-table-danger shrink-0"
          aria-label={t('stacks.security_groups.remove')}
        >{t('common.remove')}</button>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <label className="flex flex-col gap-1 text-xs">
          <span className="text-portal-text2 font-medium">{t('stacks.security_groups.field.name')} *</span>
          <input
            className={inputCls}
            value={g.name ?? ''}
            placeholder="web-egress"
            maxLength={10}
            onChange={(e) => set('name', e.target.value)}
          />
          {nameInvalid && (
            <span className="text-[11px] text-portal-danger">{t('stacks.security_groups.name_hint')}</span>
          )}
        </label>
        <label className="flex flex-col gap-1 text-xs">
          <span className="text-portal-text2 font-medium">{t('stacks.security_groups.field.comment')}</span>
          <input
            className={inputCls}
            value={g.comment ?? ''}
            maxLength={255}
            onChange={(e) => set('comment', e.target.value || undefined)}
          />
        </label>
      </div>

      {/* SG-eigene Regeln (in/out; keine group-Regel innerhalb einer SG). */}
      <StackFirewallRuleList
        t={t}
        rules={g.rules}
        onChange={(rules) => set('rules', rules)}
        refs={refs}
        macros={macros}
        withGroup={false}
      />
    </div>
  )
}
