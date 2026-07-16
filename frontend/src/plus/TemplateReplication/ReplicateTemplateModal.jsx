// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-101: Replikations-Modal an einer VM-Template-Zeile der Image Factory.
// Lädt Preflight (Quell-Status + Ziel-Nodes samt Datastores), lässt Ziele +
// Storage wählen, zeigt eine Plan-Vorschau (shared → N→1) und startet die
// Replikation als Job → Navigation in den Live-Log (/events/:id).
import { useState, useEffect, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { preflightReplication, startReplication } from './api'
import { replicationErrMsg, buildPlan } from './replicationHelpers'
import { modalInputCls, formatBytes } from '../../components/vms/disks/diskHelpers'

function storageLabel(s, t) {
  const shared = s.shared ? ` · ${t('template_replication.shared_tag')}` : ''
  return `${s.name}${shared} (${formatBytes(s.avail)} ${t('template_replication.free')} / ${formatBytes(s.total)})`
}

export default function ReplicateTemplateModal({ tmpl, onClose }) {
  const { t } = useTranslation()
  const navigate = useNavigate()

  const [preflight, setPreflight] = useState(null)   // null = loading
  const [preflightErr, setPreflightErr] = useState('')
  const [mode, setMode] = useState('selected')       // 'selected' | 'all'
  const [selectedNodes, setSelectedNodes] = useState({})  // { node: true }
  const [perNodeMode, setPerNodeMode] = useState(false)   // Haken „pro Node abweichen"
  const [defaultStorage, setDefaultStorage] = useState('')
  const [perNode, setPerNode] = useState({})         // { node: { storage, newid } }
  const [removeSource, setRemoveSource] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let active = true
    setPreflight(null)
    setPreflightErr('')
    preflightReplication(tmpl.node, tmpl.vmid)
      .then((data) => { if (active) setPreflight(data) })
      .catch((err) => { if (active) { setPreflight(false); setPreflightErr(replicationErrMsg(err, t)) } })
    return () => { active = false }
  }, [tmpl.node, tmpl.vmid, t])

  const targets = useMemo(() => preflight?.targets ?? [], [preflight])

  // Aktive Ziel-Nodes je nach Modus.
  const activeNodes = useMemo(() => {
    if (!preflight || preflight.source_shared) return []
    if (mode === 'all') return targets.map((tn) => tn.node)
    return targets.map((tn) => tn.node).filter((n) => selectedNodes[n])
  }, [preflight, mode, targets, selectedNodes])

  // Storages, die auf ALLEN aktiven Nodes existieren (für den „einen Storage für alle"-Default).
  const commonStorages = useMemo(() => {
    if (activeNodes.length === 0) return []
    const lists = activeNodes.map((n) => {
      const tn = targets.find((x) => x.node === n)
      return new Set((tn?.storages ?? []).map((s) => s.name))
    })
    const [first, ...rest] = lists
    const names = [...(first ?? [])].filter((name) => rest.every((s) => s.has(name)))
    // Repräsentative Storage-Objekte (von der ersten aktiven Node) für Labels.
    const firstTn = targets.find((x) => x.node === activeNodes[0])
    return names
      .map((name) => (firstTn?.storages ?? []).find((s) => s.name === name))
      .filter(Boolean)
  }, [activeNodes, targets])

  // Wenn der bisher gewählte Default nicht mehr überall verfügbar ist → zurücksetzen.
  useEffect(() => {
    if (defaultStorage && !commonStorages.some((s) => s.name === defaultStorage)) {
      setDefaultStorage('')
    }
  }, [commonStorages, defaultStorage])

  // Effektive Storage/VMID-Wahl je aktiver Node.
  // VMID ist IMMER pro Node (cluster-weit eindeutig) – unabhängig vom Storage-Toggle;
  // nur der Storage folgt dem „einen für alle"- bzw. Per-Node-Modus.
  const selection = useMemo(() => activeNodes.map((n) => ({
    node: n,
    storage: perNodeMode ? (perNode[n]?.storage || '') : defaultStorage,
    newid: perNode[n]?.newid || '',
  })), [activeNodes, perNodeMode, perNode, defaultStorage])

  const plan = useMemo(
    () => (preflight && !preflight.source_shared ? buildPlan(selection, preflight) : { sharedOps: [], localOps: [] }),
    [selection, preflight],
  )
  const hasShared = plan.sharedOps.length > 0

  // Alle aktiven Nodes müssen einen Storage haben, sonst kein Start.
  const allChosen = activeNodes.length > 0 && selection.every((r) => r.storage)

  const setNode = (n, key, value) =>
    setPerNode((p) => ({ ...p, [n]: { ...p[n], [key]: value } }))

  const submit = async (e) => {
    e.preventDefault()
    setError('')
    // Ziel-Liste bauen (nur Zeilen mit Storage; VMID optional).
    const reqTargets = []
    for (const r of selection) {
      if (!r.storage) continue
      const tgt = { node: r.node, storage: r.storage }
      const nid = String(r.newid || '').trim()
      if (nid) {
        const num = parseInt(nid, 10)
        if (Number.isNaN(num) || num < 100) { setError(t('template_replication.vmid_invalid', { node: r.node })); return }
        tgt.newid = num
      }
      reqTargets.push(tgt)
    }
    if (reqTargets.length === 0) { setError(t('template_replication.no_targets_chosen')); return }

    setBusy(true)
    try {
      const job = await startReplication({
        source_node: tmpl.node,
        source_vmid: tmpl.vmid,
        targets: reqTargets,
        remove_source_after_shared: hasShared ? removeSource : false,
      })
      onClose?.()
      navigate(`/events/${job.id}`)
    } catch (err) {
      setError(replicationErrMsg(err, t))
      setBusy(false)
    }
  }

  const noReplication = preflight && (preflight.source_shared || preflight.single_node || targets.length === 0)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-700 shadow-xl w-full max-w-2xl max-h-[88vh] flex flex-col rounded-lg">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200 dark:border-zinc-700 shrink-0">
          <h2 className="text-sm font-semibold text-gray-900 dark:text-white">
            {t('template_replication.title', { name: tmpl.name || tmpl.vmid })}
          </h2>
          <button onClick={onClose} aria-label={t('template_replication.close')} className="btn-ghost">✕</button>
        </div>

        <div className="overflow-y-auto flex-1 p-5 space-y-4">
          {/* Kopf: Quelle */}
          <div className="text-xs text-gray-500 dark:text-zinc-400">
            {t('template_replication.source')}:{' '}
            <span className="font-mono text-gray-800 dark:text-zinc-200">
              {tmpl.name} · VMID {tmpl.vmid} · {tmpl.node}
            </span>
          </div>

          {preflight === null && (
            <p className="text-sm text-gray-400 dark:text-zinc-500 animate-pulse py-6">{t('template_replication.loading')}</p>
          )}

          {preflight === false && (
            <p className="text-sm text-portal-danger bg-portal-danger/10 border border-portal-danger/30 px-3 py-2 rounded">
              {preflightErr}
            </p>
          )}

          {/* kein-Op: Quelle bereits shared */}
          {preflight && preflight.source_shared && (
            <div className="text-sm text-portal-info bg-portal-info/10 border border-portal-info/30 px-3 py-3 rounded">
              {t('template_replication.noop_shared', { storage: preflight.source_storage || '' })}
            </div>
          )}

          {/* Single-Node / keine Ziele */}
          {preflight && !preflight.source_shared && targets.length === 0 && (
            <div className="text-sm text-portal-warn bg-portal-warn/10 border border-portal-warn/30 px-3 py-3 rounded">
              {t('template_replication.single_node')}
            </div>
          )}

          {/* Auswahl-Flow */}
          {preflight && !preflight.source_shared && targets.length > 0 && (
            <>
              {!preflight.is_template && (
                <div className="text-sm text-portal-warn bg-portal-warn/10 border border-portal-warn/30 px-3 py-2 rounded">
                  {t('template_replication.not_template')}
                </div>
              )}

              {/* Ziel-Modus */}
              <div>
                <span className="block text-xs text-gray-500 dark:text-zinc-500 mb-1">{t('template_replication.target_mode')}</span>
                <div className="flex items-center gap-4 text-sm text-gray-800 dark:text-zinc-200">
                  <label className="inline-flex items-center gap-1.5 cursor-pointer">
                    <input type="radio" name="repl-mode" checked={mode === 'selected'} onChange={() => setMode('selected')} />
                    {t('template_replication.mode_selected')}
                  </label>
                  <label className="inline-flex items-center gap-1.5 cursor-pointer">
                    <input type="radio" name="repl-mode" checked={mode === 'all'} onChange={() => setMode('all')} />
                    {t('template_replication.mode_all')}
                  </label>
                </div>
              </div>

              {/* Node-Mehrfachauswahl (nur „ausgewählte Nodes") */}
              {mode === 'selected' && (
                <div className="flex flex-wrap gap-2">
                  {targets.map((tn) => (
                    <label
                      key={tn.node}
                      className={`inline-flex items-center gap-1.5 text-sm px-2.5 py-1 border rounded cursor-pointer transition-colors ${
                        selectedNodes[tn.node]
                          ? 'border-portal-accent/50 bg-portal-accent/10 text-gray-900 dark:text-zinc-100'
                          : 'border-gray-300 dark:border-zinc-600 text-gray-600 dark:text-zinc-400'
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={!!selectedNodes[tn.node]}
                        onChange={(e) => setSelectedNodes((s) => ({ ...s, [tn.node]: e.target.checked }))}
                      />
                      {tn.node}
                    </label>
                  ))}
                </div>
              )}

              {activeNodes.length > 0 && (
                <>
                  {/* Storage-Default + Override-Haken */}
                  <label className="flex items-center gap-2 text-sm text-gray-800 dark:text-zinc-200 cursor-pointer">
                    <input type="checkbox" checked={perNodeMode} onChange={(e) => setPerNodeMode(e.target.checked)} />
                    {t('template_replication.per_node_override')}
                  </label>

                  {!perNodeMode && (
                    <div>
                      <label htmlFor="repl-default-storage" className="block text-xs text-gray-500 dark:text-zinc-500 mb-1">
                        {t('template_replication.default_storage')}
                      </label>
                      {commonStorages.length === 0 ? (
                        <p className="text-xs text-portal-warn">{t('template_replication.no_common_storage')}</p>
                      ) : (
                        <select
                          id="repl-default-storage"
                          value={defaultStorage}
                          onChange={(e) => setDefaultStorage(e.target.value)}
                          className={modalInputCls}
                        >
                          <option value="">{t('template_replication.select_storage')}</option>
                          {commonStorages.map((s) => (
                            <option key={s.name} value={s.name}>{storageLabel(s, t)}</option>
                          ))}
                        </select>
                      )}
                    </div>
                  )}

                  {/* Pro-Node-Storage-Zeilen (nur Storage; VMID separat unten) */}
                  {perNodeMode && (
                    <div className="space-y-2">
                      {activeNodes.map((n) => {
                        const tn = targets.find((x) => x.node === n)
                        const storages = tn?.storages ?? []
                        return (
                          <div key={n} className="border border-gray-200 dark:border-zinc-700 rounded p-3 space-y-1.5">
                            <div className="text-xs font-medium text-gray-700 dark:text-zinc-300">{n}</div>
                            <label className="block text-[11px] text-gray-500 dark:text-zinc-500">
                              {t('template_replication.storage')}
                            </label>
                            {storages.length === 0 ? (
                              <p className="text-xs text-portal-warn">{t('template_replication.node_no_storage')}</p>
                            ) : (
                              <select
                                value={perNode[n]?.storage || ''}
                                onChange={(e) => setNode(n, 'storage', e.target.value)}
                                className={modalInputCls}
                              >
                                <option value="">{t('template_replication.select_storage')}</option>
                                {storages.map((s) => (
                                  <option key={s.name} value={s.name}>{storageLabel(s, t)}</option>
                                ))}
                              </select>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  )}

                  {/* Ziel-VMIDs je Node – IMMER pro Node (cluster-weit eindeutig) */}
                  <div>
                    <span className="block text-xs text-gray-500 dark:text-zinc-500 mb-1">
                      {t('template_replication.vmids_title')}
                    </span>
                    <div className="space-y-1.5">
                      {activeNodes.map((n) => (
                        <div key={n} className="flex items-center gap-2">
                          <span className="text-xs text-gray-700 dark:text-zinc-300 w-28 shrink-0 truncate" title={n}>{n}</span>
                          <input
                            type="number"
                            min="100"
                            value={perNode[n]?.newid || ''}
                            placeholder={t('template_replication.vmid_auto')}
                            onChange={(e) => setNode(n, 'newid', e.target.value)}
                            className={`${modalInputCls} font-mono`}
                          />
                        </div>
                      ))}
                    </div>
                    <p className="text-[11px] text-gray-400 dark:text-zinc-600 mt-1">{t('template_replication.vmids_hint')}</p>
                  </div>

                  {/* Plan-Vorschau */}
                  {(plan.sharedOps.length > 0 || plan.localOps.length > 0) && (
                    <div className="border border-gray-200 dark:border-zinc-700 rounded p-3 bg-gray-50 dark:bg-zinc-800/50">
                      <div className="text-xs font-medium text-gray-600 dark:text-zinc-400 mb-1.5">
                        {t('template_replication.plan_title')}
                      </div>
                      <ul className="space-y-1 text-xs text-gray-700 dark:text-zinc-300">
                        {plan.sharedOps.map((op) => (
                          <li key={`s-${op.storage}`}>
                            • {t('template_replication.plan_shared', { storage: op.storage, count: op.nodes.length })}
                          </li>
                        ))}
                        {plan.localOps.map((op) => (
                          <li key={`l-${op.node}`}>
                            • {t('template_replication.plan_local', { node: op.node, storage: op.storage })}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* Optional: lokale Quelle nach shared-Heben entfernen */}
                  {hasShared && (
                    <label className="flex items-start gap-2 text-sm text-gray-800 dark:text-zinc-200 cursor-pointer">
                      <input type="checkbox" className="mt-0.5" checked={removeSource} onChange={(e) => setRemoveSource(e.target.checked)} />
                      <span>
                        {t('template_replication.remove_source')}
                        <span className="block text-xs text-gray-400 dark:text-zinc-600">{t('template_replication.remove_source_hint')}</span>
                      </span>
                    </label>
                  )}
                </>
              )}
            </>
          )}

          {error && <p className="text-sm text-portal-danger bg-portal-danger/10 border border-portal-danger/30 px-3 py-2 rounded">{error}</p>}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 px-5 py-4 border-t border-gray-200 dark:border-zinc-700 shrink-0">
          <button type="button" onClick={onClose} className="btn-secondary">
            {noReplication ? t('template_replication.close') : t('template_replication.cancel')}
          </button>
          {preflight && !noReplication && (
            <button type="button" onClick={submit} disabled={busy || !allChosen} className="btn-primary">
              {busy ? t('template_replication.starting') : t('template_replication.start')}
            </button>
          )}
        </div>
        <span className="rq hidden" aria-hidden="true" />
      </div>
    </div>
  )
}
