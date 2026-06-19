// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-76 Phase 1: Stack-Detailseite /stacks/:id (AC-UI-8/13).
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import jsyaml from 'js-yaml'
import { useAuth } from '../../hooks/useAuth'
import { useCapability } from '../../hooks/useCapability'
import { formatApiError } from '../../api/errors'
import ConfirmModal from '../../components/common/ConfirmModal'
import Watermark from '../../components/common/Watermark'
import { useStack, useDeleteStack, useInvalidateStacks } from './hooks'
import StackVersionList from './StackVersionList'
import DeploymentStateBadge from './DeploymentStateBadge'
import StackPlanModal from './StackPlanModal'
import StackDriftModal from './StackDriftModal'
import StackDeploymentsTab from './StackDeploymentsTab'
import StackResourcesTab from './StackResourcesTab'
import HelpButton from '../../features/help/components/HelpButton'

// PROJ-91 (§H): informativer Plan-Hinweis – wie viele Gäste eine aktive Firewall
// bekommen + wie viele stack-eigene Security-Groups angelegt werden. Aus dem YAML
// best-effort abgeleitet (die FW-Artefakte laufen über den Post-Apply-Commit und
// tauchen nicht im tofu-Plan auf).
function firewallHintOf(yamlText) {
  try {
    const obj = jsyaml.load(yamlText)
    if (!obj || typeof obj !== 'object') return null
    const guests = (Array.isArray(obj.resources) ? obj.resources : [])
      .filter((r) => r?.firewall?.enabled).length
    const groups = (Array.isArray(obj.security_groups) ? obj.security_groups : []).length
    return (guests > 0 || groups > 0) ? { guests, groups } : null
  } catch {
    return null
  }
}

function ResourceRow({ r }) {
  return (
    <tr className="border-b border-portal-border/50 text-portal-text">
      <td className="px-3 py-1.5 font-mono">{r.name}</td>
      <td className="px-3 py-1.5">{r.node}</td>
      <td className="px-3 py-1.5">{r.template}</td>
      <td className="px-3 py-1.5">{r.cores ?? 1}</td>
      <td className="px-3 py-1.5">{r.memory ?? 2048} MB</td>
      <td className="px-3 py-1.5">{r.disk ?? 32} GB</td>
      <td className="px-3 py-1.5">{r.pool || '—'}</td>
    </tr>
  )
}

