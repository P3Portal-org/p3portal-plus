// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-92: Liste editor-verwalteter Definitionen (Marker-gefiltert) mit Neu /
// Bearbeiten / Löschen. Fremde ZIP/Git-Definitionen tauchen hier nicht auf.
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useDefinitions, useDeleteDefinition } from './hooks'
import ConfirmModal from '../../components/common/ConfirmModal'

export default function DefinitionList({ onNew, onEdit }) {
  const { t } = useTranslation()
  const { data: definitions, isLoading, error } = useDefinitions()
  const del = useDeleteDefinition()
  const [confirmDel, setConfirmDel] = useState(null)

  const list = Array.isArray(definitions) ? definitions : []

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs text-portal-text2">{t('packer_editor.list.intro')}</p>
        <button type="button" className="btn-primary text-xs" onClick={onNew}>
          + {t('packer_editor.list.new')}
        </button>
      </div>

      {isLoading && <p className="text-sm text-portal-text2">{t('common.loading')}</p>}
      {error && <p className="text-sm text-portal-danger">{t('common.error_generic')}</p>}

      {!isLoading && !error && list.length === 0 && (
        <div className="py-12 text-center">
          <p className="text-sm text-portal-text2">{t('packer_editor.list.empty')}</p>
        </div>
      )}

      {list.length > 0 && (
        <div className="rounded-lg border border-portal-border overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-portal-text2 border-b border-portal-border">
                <th className="px-3 py-2 font-medium">{t('packer_editor.list.col_name')}</th>
                <th className="px-3 py-2 font-medium">{t('packer_editor.list.col_id')}</th>
                <th className="px-3 py-2 font-medium">{t('packer_editor.list.col_source')}</th>
                <th className="px-3 py-2 font-medium">{t('packer_editor.list.col_role')}</th>
                <th className="px-3 py-2 font-medium text-right">{t('packer_editor.list.col_actions')}</th>
              </tr>
            </thead>
            <tbody>
              {list.map((d) => (
                <tr key={d.id} className="border-b border-portal-border last:border-0">
                  <td className="px-3 py-2 text-portal-text">{d.name}</td>
                  <td className="px-3 py-2 font-mono text-xs text-portal-text2">{d.id}</td>
                  <td className="px-3 py-2 text-xs text-portal-text2">
                    {d.source_type === 'proxmox-iso' ? t('packer_editor.source.type_iso') : t('packer_editor.source.type_clone')}
                  </td>
                  <td className="px-3 py-2 text-xs text-portal-text2">{d.required_role}</td>
                  <td className="px-3 py-2">
                    <div className="flex justify-end gap-1">
                      <button type="button" className="btn-table" onClick={() => onEdit(d.id)}>{t('common.edit')}</button>
                      <button type="button" className="btn-table-danger" onClick={() => setConfirmDel(d)}>{t('common.delete')}</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {confirmDel && (
        <ConfirmModal
          title={t('packer_editor.list.delete_title')}
          body={t('packer_editor.list.delete_message', { name: confirmDel.name })}
          confirmLabel={t('common.delete')}
          variant="danger"
          onConfirm={() => del.mutateAsync(confirmDel.id)}
          onClose={() => setConfirmDel(null)}
        />
      )}
    </div>
  )
}
