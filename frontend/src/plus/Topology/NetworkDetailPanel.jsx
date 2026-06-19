// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-75: Slide-Over mit Netzwerk-Details eines Gasts (AC-PANEL-*). Lädt den
// bestehenden VM-Detail-Endpoint on-click → kein neuer Backend-Endpoint.
import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { getVmDetail } from '../../api/vms'

/** guest.type ('vm'|'lxc') → VM-Detail-API/Route-Typ ('qemu'|'lxc'). */
function apiType(t) {
  return t === 'lxc' ? 'lxc' : 'qemu'
}

export default function NetworkDetailPanel({ guest, onClose }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const type = apiType(guest?.type)

  useEffect(() => {
    const handle = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handle)
    return () => window.removeEventListener('keydown', handle)
  }, [onClose])

  const { data, isLoading, isError } = useQuery({
    queryKey: ['topology-detail', guest?.node, type, guest?.vmid],
    queryFn: () => getVmDetail(guest.node, type, guest.vmid),
    enabled: !!guest,
    staleTime: 15_000,
    retry: false,
  })

  if (!guest) return null

  const nets = data?.networks || []
  const hasNet = nets.length > 0 || data?.ip
  const goDetail = () => navigate(`/vm/${guest.node}/${type}/${guest.vmid}`)

  return (
    <>
      <div className="fixed inset-0 bg-black/20 dark:bg-black/40 z-[59]" onClick={onClose} aria-hidden="true" />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('topology.panel.title', { name: guest.label })}
        className="fixed right-0 top-0 h-full w-full sm:w-[420px] bg-white dark:bg-zinc-900 border-l border-gray-200 dark:border-zinc-700 shadow-2xl z-[60] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-100 dark:border-zinc-800 shrink-0">
          <div className="flex-1 min-w-0">
            <h2 className="text-sm font-semibold text-gray-900 dark:text-zinc-100 truncate">{guest.label}</h2>
            <p className="text-[11px] text-gray-400 dark:text-zinc-500">{guest.type === 'lxc' ? 'LXC' : 'VM'} · {guest.vmid} · {guest.node}</p>
          </div>
          <button type="button" onClick={onClose} className="btn-ghost p-1" aria-label={t('common.close')}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="w-4 h-4">
              <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
          {/* Status-Zeile */}
          <div className="flex flex-wrap gap-1.5">
            {guest.managed_by_stack && (
              <span className="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium bg-portal-accent/15 text-portal-accent">
                ⛓ {t('topology.badge.stack', { name: guest.managed_by_stack })}
              </span>
            )}
            {guest.ssh_managed && (
              <span className="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium bg-portal-info/15 text-portal-info">
                ⚙ {t('topology.badge.ansible')}
              </span>
            )}
            {guest.is_template && (
              <span className="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium bg-gray-200 dark:bg-zinc-700 text-gray-600 dark:text-zinc-300">
                {t('topology.badge.template')}
              </span>
            )}
          </div>

          <div>
            <h3 className="text-xs font-semibold text-gray-700 dark:text-zinc-200 mb-2">{t('topology.panel.network')}</h3>

            {isLoading && <p className="text-xs text-gray-400 dark:text-zinc-500">{t('topology.panel.loading')}</p>}

            {!isLoading && (isError || !hasNet) && (
              <div className="rounded-md border border-portal-warn/30 bg-portal-warn/10 px-3 py-2 text-xs text-portal-warn">
                {t('topology.panel.no_network')}
              </div>
            )}

            {!isLoading && data?.ip && (
              <div className="mb-2 text-xs">
                <span className="text-gray-400 dark:text-zinc-500">IP: </span>
                <span className="font-mono text-gray-800 dark:text-zinc-200">{data.ip}</span>
              </div>
            )}

            {!isLoading && nets.length > 0 && (
              <div className="space-y-2">
                {nets.map((nic) => (
                  <div key={nic.id} className="rounded-md border border-gray-200 dark:border-zinc-700 px-2.5 py-2 text-xs">
                    <div className="flex items-center justify-between">
                      <span className="font-medium text-gray-800 dark:text-zinc-100">{nic.id}</span>
                      <span className="text-[10px] text-gray-400 dark:text-zinc-500">{nic.model}</span>
                    </div>
                    <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5">
                      <dt className="text-gray-400 dark:text-zinc-500">{t('topology.panel.bridge')}</dt>
                      <dd className="font-mono text-gray-700 dark:text-zinc-300">{nic.bridge || '–'}</dd>
                      <dt className="text-gray-400 dark:text-zinc-500">MAC</dt>
                      <dd className="font-mono text-gray-700 dark:text-zinc-300">{nic.mac || '–'}</dd>
                    </dl>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="px-4 py-3 border-t border-gray-100 dark:border-zinc-800 shrink-0">
          <button type="button" onClick={goDetail} className="btn-primary w-full text-xs">
            {t('topology.panel.go_detail')}
          </button>
        </div>
      </div>
    </>
  )
}
