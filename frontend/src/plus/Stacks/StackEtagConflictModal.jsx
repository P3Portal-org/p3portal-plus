// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-76 Phase 1: ETag-Konflikt-Modal — drei Spalten base/your/current (AC-UI-12, AC-CONC-3).
import { useTranslation } from 'react-i18next'

function Column({ title, accent, text }) {
  return (
    <div className="flex flex-col min-w-0 flex-1">
      <div className={`text-[11px] font-semibold uppercase tracking-wide px-2 py-1 ${accent}`}>{title}</div>
      <pre className="flex-1 overflow-auto text-[11px] font-mono whitespace-pre-wrap break-all p-2 bg-portal-bg2 border border-portal-border rounded-b-md max-h-[50vh]">
        {text || <span className="italic text-portal-text3">—</span>}
      </pre>
    </div>
  )
}

export default function StackEtagConflictModal({ conflict, onReload, onOverride, onClose }) {
  // conflict: { current_etag, current_yaml, your_yaml, base_yaml }
  const { t } = useTranslation()
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-700 rounded-lg w-full max-w-5xl mx-4 shadow-xl flex flex-col max-h-[88vh]">
        <div className="px-5 py-4 border-b border-gray-200 dark:border-zinc-700 shrink-0">
          <h2 className="text-sm font-semibold text-portal-danger">{t('stacks.etag_conflict.title')}</h2>
          <p className="text-xs text-portal-text2 mt-1">{t('stacks.etag_conflict.hint')}</p>
        </div>

        <div className="overflow-auto flex-1 p-5">
          <div className="flex gap-3">
            <Column title={t('stacks.etag_conflict.base')} accent="text-portal-text2 bg-portal-bg3 rounded-t-md" text={conflict?.base_yaml} />
            <Column title={t('stacks.etag_conflict.your')} accent="text-portal-warn bg-portal-warn/10 rounded-t-md" text={conflict?.your_yaml} />
            <Column title={t('stacks.etag_conflict.current')} accent="text-portal-success bg-portal-success/10 rounded-t-md" text={conflict?.current_yaml} />
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 px-5 py-4 border-t border-gray-200 dark:border-zinc-700 shrink-0">
          <button type="button" onClick={onClose} className="btn-secondary">{t('common.cancel')}</button>
          <button type="button" onClick={onReload} className="btn-secondary">{t('stacks.etag_conflict.reload_btn')}</button>
          <button type="button" onClick={() => onOverride(conflict.current_etag)} className="btn-danger">{t('stacks.etag_conflict.override_btn')}</button>
        </div>
      </div>
    </div>
  )
}
