// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-75: Reine Helfer für die Topologie (Filter, Ressourcen, Formatierung).
// Bewusst frei von React/dagre → unit-testbar.

export const DEFAULT_FILTERS = { status: 'all', type: 'all', stack: 'all', q: '' }

/**
 * Wendet die Toolbar-Filter (Status/Typ/Stack/Suche) clientseitig auf einen
 * Gast (vm|lxc) an. Backend liefert bereits RBAC-gefiltert (AC-RBAC-4); dieser
 * Filter ist rein kosmetisch und reduziert die Knotenmenge.
 */
export function guestMatchesFilters(guest, filters) {
  const f = filters || DEFAULT_FILTERS
  if (f.status === 'running' && guest.status !== 'running') return false
  if (f.status === 'stopped' && guest.status === 'running') return false
  if (f.type !== 'all' && guest.type !== f.type) return false
  if (f.stack === 'managed' && !guest.managed_by_stack) return false
  if (f.stack === 'free' && guest.managed_by_stack) return false
  if (f.stack !== 'all' && f.stack !== 'managed' && f.stack !== 'free') {
    // Konkreter Stack-Name aus dem Dropdown
    if (guest.managed_by_stack !== f.stack) return false
  }
  if (f.q) {
    const q = f.q.trim().toLowerCase()
    if (q) {
      const hay = `${guest.label || ''} ${guest.vmid ?? ''}`.toLowerCase()
      if (!hay.includes(q)) return false
    }
  }
  return true
}

/** Alle sichtbaren Gäste über alle Installationen nach Filtern. */
export function filterGuests(installations, filters) {
  const out = []
  for (const inst of installations || []) {
    for (const g of inst.guests || []) {
      if (guestMatchesFilters(g, filters)) out.push(g)
    }
  }
  return out
}

/** true wenn mindestens ein Filter vom Default abweicht (für Empty-State-CTA). */
export function hasActiveFilters(filters) {
  const f = filters || DEFAULT_FILTERS
  return f.status !== 'all' || f.type !== 'all' || f.stack !== 'all' || !!(f.q && f.q.trim())
}

// ── Ressourcen-Auslastung ─────────────────────────────────────────────────────

/** Schwellwert-Klassifizierung für Mini-Balken (AC-RES-4). */
export function resourceLevel(pct) {
  if (pct == null || Number.isNaN(pct)) return 'na'
  if (pct > 85) return 'danger'
  if (pct >= 70) return 'warn'
  return 'success'
}

/** Tailwind-Klasse für einen Ressourcen-Balken (portal-* Tokens, kein Roh-Tailwind). */
export function levelBarClass(level) {
  switch (level) {
    case 'danger': return 'bg-portal-danger'
    case 'warn': return 'bg-portal-warn'
    case 'success': return 'bg-portal-success'
    default: return 'bg-gray-300 dark:bg-zinc-600'
  }
}

/**
 * CPU-Auslastung in % aus dem Gast-Datensatz. `cpu` ist eine Fraktion 0–1
 * (Proxmox cluster/resources). Gestoppte VMs / fehlende Daten → null (N/A).
 */
export function cpuPct(guest) {
  if (!guest || guest.status !== 'running') return null
  if (guest.cpu == null) return null
  return Math.min(100, Math.max(0, guest.cpu * 100))
}

/** RAM-Auslastung in % (mem/maxmem). */
export function memPct(guest) {
  if (!guest || !guest.maxmem || guest.mem == null) return null
  if (guest.status !== 'running') return null
  return Math.min(100, Math.max(0, (guest.mem / guest.maxmem) * 100))
}

/** Disk-Auslastung in % (disk/maxdisk). QEMU liefert oft disk=0 → N/A (AC-RES-6/EC-3). */
export function diskPct(guest) {
  if (!guest || !guest.maxdisk || !guest.disk) return null
  return Math.min(100, Math.max(0, (guest.disk / guest.maxdisk) * 100))
}

// ── Formatierung ──────────────────────────────────────────────────────────────

export function formatBytes(bytes) {
  const n = Number(bytes)
  if (!n || n <= 0) return '–'
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB']
  let i = 0
  let v = n
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++ }
  return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${units[i]}`
}

// ── Netz-Sicht: nur Knoten/Kanten zu sichtbaren Gästen ────────────────────────

/**
 * Beschränkt die Konnektivitäts-Kanten auf die Menge sichtbarer Gast-IDs.
 * Backend liefert nur sichtbare Gäste (RBAC), der Client-Filter verkleinert
 * zusätzlich nach Toolbar-Filtern.
 * @param {Array} edgesConn  [{guest_id, network_id}]
 * @param {Set<string>} visibleGuestIds
 */
export function visibleConnEdges(edgesConn, visibleGuestIds) {
  return (edgesConn || []).filter((e) => visibleGuestIds.has(e.guest_id))
}
