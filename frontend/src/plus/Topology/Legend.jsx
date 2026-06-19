// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-75: Kontextabhängige Legende unten links (AC-TAB-7).
import { useTranslation } from 'react-i18next'

function Dot({ cls }) {
  return <span className={`inline-block w-2.5 h-2.5 rounded-sm ${cls}`} />
}

export default function Legend({ view }) {
  const { t } = useTranslation()
  return (
    <div className="rounded-md border border-gray-200 dark:border-zinc-700 bg-white/90 dark:bg-zinc-900/90 backdrop-blur px-2.5 py-2 text-[10px] text-gray-600 dark:text-zinc-300 shadow-sm max-w-[220px]">
      <div className="font-semibold mb-1 text-gray-700 dark:text-zinc-200">{t('topology.legend.title')}</div>
      <div className="space-y-1">
        {view === 'dependencies' ? (
          <>
            <div className="flex items-center gap-1.5"><span className="inline-block w-4 h-0 border-t-2 border-portal-info" /> {t('topology.legend.dep_edge')}</div>
            <div className="flex items-center gap-1.5"><span className="inline-block w-4 h-0 border-t-2 border-dashed border-portal-text3" /> {t('topology.legend.dep_stale')}</div>
            <div className="mt-1 pt-1 border-t border-gray-100 dark:border-zinc-800 text-gray-400 dark:text-zinc-500">{t('topology.legend.dep_hint')}</div>
          </>
        ) : view === 'compute' ? (
          <>
            <div className="flex items-center gap-1.5"><Dot cls="bg-portal-success" /> {t('topology.legend.running')}</div>
            <div className="flex items-center gap-1.5"><Dot cls="bg-portal-danger" /> {t('topology.legend.stopped')}</div>
            <div className="flex items-center gap-1.5"><span className="inline-block w-2.5 h-2.5 rounded-sm border-2 border-portal-accent" /> {t('topology.legend.stack')}</div>
            <div className="flex items-center gap-1.5"><Dot cls="bg-portal-warn" /> {t('topology.legend.threshold')}</div>
          </>
        ) : (
          <>
            <div className="flex items-center gap-1.5"><span className="inline-block w-2.5 h-2.5 rounded-sm border-2 border-gray-300 dark:border-zinc-600" /> {t('topology.net.kind.node_bridge')}</div>
            <div className="flex items-center gap-1.5"><span className="inline-block w-2.5 h-2.5 rounded-sm border-2 border-portal-info" /> {t('topology.net.kind.sdn_vnet')}</div>
            <div className="flex items-center gap-1.5"><span className="inline-block w-2.5 h-2.5 rounded-sm border-2 border-portal-accent" /> {t('topology.net.kind.stack_bridge')}</div>
            <div className="flex items-center gap-1.5"><span className="inline-block w-2.5 h-2.5 rounded-sm border-2 border-dashed border-portal-warn" /> {t('topology.net.kind.unknown')}</div>
            <div className="mt-1 pt-1 border-t border-gray-100 dark:border-zinc-800 text-gray-400 dark:text-zinc-500">{t('topology.legend.hover_hint')}</div>
          </>
        )}
      </div>
    </div>
  )
}