export default function StackDetailPage() {
  const { t } = useTranslation()
  const canUseStacks = useCapability('stacks')
  const navigate = useNavigate()
  const { id } = useParams()
  const { role } = useAuth()
  const isAdmin = role === 'admin'

  const { data: stack, isLoading, error } = useStack(id)
  const delMut = useDeleteStack()
  const invalidate = useInvalidateStacks()

  const [tab, setTab] = useState('yaml')   // 'yaml' | 'resources' | 'versions' | 'deployments' | 'live'
  const [confirmDel, setConfirmDel] = useState(false)
  const [pendingMsg, setPendingMsg] = useState(null)
  const [planOp, setPlanOp] = useState(null)   // 'apply' | 'destroy' | null
  const [showDrift, setShowDrift] = useState(false)

  // Owner OR admin can write (backend enforces; UI mirrors).
  const canWrite = isAdmin || (stack && stack.owner_user_id != null)

  const handleDelete = async () => {
    const res = await delMut.mutateAsync(Number(id))
    if (res?.kind === 'pending') {
      setPendingMsg(t('stacks.approval.delete_pending', { name: stack?.name }))
    } else {
      navigate('/stacks')
    }
  }

  if (!canUseStacks) {
    return <div className="flex-1 flex items-center justify-center"><p className="text-sm text-portal-text2">{t('stacks.not_available')}</p></div>
  }

  const tabCls = (id_) =>
    `px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
      tab === id_ ? 'border-portal-accent text-portal-white' : 'border-transparent text-portal-text2 hover:text-portal-white'
    }`

  const resources = stack?.resources ?? []
  // Corrupt = leerer ODER nicht-parsebarer yaml_text (BUG-76-4, Edge 16).
  // Backend liefert yaml_corrupt (safe_load-Check) — kein js-yaml im Detail-Chunk nötig.
  const corrupt = stack && (stack.yaml_corrupt || !stack.yaml_text || stack.yaml_text.trim() === '')

  return (
    <div className="flex flex-col flex-1 min-h-0">
      <header className="h-12 flex items-center justify-between gap-3 px-6 border-b border-gray-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <button onClick={() => navigate('/stacks')} className="btn-table" aria-label={t('common.back')}>←</button>
          <h1 className="text-sm font-semibold text-gray-900 dark:text-zinc-100 truncate">{stack?.name || t('stacks.title')}</h1>
          <HelpButton helpKey="stacks.detail" />
          {stack && <span className="shrink-0 px-2 py-0.5 rounded-full text-[11px] font-medium bg-portal-bg3 text-portal-text2">v{stack.version}</span>}
          {stack && (
            <span className={`shrink-0 px-2 py-0.5 rounded-full text-[11px] font-medium ${stack.status === 'active' ? 'bg-portal-success/15 text-portal-success' : 'bg-portal-bg3 text-portal-text2'}`}>
              {t(`stacks.status.${stack.status}`, stack.status)}
            </span>
          )}
          {stack?.is_orphan && <span className="shrink-0 text-[10px] uppercase text-portal-warn">{t('stacks.orphan_badge')}</span>}
          {stack?.deployment_state && <DeploymentStateBadge state={stack.deployment_state} />}
        </div>
        {stack && (
          <div className="flex items-center gap-2 shrink-0">
            {/* Phase 2b: Deploy/Destroy/Drift aktiv (AC-2B-UI-1/4/5) */}
            {canWrite && <button onClick={() => setPlanOp('apply')} className="btn-primary">{t('stacks.deploy.btn')}</button>}
            {canWrite && stack.deployment_state && stack.deployment_state !== 'not_deployed' && stack.deployment_state !== 'destroyed' && (
              <button onClick={() => setPlanOp('destroy')} className="btn-danger">{t('stacks.deploy.destroy_btn')}</button>
            )}
            {stack.deployment_state && stack.deployment_state !== 'not_deployed' && (
              <button onClick={() => setShowDrift(true)} className="btn-secondary">{t('stacks.drift.btn')}</button>
            )}
            {canWrite && <button onClick={() => navigate(`/stacks/${id}/edit`)} className="btn-secondary">{t('common.edit')}</button>}
            {canWrite && <button onClick={() => setConfirmDel(true)} className="btn-table-danger">{t('common.delete')}</button>}
          </div>
        )}
      </header>
      <main className="flex-1 overflow-y-auto px-6 py-6 space-y-4 bg-transparent">
        {isLoading ? (
          <p className="text-sm text-portal-text2">{t('common.loading')}</p>
        ) : error ? (
          <p className="text-sm text-portal-danger">{formatApiError(error, t('common.error_generic'))}</p>
        ) : stack ? (
          <>
            {stack.description && <p className="text-sm text-portal-text2">{stack.description}</p>}

            {corrupt && (
              <div className="rounded-md border border-portal-danger/40 bg-portal-danger/10 p-3 text-xs text-portal-danger">
                {t('stacks.detail.corrupt_banner')}
              </div>
            )}
            {pendingMsg && (
              <div className="rounded-md border border-portal-warn/40 bg-portal-warn/10 p-3 text-xs text-portal-warn">{pendingMsg}</div>
            )}

            {/* Tabs */}
            <div className="flex border-b border-portal-border">
              <button className={tabCls('yaml')} onClick={() => setTab('yaml')}>{t('stacks.detail.yaml_tab')}</button>
              <button className={tabCls('resources')} onClick={() => setTab('resources')}>{t('stacks.detail.resources_tab')} ({stack.resource_count})</button>
              <button className={tabCls('live')} onClick={() => setTab('live')}>{t('stacks.detail.live_tab')}</button>
              <button className={tabCls('deployments')} onClick={() => setTab('deployments')}>{t('stacks.detail.deployments_tab')}</button>
              <button className={tabCls('versions')} onClick={() => setTab('versions')}>{t('stacks.detail.versions_tab')}</button>
            </div>

            <div className="bg-white dark:bg-zinc-900 rounded-lg border border-gray-200 dark:border-zinc-700 p-5">
              {tab === 'yaml' && (
                <pre className="text-xs font-mono whitespace-pre-wrap break-all text-portal-text overflow-auto max-h-[60vh]">{stack.yaml_text}</pre>
              )}

              {tab === 'resources' && (
                resources.length === 0 ? (
                  <p className="text-sm text-portal-text3 italic">{t('stacks.detail.no_resources')}</p>
                ) : (
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-portal-text3 border-b border-portal-border text-left">
                        <th className="px-3 py-1.5 font-medium">{t('stacks.preview.col_name')}</th>
                        <th className="px-3 py-1.5 font-medium">{t('stacks.preview.col_node')}</th>
                        <th className="px-3 py-1.5 font-medium">{t('stacks.preview.col_template')}</th>
                        <th className="px-3 py-1.5 font-medium">{t('stacks.preview.col_cores')}</th>
                        <th className="px-3 py-1.5 font-medium">{t('stacks.preview.col_memory')}</th>
                        <th className="px-3 py-1.5 font-medium">{t('stacks.preview.col_disk')}</th>
                        <th className="px-3 py-1.5 font-medium">{t('stacks.preview.col_pool')}</th>
                      </tr>
                    </thead>
                    <tbody>{resources.map((r, i) => <ResourceRow key={i} r={r} />)}</tbody>
                  </table>
                )
              )}

              {tab === 'live' && <StackResourcesTab stackId={Number(id)} />}

              {tab === 'deployments' && <StackDeploymentsTab stackId={Number(id)} />}

              {tab === 'versions' && (
                <StackVersionList stackId={Number(id)} canWrite={canWrite} currentEtag={stack.current_etag} onRestored={() => invalidate(Number(id))} />
              )}
            </div>
          </>
        ) : null}

        <Watermark />
      </main>

      {confirmDel && (
        <ConfirmModal
          title={t('stacks.delete_confirm_title')}
          body={t('stacks.delete_confirm_body', { name: stack?.name })}
          confirmLabel={t('common.delete')}
          variant="danger"
          onConfirm={handleDelete}
          onClose={() => setConfirmDel(false)}
        />
      )}

      {planOp && stack && (
        <StackPlanModal
          stackId={Number(id)}
          stackName={stack.name}
          operation={planOp}
          firewallHint={planOp === 'apply' ? firewallHintOf(stack.yaml_text) : null}
          onClose={() => setPlanOp(null)}
          onStarted={() => { invalidate(Number(id)); setTab('deployments') }}
        />
      )}

      {showDrift && (
        <StackDriftModal
          stackId={Number(id)}
          onClose={() => setShowDrift(false)}
          onChecked={() => invalidate(Number(id))}
        />
      )}
    </div>
  )
}
