// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-42 Phase 2: geteilte Anzeige-Helfer (Netz-/Pool-Labels + Status-Badge).

/** „vmbr0 (pve · VLAN 10)" bzw. „guests (cluster-weit)" – Netz-Identität lesbar. */
export function networkLabel(o, t) {
  if (!o) return ''
  const parts = []
  if (o.node) parts.push(o.node)
  else parts.push(t('ipam.pool.cluster_wide'))
  if (o.vlan_tag != null) parts.push(`VLAN ${o.vlan_tag}`)
  return `${o.network_name} (${parts.join(' · ')})`
}

/** Pool-Kurzlabel für Dropdowns/Zeilen: „vmbr0 · 192.168.2.0/24". */
export function poolLabel(pool, t) {
  if (!pool) return ''
  return `${networkLabel(pool, t)} · ${pool.cidr}`
}

const STATUS_CLS = {
  confirmed: 'bg-portal-success/15 text-portal-success',
  pending: 'bg-portal-warn/15 text-portal-warn',
  orphaned: 'bg-portal-danger/15 text-portal-danger',
}

export function StatusBadge({ status, t }) {
  const cls = STATUS_CLS[status] || 'bg-portal-bg3 text-portal-text2'
  return (
    <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium ${cls}`}>
      {t(`ipam.alloc.status_${status}`)}
    </span>
  )
}
