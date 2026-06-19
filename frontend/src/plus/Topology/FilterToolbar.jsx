// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-75: Filter-Toolbar mit View-Toggle, Status/Typ/Stack-Filter, Suche,
// Refresh (AC-TAB-4/AC-VIEW-1/AC-TAB-10).
import { useTranslation } from 'react-i18next'

const selectCls =
  'h-7 rounded-md border border-gray-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-2 text-xs text-gray-700 dark:text-zinc-200 focus:outline-none focus:border-portal-accent'

export default function FilterToolbar({ view, onViewChange, filters, onFiltersChange, stacks = [], onRefresh, refreshing, showDependencies = false }) {
  const { t } = useTranslation()
  const set = (patch) => onFiltersChange({ ...filters, ...patch })
  const viewBtn = (v, label) => (
    <button
      type="button"
      onClick={() => onViewChange(v)}
      className={`px-2.5 py-1 transition-colors ${view === v ? 'bg-[var(--accent)] text-white' : 'bg-white dark:bg-zinc-900 text-gray-600 dark:text-zinc-300 hover:bg-gray-50 dark:hover:bg-zinc-800'}`}
    >
      {label}
    </button>
  )

  return (
    <div className="flex flex-wrap items-center gap-2 px-3 py-2 border-b border-gray-200 dark:border-zinc-700 bg-white dark:bg-zinc-900">
      {/* View-Toggle Compute / Netzwerk / Board / Abhängigkeiten */}
      <div className="inline-flex rounded-md overflow-hidden border border-gray-300 dark:border-zinc-700 text-xs">
        {viewBtn('compute', t('topology.view.compute'))}
        {viewBtn('network', t('topology.view.network'))}
        {viewBtn('board', t('topology.view.board'))}
        {showDependencies && viewBtn('dependencies', t('topology.view.dependencies'))}
      </div>

      <select className={selectCls} value={filters.status} onChange={(e) => set({ status: e.target.value })} aria-label={t('topology.filter.status')}>
        <option value="all">{t('topology.filter.status_all')}</option>
        <option value="running">{t('topology.status.running')}</option>
        <option value="stopped">{t('topology.status.stopped')}</option>
      </select>

      <select className={selectCls} value={filters.type} onChange={(e) => set({ type: e.target.value })} aria-label={t('topology.filter.type')}>
        <option value="all">{t('topology.filter.type_all')}</option>
        <option value="vm">VM</option>
        <option value="lxc">LXC</option>
      </select>

      <select className={selectCls} value={filters.stack} onChange={(e) => set({ stack: e.target.value })} aria-label={t('topology.filter.stack')}>
        <option value="all">{t('topology.filter.stack_all')}</option>
        <option value="managed">{t('topology.filter.stack_managed')}</option>
        <option value="free">{t('topology.filter.stack_free')}</option>
        {stacks.map((s) => (
          <option key={s} value={s}>{s}</option>
        ))}
      </select>

      <input
        type="text"
        value={filters.q}
        onChange={(e) => set({ q: e.target.value })}
        placeholder={t('topology.filter.search_ph')}
        className={`${selectCls} w-40`}
        aria-label={t('topology.filter.search')}
      />

      <div className="ml-auto">
        <button type="button" onClick={onRefresh} disabled={refreshing} className="btn-secondary text-xs flex items-center gap-1" title={t('topology.refresh')}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className={`w-3.5 h-3.5 ${refreshing ? 'animate-spin' : ''}`}>
            <path d="M21 12a9 9 0 1 1-2.64-6.36M21 3v6h-6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          {t('topology.refresh')}
        </button>
      </div>
    </div>
  )
}
