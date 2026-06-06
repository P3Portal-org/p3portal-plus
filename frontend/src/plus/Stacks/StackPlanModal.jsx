// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-76 Phase 2b: Plan-Gate-Modal (AC-2B-PLAN, AC-2B-UI-1/2/3).
// Zweistufig: Plan → Review (Zerstörungen hervorgehoben) → Apply/Destroy als Job
// → Live-Log. 202 → Pending-Banner, 409 → „Definition geändert, neu planen".
import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { formatApiError } from '../../api/errors'
import { useStackPlan, useDeployStack, useDestroyStack } from './hooks'
import StackDeployLogView from './StackDeployLogView'

// portal-* Token je Plan-Aktion. Zerstörung/Replace = danger (AC-2B-PLAN-5).
const ACTION_STYLES = {
  create:  'text-portal-success',
  update:  'text-portal-warn',
  delete:  'text-portal-danger font-semibold',
  replace: 'text-portal-danger font-semibold',
}
const ACTION_SIGN = { create: '+', update: '~', delete: '−', replace: '∓' }

function CountChip({ label, value, danger }) {
  if (!value) return null
  const cls = danger ? 'bg-portal-danger/15 text-portal-danger' : 'bg-portal-bg3 text-portal-text2'
  return <span className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${cls}`}>{value} {label}</span>
}

export default function StackPlanModal({ stackId, stackName, operation, onClose, onStarted }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const isDestroy = operation === 'destroy'

  const planMut = useStackPlan()
  const deployMut = useDeployStack()
  const destroyMut = useDestroyStack()
  const runMut = isDestroy ? destroyMut : deployMut

  const [phase, setPhase] = useState('planning')   // planning | review | running
  const [plan, setPlan] = useState(null)
  const [error, setError] = useState(null)
  const [vmidTaken, setVmidTaken] = useState(false) // belegte VMID → zurück zum Editor anbieten
  const [vmidSuggestions, setVmidSuggestions] = useState([]) // [{index,name,old_vmid,new_vmid}]
  const [pending, setPending] = useState(null)     // { poll_url }
  const [jobId, setJobId] = useState(null)

  const goToEditor = () => { onClose?.(); navigate(`/stacks/${stackId}/edit`) }
  // „Nächste freie IDs wählen": zum Editor mit den Vorschlägen vorausgefüllt.
  const applyFreeVmids = () => {
    onClose?.()
    navigate(`/stacks/${stackId}/edit`, { state: { vmidSuggestions } })
  }

  const runPlan = useCallback(async () => {
    setPhase('planning'); setError(null); setPlan(null); setVmidTaken(false); setVmidSuggestions([])
    try {
      const data = await planMut.mutateAsync({ id: stackId, operation })
      setPlan(data)
      setPhase('review')
    } catch (err) {
      // Bekannte Gate-Fehler vor dem Plan klar übersetzen (sonst roher detail-Code).
      const detail = err?.response?.data?.detail
      if (detail && typeof detail === 'object' && detail.error === 'vmid_taken') {
        setError(t('stacks.deploy.vmid_taken', { ids: (detail.taken || []).join(', ') }))
        setVmidTaken(true)
        setVmidSuggestions(Array.isArray(detail.suggestions) ? detail.suggestions : [])
      } else if (typeof detail === 'string' && detail.startsWith('template_not_found:')) {
        setError(t('stacks.deploy.template_not_found', { names: detail.slice('template_not_found:'.length) }))
      } else {
        setError(formatApiError(err, t('common.error_generic')))
      }
      setPhase('review')
    }
    // planMut/operation/stackId/t are stable per render; intentionally minimal deps.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stackId, operation])

  useEffect(() => { runPlan() }, [runPlan])

  const handleApply = async () => {
    if (!plan?.plan_token) return
    setError(null)
    try {
      const res = await runMut.mutateAsync({ id: stackId, planToken: plan.plan_token })
      if (res?.kind === 'pending') {
        setPending(res.data || {})
      } else {
        setJobId(res.data?.job_id)
        setPhase('running')
        onStarted?.()
      }
    } catch (err) {
      // 409 = Definition geändert / Lock → Re-Plan anbieten.
      const status = err?.response?.status
      if (status === 409) {
        setError(t('stacks.deploy.definition_changed'))
      } else {
        setError(formatApiError(err, t('common.error_generic')))
      }
    }
  }

  const summary = plan?.summary
  const destructive = summary ? (summary.destroy + summary.replace) : 0

  const title = isDestroy ? t('stacks.deploy.destroy_title', { name: stackName })
    : t('stacks.deploy.plan_title', { name: stackName })

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-700 rounded-lg w-full max-w-2xl mx-4 shadow-xl flex flex-col max-h-[85vh]">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200 dark:border-zinc-700 shrink-0">
          <h2 className="text-sm font-semibold text-gray-900 dark:text-zinc-100">{title}</h2>
          <button onClick={onClose} className="btn-ghost text-gray-400 hover:text-gray-600" aria-label={t('common.close')}>✕</button>
        </div>

        <div className="overflow-auto flex-1 px-5 py-4 flex flex-col min-h-0">
          {pending && (
            <div className="rounded-md border border-portal-warn/40 bg-portal-warn/10 p-3 text-xs text-portal-warn">
              {t('stacks.approval.pending')}
              {pending.poll_url && (
                <a href={pending.poll_url} className="ml-2 underline" target="_blank" rel="noreferrer">{t('stacks.approval.view_request')}</a>
              )}
            </div>
          )}

          {!pending && phase === 'planning' && (
            <p className="text-sm text-portal-text2">{t('stacks.deploy.planning')}</p>
          )}

          {!pending && phase === 'review' && (
            <>
              {error && <p className="text-sm text-portal-danger mb-3">{error}</p>}
              {vmidTaken && (
                <div className="flex flex-wrap gap-2 mb-3">
                  {vmidSuggestions.length > 0 && (
                    <button type="button" onClick={applyFreeVmids} className="btn-primary self-start">
                      {t('stacks.deploy.pick_free_vmids', {
                        ids: vmidSuggestions.map((s) => s.new_vmid).join(', '),
                      })}
                    </button>
                  )}
                  <button type="button" onClick={goToEditor} className="btn-secondary self-start">
                    {t('stacks.deploy.back_to_editor')}
                  </button>
                </div>
              )}
              {summary && (
                <>
                  <div className="flex flex-wrap items-center gap-2 mb-3">
                    <CountChip label={t('stacks.deploy.count_create')} value={summary.create} />
                    <CountChip label={t('stacks.deploy.count_change')} value={summary.change} />
                    <CountChip label={t('stacks.deploy.count_destroy')} value={summary.destroy} danger />
                    <CountChip label={t('stacks.deploy.count_replace')} value={summary.replace} danger />
                    {summary.create + summary.change + summary.destroy + summary.replace === 0 && (
                      <span className="text-xs text-portal-text2">{t('stacks.deploy.no_changes')}</span>
                    )}
                  </div>

                  {destructive > 0 && (
                    <div className="rounded-md border border-portal-danger/40 bg-portal-danger/10 p-3 text-xs text-portal-danger mb-3">
                      {t('stacks.deploy.destroy_warning', { count: destructive })}
                    </div>
                  )}

                  {summary.resources.length > 0 && (
                    <div className="rounded-md border border-portal-border overflow-auto">
                      <table className="w-full text-xs">
                        <thead className="bg-portal-bg2">
                          <tr className="text-portal-text3 border-b border-portal-border text-left">
                            <th className="px-3 py-1.5 font-medium">{t('stacks.deploy.col_resource')}</th>
                            <th className="px-3 py-1.5 font-medium">{t('stacks.deploy.col_action')}</th>
                          </tr>
                        </thead>
                        <tbody>
                          {summary.resources.map((r) => (
                            <tr key={r.name} className="border-b border-portal-border/50 last:border-0">
                              <td className="px-3 py-1.5 font-mono text-portal-text">{r.name}</td>
                              <td className={`px-3 py-1.5 font-mono ${ACTION_STYLES[r.action] ?? 'text-portal-text2'}`}>
                                {ACTION_SIGN[r.action] ?? ''} {t(`stacks.deploy.action.${r.action}`, r.action)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </>
              )}
            </>
          )}

          {!pending && phase === 'running' && jobId && (
            <StackDeployLogView jobId={jobId} />
          )}
        </div>

        <div className="flex justify-end gap-2 px-5 py-4 border-t border-gray-200 dark:border-zinc-700 shrink-0">
          {phase === 'running' || pending ? (
            <button type="button" onClick={onClose} className="btn-secondary">{t('common.close')}</button>
          ) : (
            <>
              <button type="button" onClick={onClose} className="btn-secondary">{t('common.cancel')}</button>
              {error
                ? <button type="button" onClick={runPlan} className="btn-primary">{t('stacks.deploy.replan_btn')}</button>
                : (
                  <button
                    type="button"
                    onClick={handleApply}
                    disabled={phase !== 'review' || runMut.isPending || !plan?.plan_token}
                    className={isDestroy ? 'btn-danger' : 'btn-primary'}
                  >
                    {runMut.isPending
                      ? t('stacks.deploy.starting')
                      : isDestroy ? t('stacks.deploy.confirm_destroy') : t('stacks.deploy.confirm_apply')}
                  </button>
                )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
