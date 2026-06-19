// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-96: „Verwaiste Abhängigkeiten"-Tab in System Settings (AC-ORPHAN-3).
// Verwaiste Kanten (deren Quell- oder Ziel-VM verschwunden ist) werden hier
// gelistet und können einzeln/gebündelt gelöscht werden. Gated durch
// manage_dependencies (kein separates Orphan-Recht).
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { formatApiError } from '../../api/errors'
import ConfirmModal from '../../components/common/ConfirmModal'
import { useOrphanDependencies, useDeleteOrphanDependencies } from './hooks'

function vmLabel(name, vmid, installation) {
  const base = name || `#${vmid}`
  return installation ? `${base} (${vmid}) · ${installation}` : `${base} (${vmid})`
}

export default function OrphanDependenciesTab() {
  const { t } = useTranslation()
  const { data, isLoading, error } = useOrphanDependencies()
  const deleteMut = useDeleteOrphanDependencies()
  const [confirm, setConfirm] = useState(null) // { id } | 'all'

  const orphans = data ?? []

  const purge = async (ids) => {
    await deleteMut.mutateAsync(ids)
  }

  return (
    <div className="space-y-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-gray-900 dark:text-zinc-100">{t('dependencies.orphans.title')}</h3>
          <p className="text-xs text-portal-text2 mt-0.5">{t('dependencies.orphans.subtitle')}</p>
        </div>
        {orphans.length > 0 && (
          <button type="button" onClick={() => setConfirm('all')} className="btn-table-danger shrink-0">
            {t('dependencies.orphans.purge_all')}
          </button>
        )}
      </div>

      {isLoading ? (
        <p className="text-sm text-portal-text2">{t('common.loading')}</p>
      ) : error ? (
        <p className="text-sm text-portal-danger">{formatApiError(error, t('common.error_generic'))}</p>
      ) : orphans.length === 0 ? (
        <p className="text-sm text-portal-text3 italic">{t('dependencies.orphans.empty')}</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-portal-text3 border-b border-portal-border text-left">
              <th className="px-3 py-2 font-medium">{t('dependencies.orphans.col_source')}</th>
              <th className="px-3 py-2 font-medium">{t('dependencies.orphans.col_target')}</th>
              <th className="px-3 py-2 font-medium">{t('dependencies.orphans.col_label')}</th>
              <th className="px-3 py-2 font-medium">{t('dependencies.orphans.col_orphaned_at')}</th>
              <th className="px-3 py-2 font-medium text-right">{t('dependencies.orphans.col_actions')}</th>
            </tr>
          </thead>
          <tbody>
            {orphans.map((o) => (
              <tr key={o.id} className="border-b border-portal-border/50">
                <td className="px-3 py-2 text-portal-text">{vmLabel(o.source_name, o.source_vmid, o.source_installation)}</td>
                <td className="px-3 py-2 text-portal-text">{vmLabel(o.target_name, o.target_vmid, o.target_installation)}</td>
                <td className="px-3 py-2 text-portal-text2 text-xs italic">{o.dep_label || '—'}</td>
                <td className="px-3 py-2 text-portal-text3 text-xs tabular-nums">{(o.stale_at || '').replace('T', ' ').slice(0, 16) || '—'}</td>
                <td className="px-3 py-2">
                  <div className="flex justify-end">
                    <button type="button" onClick={() => setConfirm({ id: o.id })} className="btn-table-danger">
                      {t('common.delete')}
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {confirm && (
        <ConfirmModal
          title={t('dependencies.orphans.purge_confirm_title')}
          body={confirm === 'all'
            ? t('dependencies.orphans.purge_all_confirm_body', { count: orphans.length })
            : t('dependencies.orphans.purge_confirm_body')}
          confirmLabel={t('common.delete')}
          variant="danger"
          onConfirm={() => purge(confirm === 'all' ? [] : [confirm.id])}
          onClose={() => setConfirm(null)}
        />
      )}
    </div>
  )
}
