// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-76 Phase 1: Vorschau-Modal — zeigt aufgelöste VMs (count → Suffix) + Issues (AC-UI-7).
import { useTranslation } from 'react-i18next'

export default function StackPreviewModal({ preview, loading, error, onClose }) {
  const { t } = useTranslation()
  const resources = preview?.resources ?? []
  const errors = preview?.errors ?? []
  const warnings = preview?.warnings ?? []

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-700 rounded-lg w-full max-w-3xl mx-4 shadow-xl flex flex-col max-h-[85vh]">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200 dark:border-zinc-700 shrink-0">
          <h2 className="text-sm font-semibold text-gray-900 dark:text-zinc-100">{t('stacks.preview.title')}</h2>
          <button onClick={onClose} className="btn-ghost text-gray-400 hover:text-gray-600" aria-label={t('common.close')}>✕</button>
        </div>

        <div className="overflow-auto flex-1 p-5 space-y-4">
          {loading && <p className="text-sm text-portal-text2">{t('common.loading')}</p>}
          {error && <p className="text-sm text-portal-danger">{error}</p>}

          {!loading && !error && (
            <>
              {errors.length > 0 && (
                <div className="rounded-md border border-portal-danger/40 bg-portal-danger/10 p-3 space-y-1">
                  <p className="text-xs font-semibold text-portal-danger">{t('stacks.validation.errors')}</p>
                  <ul className="list-disc pl-5 text-xs text-portal-danger space-y-0.5">
                    {errors.map((e, i) => <li key={i}>{e}</li>)}
                  </ul>
                </div>
              )}
              {warnings.length > 0 && (
                <div className="rounded-md border border-portal-warn/40 bg-portal-warn/10 p-3 space-y-1">
                  <p className="text-xs font-semibold text-portal-warn">{t('stacks.validation.warnings')}</p>
                  <ul className="list-disc pl-5 text-xs text-portal-warn space-y-0.5">
                    {warnings.map((w, i) => <li key={i}>{w}</li>)}
                  </ul>
                </div>
              )}

              <div>
                <p className="text-xs text-portal-text2 mb-2">
                  {t('stacks.preview.resource_count', { count: preview?.resource_count ?? resources.length })}
                </p>
                {resources.length === 0 ? (
                  <p className="text-sm text-portal-text3 italic">{t('stacks.preview.empty')}</p>
                ) : (
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-portal-text3 border-b border-portal-border text-left">
                        <th className="py-1.5 pr-3 font-medium">{t('stacks.preview.col_name')}</th>
                        <th className="py-1.5 pr-3 font-medium">{t('stacks.preview.col_node')}</th>
                        <th className="py-1.5 pr-3 font-medium">{t('stacks.preview.col_template')}</th>
                        <th className="py-1.5 pr-3 font-medium">{t('stacks.preview.col_cores')}</th>
                        <th className="py-1.5 pr-3 font-medium">{t('stacks.preview.col_memory')}</th>
                        <th className="py-1.5 pr-3 font-medium">{t('stacks.preview.col_disk')}</th>
                        <th className="py-1.5 font-medium">{t('stacks.preview.col_pool')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {resources.map((r, i) => (
                        <tr key={i} className="border-b border-portal-border/50 text-portal-text">
                          <td className="py-1.5 pr-3 font-mono">{r.name}</td>
                          <td className="py-1.5 pr-3">{r.node}</td>
                          <td className="py-1.5 pr-3">{r.template}</td>
                          <td className="py-1.5 pr-3">{r.cores}</td>
                          <td className="py-1.5 pr-3">{r.memory} MB</td>
                          <td className="py-1.5 pr-3">{r.disk} GB</td>
                          <td className="py-1.5">{r.pool || '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </>
          )}
        </div>

        <div className="flex justify-end px-5 py-4 border-t border-gray-200 dark:border-zinc-700 shrink-0">
          <button type="button" onClick={onClose} className="btn-secondary">{t('common.close')}</button>
        </div>
      </div>
    </div>
  )
}
