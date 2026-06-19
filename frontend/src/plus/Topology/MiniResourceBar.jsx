// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-75: Farbcodierter Mini-Ressourcen-Balken im VM/LXC-Knoten (AC-RES-*).
import { resourceLevel, levelBarClass } from './topologyHelpers'

/**
 * @param {string} label   Kürzel (CPU/RAM/Disk)
 * @param {number|null} pct  0–100, null = N/A (Balken grau, Text „N/A")
 * @param {string} tooltip exakte Werte für den title-Tooltip (AC-RES-5)
 */
export default function MiniResourceBar({ label, pct, tooltip, naLabel = 'N/A' }) {
  const isNa = pct == null || Number.isNaN(pct)
  const level = resourceLevel(isNa ? null : pct)
  const clamped = isNa ? 0 : Math.min(100, Math.max(0, pct))
  return (
    <div className="flex items-center gap-1" title={tooltip}>
      <span className="w-7 shrink-0 text-[9px] uppercase tracking-wide text-gray-400 dark:text-zinc-500">{label}</span>
      <div className="flex-1 h-1.5 rounded-sm bg-gray-200 dark:bg-zinc-700 overflow-hidden">
        {!isNa && (
          <div className={`h-full ${levelBarClass(level)}`} style={{ width: `${clamped}%` }} />
        )}
      </div>
      <span className="w-8 shrink-0 text-right text-[9px] tabular-nums text-gray-400 dark:text-zinc-500">
        {isNa ? naLabel : `${clamped.toFixed(0)}%`}
      </span>
    </div>
  )
}
