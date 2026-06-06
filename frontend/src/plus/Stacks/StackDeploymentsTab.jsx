// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-76 Phase 2b: Deployment-Historie-Tab (AC-2B-UI-7).
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { formatApiError } from '../../api/errors'
import { useStackDeployments } from './hooks'

const STATUS_STYLES = {
  running: 'text-portal-info',
  success: 'text-portal-success',
  partial: 'text-portal-warn',
  failed:  'text-portal-danger',
}

function summaryText(s, t) {
  if (!s) return '—'
  const parts = []
  if (s.create) parts.push(`+${s.create}`)
  if (s.change) parts.push(`~${s.change}`)
  if (s.destroy) parts.push(`−${s.destroy}`)
  if (s.replace) parts.push(`∓${s.replace}`)
  return parts.length ? parts.join(' ') : t('stacks.deploy.no_changes')
}

export default function StackDeploymentsTab({ stackId }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { data, isLoading, error } = useStackDeployments(stackId)
  const rows = data ?? []

  if (isLoading) return <p className="text-sm text-portal-text2">{t('common.loading')}</p>
  if (error) return <p className="text-sm text-portal-danger">{formatApiError(error, t('common.error_generic'))}</p>
  if (rows.length === 0) return <p className="text-sm text-portal-text3 italic">{t('stacks.deploy.no_deployments')}</p>

  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-portal-text3 border-b border-portal-border text-left">
          <th className="px-3 py-1.5 font-medium">{t('stacks.deploy.col_operation')}</th>
          <th className="px-3 py-1.5 font-medium">{t('stacks.deploy.col_status')}</th>
          <th className="px-3 py-1.5 font-medium">{t('stacks.deploy.col_summary')}</th>
          <th className="px-3 py-1.5 font-medium">{t('stacks.deploy.col_started')}</th>
          <th className="px-3 py-1.5 font-medium">{t('stacks.deploy.col_finished')}</th>
          <th className="px-3 py-1.5 font-medium text-right">{t('stacks.deploy.col_log')}</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((d) => (
          <tr key={d.id} className="border-b border-portal-border/50 text-portal-text">
            <td className="px-3 py-1.5">{t(`stacks.deploy.operation.${d.operation}`, d.operation)}</td>
            <td className={`px-3 py-1.5 font-medium ${STATUS_STYLES[d.status] ?? 'text-portal-text2'}`}>
              {t(`stacks.deploy.run_status.${d.status}`, d.status)}
              {d.error_text && <span className="block text-portal-danger/80 font-normal mt-0.5 max-w-xs truncate" title={d.error_text}>{d.error_text}</span>}
            </td>
            <td className="px-3 py-1.5 font-mono text-portal-text2">{summaryText(d.plan_summary, t)}</td>
            <td className="px-3 py-1.5 text-portal-text3">{(d.started_at || '').replace('T', ' ').slice(0, 16)}</td>
            <td className="px-3 py-1.5 text-portal-text3">{d.finished_at ? d.finished_at.replace('T', ' ').slice(0, 16) : '—'}</td>
            <td className="px-3 py-1.5 text-right">
              {d.job_id
                ? <button onClick={() => navigate(`/events/${d.job_id}`)} className="btn-table">{t('stacks.deploy.view_log')}</button>
                : '—'}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
