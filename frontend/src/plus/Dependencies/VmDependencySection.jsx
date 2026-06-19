// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-96: „Abhängigkeiten"-Sektion auf der VM-Detailseite (AC-DECLARE-1/3/4).
// Zeigt beide Richtungen — „hängt ab von …" und „davon hängen ab …" — und
// erlaubt (mit manage_dependencies) das Anlegen/Entfernen/Label-Bearbeiten.
import { useState, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { formatApiError } from '../../api/errors'
import {
  useVmDependencies,
  useVisibleVms,
  useCreateDependency,
  useDeleteDependency,
  useUpdateDependencyLabel,
} from './hooks'

const inputCls =
  'h-8 rounded-md border border-gray-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-2 text-xs text-gray-700 dark:text-zinc-200 focus:outline-none focus:border-portal-accent'

function StaleBadge() {
  const { t } = useTranslation()
  return (
    <span className="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium bg-portal-warn/15 text-portal-warn">
      {t('dependencies.stale_badge')}
    </span>
  )
}

/** Zeile in einer der beiden Richtungs-Listen. `peer` = die jeweils andere VM. */
function DepRow({ dep, peer, canManage, onRemove }) {
  const { t } = useTranslation()
  const [editing, setEditing] = useState(false)
  const [label, setLabel] = useState(dep.dep_label || '')
  const updateMut = useUpdateDependencyLabel()
  const [err, setErr] = useState('')

  const saveLabel = async () => {
    setErr('')
    try {
      await updateMut.mutateAsync({ id: dep.id, depLabel: label.trim() || null })
      setEditing(false)
    } catch (e) {
      setErr(formatApiError(e, t('common.error_generic')))
    }
  }

  return (
    <li className="flex items-center gap-2 py-1.5 border-b border-gray-100 dark:border-zinc-800 last:border-0">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="text-xs font-medium text-gray-900 dark:text-zinc-100 truncate" title={peer.name || String(peer.vmid)}>
            {peer.name || `#${peer.vmid}`}
          </span>
          <span className="text-[10px] text-gray-400 dark:text-zinc-500 tabular-nums">· {peer.vmid}</span>
          {peer.installation && (
            <span className="text-[10px] text-gray-400 dark:text-zinc-500 truncate">· {peer.installation}</span>
          )}
          {dep.stale && <StaleBadge />}
        </div>
        {editing ? (
          <div className="mt-1 flex items-center gap-1.5">
            <input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder={t('dependencies.label_ph')}
              maxLength={200}
              className={`${inputCls} flex-1`}
            />
            <button type="button" onClick={saveLabel} disabled={updateMut.isPending} className="btn-table">
              {t('common.save')}
            </button>
            <button type="button" onClick={() => { setEditing(false); setLabel(dep.dep_label || '') }} className="btn-table">
              {t('common.cancel')}
            </button>
          </div>
        ) : dep.dep_label ? (
          <div className="mt-0.5 text-[11px] text-portal-text2 italic truncate" title={dep.dep_label}>{dep.dep_label}</div>
        ) : null}
        {err && <p className="mt-0.5 text-[11px] text-portal-danger">{err}</p>}
      </div>
      {canManage && (
        <div className="flex items-center gap-1.5 shrink-0">
          {!editing && (
            <button type="button" onClick={() => setEditing(true)} className="btn-table" title={t('dependencies.edit_label')}>
              {t('dependencies.label_btn')}
            </button>
          )}
          <button type="button" onClick={() => onRemove(dep)} className="btn-table-danger">
            {t('common.remove')}
          </button>
        </div>
      )}
    </li>
  )
}

export default function VmDependencySection({ portalNodeId, vmid, node, vmName, canManage }) {
  const { t } = useTranslation()
  const numericVmid = Number(vmid)
  const { data, isLoading, isError, error } = useVmDependencies({ vmid: numericVmid, nodeId: portalNodeId, node })
  const vmsQuery = useVisibleVms({ enabled: canManage })
  const createMut = useCreateDependency()
  const deleteMut = useDeleteDependency()

  const [adding, setAdding] = useState(false)
  const [targetKey, setTargetKey] = useState('')
  const [newLabel, setNewLabel] = useState('')
  const [formErr, setFormErr] = useState('')

  const dependsOn = data?.depends_on || []
  const dependents = data?.dependents || []

  // Ziel-Auswahl: alle sichtbaren VMs außer der aktuellen, nur solche mit
  // portal_node_id (installationsübergreifend, aber identifizierbar) und ohne
  // bereits bestehende „hängt ab von"-Kante (verhindert Duplikat-422/409).
  const existingTargets = useMemo(
    () => new Set((data?.depends_on || []).map((d) => `${d.target_node_id}:${d.target_vmid}`)),
    [data],
  )
  const targetOptions = useMemo(() => {
    const rows = vmsQuery.data || []
    return rows
      .filter((v) => v.portal_node_id != null)
      .filter((v) => !(v.portal_node_id === portalNodeId && v.vmid === numericVmid))
      .filter((v) => !existingTargets.has(`${v.portal_node_id}:${v.vmid}`))
      .map((v) => ({
        key: `${v.portal_node_id}:${v.vmid}`,
        portal_node_id: v.portal_node_id,
        vmid: v.vmid,
        label: `${v.name || `#${v.vmid}`} (${v.vmid})${v.portal_node_name ? ` · ${v.portal_node_name}` : ''}`,
      }))
      .sort((a, b) => a.label.localeCompare(b.label))
  }, [vmsQuery.data, portalNodeId, numericVmid, existingTargets])

  const submitAdd = async () => {
    setFormErr('')
    if (!targetKey) return
    const [tNode, tVmid] = targetKey.split(':').map(Number)
    if (portalNodeId == null) {
      setFormErr(t('dependencies.no_node_id'))
      return
    }
    try {
      await createMut.mutateAsync({
        source_node_id: portalNodeId,
        source_vmid: numericVmid,
        target_node_id: tNode,
        target_vmid: tVmid,
        dep_label: newLabel.trim() || null,
      })
      setAdding(false)
      setTargetKey('')
      setNewLabel('')
    } catch (e) {
      const status = e.response?.status
      if (status === 409) setFormErr(t('dependencies.err_duplicate'))
      else if (status === 422) setFormErr(t('dependencies.err_invalid'))
      else setFormErr(formatApiError(e, t('common.error_generic')))
    }
  }

  const remove = async (dep) => {
    try {
      await deleteMut.mutateAsync(dep.id)
    } catch { /* invalidate zieht den Stand nach; Fehler hier nicht-blockierend */ }
  }

  return (
    <div className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-700 rounded-lg p-4">
      <div className="flex items-center justify-between gap-2 mb-3">
        <h3 className="text-sm font-semibold text-gray-900 dark:text-zinc-100">{t('dependencies.section_title')}</h3>
        {canManage && !adding && (
          <button
            type="button"
            onClick={() => setAdding(true)}
            disabled={portalNodeId == null}
            className="btn-table"
            title={portalNodeId == null ? t('dependencies.no_node_id') : undefined}
          >
            + {t('dependencies.add_btn')}
          </button>
        )}
      </div>

      {/* Add-Form */}
      {canManage && adding && (
        <div className="mb-3 rounded-md border border-portal-accent/30 bg-portal-accent/5 p-3 space-y-2">
          <p className="text-[11px] text-portal-text2">{t('dependencies.add_hint', { vm: vmName || `#${numericVmid}` })}</p>
          <div className="flex flex-wrap items-center gap-2">
            <select value={targetKey} onChange={(e) => setTargetKey(e.target.value)} className={`${inputCls} min-w-[14rem]`}>
              <option value="">{vmsQuery.isLoading ? t('common.loading') : t('dependencies.select_target')}</option>
              {targetOptions.map((o) => (
                <option key={o.key} value={o.key}>{o.label}</option>
              ))}
            </select>
            <input
              value={newLabel}
              onChange={(e) => setNewLabel(e.target.value)}
              placeholder={t('dependencies.label_ph')}
              maxLength={200}
              className={`${inputCls} flex-1 min-w-[8rem]`}
            />
          </div>
          {formErr && <p className="text-[11px] text-portal-danger">{formErr}</p>}
          <div className="flex items-center gap-2">
            <button type="button" onClick={submitAdd} disabled={!targetKey || createMut.isPending} className="btn-primary text-xs">
              {createMut.isPending ? '…' : t('dependencies.add_btn')}
            </button>
            <button type="button" onClick={() => { setAdding(false); setTargetKey(''); setNewLabel(''); setFormErr('') }} className="btn-secondary text-xs">
              {t('common.cancel')}
            </button>
          </div>
        </div>
      )}

      {isLoading ? (
        <p className="text-xs text-gray-400 dark:text-zinc-500">{t('common.loading')}</p>
      ) : isError ? (
        <p className="text-xs text-portal-danger">{formatApiError(error, t('common.error_generic'))}</p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-2">
          {/* hängt ab von … (diese VM ist die Quelle; peer = Ziel) */}
          <div>
            <h4 className="text-[11px] font-semibold uppercase tracking-wide text-gray-500 dark:text-zinc-400 mb-1">
              {t('dependencies.depends_on')}
            </h4>
            {dependsOn.length === 0 ? (
              <p className="text-xs text-gray-400 dark:text-zinc-500 italic">{t('dependencies.none')}</p>
            ) : (
              <ul>
                {dependsOn.map((d) => (
                  <DepRow
                    key={d.id}
                    dep={d}
                    peer={{ vmid: d.target_vmid, name: d.target_name, installation: d.target_installation }}
                    canManage={canManage}
                    onRemove={remove}
                  />
                ))}
              </ul>
            )}
          </div>

          {/* davon hängen ab … (diese VM ist das Ziel; peer = Quelle) */}
          <div>
            <h4 className="text-[11px] font-semibold uppercase tracking-wide text-gray-500 dark:text-zinc-400 mb-1">
              {t('dependencies.dependents')}
            </h4>
            {dependents.length === 0 ? (
              <p className="text-xs text-gray-400 dark:text-zinc-500 italic">{t('dependencies.none')}</p>
            ) : (
              <ul>
                {dependents.map((d) => (
                  <DepRow
                    key={d.id}
                    dep={d}
                    peer={{ vmid: d.source_vmid, name: d.source_name, installation: d.source_installation }}
                    canManage={canManage}
                    onRemove={remove}
                  />
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
