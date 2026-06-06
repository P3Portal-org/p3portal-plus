// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-76 Phase 2b: Reale (deployte) VMs eines Stacks (AC-2B-UI-8).
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { formatApiError } from '../../api/errors'
import { useStackLiveResources } from './hooks'

function PowerBadge({ status, t }) {
  if (!status) return <span className="text-portal-text3">—</span>
  const cls = status === 'running' ? 'text-portal-success' : 'text-portal-text2'
  return <span className={`text-xs font-medium ${cls}`}>{t(`stacks.resources.power.${status}`, status)}</span>
}

export default function StackResourcesTab({ stackId }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { data, isLoading, error } = useStackLiveResources(stackId)
  const rows = data ?? []

  if (isLoading) return <p className="text-sm text-portal-text2">{t('common.loading')}</p>
  if (error) return <p className="text-sm text-portal-danger">{formatApiError(error, t('common.error_generic'))}</p>
  if (rows.length === 0) return <p className="text-sm text-portal-text3 italic">{t('stacks.resources.empty')}</p>

  const openVm = (r) => {
    if (!r.node || r.vmid == null) return
    const type = r.kind === 'lxc' ? 'lxc' : 'qemu'
    navigate(`/vm/${r.node}/${type}/${r.vmid}`)
  }

  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-portal-text3 border-b border-portal-border text-left">
          <th className="px-3 py-1.5 font-medium">{t('stacks.resources.col_name')}</th>
          <th className="px-3 py-1.5 font-medium">{t('stacks.resources.col_vmid')}</th>
          <th className="px-3 py-1.5 font-medium">{t('stacks.resources.col_node')}</th>
          <th className="px-3 py-1.5 font-medium">{t('stacks.resources.col_kind')}</th>
          <th className="px-3 py-1.5 font-medium">{t('stacks.resources.col_power')}</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr
            key={i}
            className="group border-b border-portal-border/50 text-portal-text hover:bg-portal-bg3/40 cursor-pointer"
            onClick={() => openVm(r)}
          >
            <td className="px-3 py-1.5 font-mono group-hover:text-portal-accent">{r.resource_name}</td>
            <td className="px-3 py-1.5 font-mono text-portal-text2">{r.vmid}</td>
            <td className="px-3 py-1.5 text-portal-text2">{r.node || '—'}</td>
            <td className="px-3 py-1.5 text-portal-text2">{r.kind === 'lxc' ? 'LXC' : 'VM'}</td>
            <td className="px-3 py-1.5"><PowerBadge status={r.status} t={t} /></td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
