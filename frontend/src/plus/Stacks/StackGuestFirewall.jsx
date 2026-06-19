// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-91: Gast-Firewall-Sektion einer VM-/LXC-Karte (AC-MODEL-2, AC-ENABLE).
// Bearbeitet `resource.firewall = { enabled, policy_in, policy_out, rules[] }`.
//  - `enabled` setzt beim Deploy das NIC-`firewall=1`-Flag + die Gast-FW-Option
//    `enable=1` (sonst greifen die Regeln nicht).
//  - Sind Regeln/Policies definiert, aber `enabled` aus → Warnung (AC-ENABLE-2),
//    blockiert das Speichern aber nicht.
//  - Ein vollständig leerer Block wird als `undefined` zurückgemeldet → reine
//    VM/LXC-Stacks bleiben byte-genau (AC-MODEL-6).
import StackFirewallRuleList from './StackFirewallRuleList'

const inputCls =
  'w-full px-2 py-1.5 text-sm rounded-md border border-portal-border bg-portal-bg2 text-portal-text focus:outline-none focus:ring-1 focus:ring-portal-accent'

const POLICIES = ['ACCEPT', 'DROP', 'REJECT']

// Ein Firewall-Block ist „leer" (→ entfernen) wenn nichts aktiviert/definiert ist.
function isEmpty(fw) {
  return !fw.enabled && !fw.policy_in && !fw.policy_out && (!fw.rules || fw.rules.length === 0)
}

export default function StackGuestFirewall({ t, firewall, onChange, refs = [], macros = [], securityGroupNames = [] }) {
  const fw = firewall || {}
  const hasRulesOrPolicy = (fw.rules && fw.rules.length > 0) || fw.policy_in || fw.policy_out
  // AC-ENABLE-2: Regeln/Policies ohne Aktivierung → Warnung.
  const inertWarning = hasRulesOrPolicy && !fw.enabled

  const set = (key, val) => {
    const next = { ...fw, [key]: val }
    onChange(isEmpty(next) ? undefined : next)
  }
  const setRules = (rules) => set('rules', rules)

  return (
    <div className="space-y-3 pt-1">
      <label className="flex items-center gap-2 text-xs text-portal-text2">
        <input
          type="checkbox"
          checked={fw.enabled === true}
          onChange={(e) => set('enabled', e.target.checked)}
          className="accent-[var(--accent)]"
        />
        <span className="font-medium">{t('stacks.firewall.enabled')}</span>
      </label>
      <p className="text-[10px] text-portal-text3 -mt-1 ml-6">{t('stacks.firewall.enabled_hint')}</p>

      {inertWarning && (
        <p className="text-[11px] text-portal-warn ml-6">⚠ {t('stacks.firewall.inert_warn')}</p>
      )}

      <div className="grid grid-cols-2 gap-3">
        <label className="flex flex-col gap-1 text-xs">
          <span className="text-portal-text2 font-medium">{t('stacks.firewall.policy_in')}</span>
          <select className={inputCls} value={fw.policy_in ?? ''} onChange={(e) => set('policy_in', e.target.value || undefined)}>
            <option value="">{t('stacks.firewall.policy_default')}</option>
            {POLICIES.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs">
          <span className="text-portal-text2 font-medium">{t('stacks.firewall.policy_out')}</span>
          <select className={inputCls} value={fw.policy_out ?? ''} onChange={(e) => set('policy_out', e.target.value || undefined)}>
            <option value="">{t('stacks.firewall.policy_default')}</option>
            {POLICIES.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
        </label>
      </div>
      <p className="text-[10px] text-portal-text3 -mt-1">{t('stacks.firewall.policy_hint')}</p>

      <StackFirewallRuleList
        t={t}
        rules={fw.rules}
        onChange={setRules}
        refs={refs}
        macros={macros}
        securityGroupNames={securityGroupNames}
        withGroup
      />
    </div>
  )
}
