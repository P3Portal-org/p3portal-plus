// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-42 Phase 2: „Netz-Freigaben"-Tab (Plus). Ein Netz (Bridge/SDN-VNet) an
// User oder Gruppe freigeben (US-10). Die IPAM-Pool-Sicht erbt automatisch (Pools
// netz-gebunden). Wirkt nur bei aktivem Strict-Toggle (Einstellungen); Admin
// sieht immer alles. Netz-Auswahl = dieselbe Quelle wie Pool-/Deploy-Formular.
import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import api from '../../api/client'
import { getNodes, getNodeVmOptions } from '../../api/cluster'
import { fetchUsers } from '../../api/admin'
import { formatApiError } from '../../api/errors'
import ConfirmModal from '../../components/common/ConfirmModal'
import { useGrants, useCreateGrant, useDeleteGrant } from './hooks'
import { networkLabel } from './helpers'

const inputCls =
  'h-8 rounded-md border border-gray-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-2 text-xs text-gray-700 dark:text-zinc-200 focus:outline-none focus:border-portal-accent'

function GrantForm({ onDone }) {
  const { t } = useTranslation()
  const createMut = useCreateGrant()

  const [node, setNode] = useState('')
  const [network, setNetwork] = useState('')
  const [vlanTag, setVlanTag] = useState('')
  const [granteeKind, setGranteeKind] = useState('user')
  const [granteeId, setGranteeId] = useState('')
  const [err, setErr] = useState('')

  const nodesQuery = useQuery({ queryKey: ['nodes'], queryFn: () => getNodes(false), staleTime: 60_000 })
  const optsQuery = useQuery({
    queryKey: ['node-vm-options', node],
    queryFn: () => getNodeVmOptions(node),
    enabled: !!node,
    staleTime: 30_000,
  })
  const usersQuery = useQuery({ queryKey: ['admin-users'], queryFn: fetchUsers, staleTime: 60_000 })
  const groupsQuery = useQuery({
    queryKey: ['groups'],
    queryFn: async () => (await api.get('/api/groups')).data,
    staleTime: 60_000,
  })

  const bridges = optsQuery.data?.bridges || []
  const vnets = optsQuery.data?.vnets || []
  const isVnet = vnets.includes(network)
  const kind = isVnet ? 'vnet' : 'bridge'

  const grantees = granteeKind === 'user'
    ? (usersQuery.data || []).map((u) => ({ id: u.id, label: u.username }))
    : (groupsQuery.data || []).map((g) => ({ id: g.id, label: g.name }))

  // Grantee-Auswahl zurücksetzen, wenn der Typ wechselt.
  useEffect(() => { setGranteeId('') }, [granteeKind])

  const submit = async () => {
    setErr('')
    if (!network || !granteeId) return
    try {
      await createMut.mutateAsync({
        kind,
        network_name: network,
        node: kind === 'bridge' ? node || null : null,
        vlan_tag: kind === 'bridge' && vlanTag ? Number(vlanTag) : null,
        grantee_kind: granteeKind,
        grantee_id: Number(granteeId),
      })
      onDone()
    } catch (e) {
      setErr(formatApiError(e, t('common.error_generic')))
    }
  }

  return (
    <div className="rounded-md border border-portal-accent/30 bg-portal-accent/5 p-3 space-y-2">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        <label className="text-xs text-portal-text2">
          {t('ipam.pool.field_node')}
          <select value={node} onChange={(e) => { setNode(e.target.value); setNetwork('') }} className={`${inputCls} w-full mt-1`}>
            <option value="">{t('ipam.pool.node_select')}</option>
            {(nodesQuery.data || []).map((n) => <option key={n.node} value={n.node}>{n.node}</option>)}
          </select>
        </label>
        <label className="text-xs text-portal-text2">
          {t('ipam.pool.field_network')}
          <select value={network} onChange={(e) => setNetwork(e.target.value)} disabled={!node} className={`${inputCls} w-full mt-1`}>
            <option value="">{t('ipam.pool.network_select')}</option>
            {bridges.length > 0 && (
              <optgroup label={t('ipam.pool.group_bridges')}>
                {bridges.map((b) => <option key={`b-${b}`} value={b}>{b}</option>)}
              </optgroup>
            )}
            {vnets.length > 0 && (
              <optgroup label={t('ipam.pool.group_vnets')}>
                {vnets.map((v) => <option key={`v-${v}`} value={v}>{v}</option>)}
              </optgroup>
            )}
          </select>
        </label>
        {kind === 'bridge' && (
          <label className="text-xs text-portal-text2">
            {t('ipam.pool.field_vlan')}
            <input value={vlanTag} onChange={(e) => setVlanTag(e.target.value.replace(/\D/g, ''))} placeholder={t('ipam.pool.vlan_ph')} className={`${inputCls} w-full mt-1`} />
          </label>
        )}
        <label className="text-xs text-portal-text2">
          {t('ipam.grants.grantee_kind')}
          <select value={granteeKind} onChange={(e) => setGranteeKind(e.target.value)} className={`${inputCls} w-full mt-1`}>
            <option value="user">{t('ipam.grants.kind_user')}</option>
            <option value="group">{t('ipam.grants.kind_group')}</option>
          </select>
        </label>
        <label className="text-xs text-portal-text2">
          {t('ipam.grants.grantee')}
          <select value={granteeId} onChange={(e) => setGranteeId(e.target.value)} className={`${inputCls} w-full mt-1`}>
            <option value="">{t('ipam.grants.grantee_select')}</option>
            {grantees.map((g) => <option key={g.id} value={g.id}>{g.label}</option>)}
          </select>
        </label>
      </div>
      {err && <p className="text-[11px] text-portal-danger">{err}</p>}
      <div className="flex items-center gap-2">
        <button type="button" onClick={submit} disabled={!network || !granteeId || createMut.isPending} className="btn-primary text-xs">
          {createMut.isPending ? '…' : t('ipam.grants.add')}
        </button>
        <button type="button" onClick={onDone} className="btn-secondary text-xs">{t('common.cancel')}</button>
      </div>
    </div>
  )
}

export default function NetworkGrantsTab() {
  const { t } = useTranslation()
  const { data: grants, isLoading, isError, error } = useGrants()
  const deleteMut = useDeleteGrant()
  const [adding, setAdding] = useState(false)
  const [delTarget, setDelTarget] = useState(null)

  const rows = grants || []

  const confirmDelete = async () => {
    if (!delTarget) return
    try {
      await deleteMut.mutateAsync(delTarget.id)
    } finally {
      setDelTarget(null)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs text-portal-text2 max-w-2xl">{t('ipam.grants.description')}</p>
        {!adding && (
          <button type="button" onClick={() => setAdding(true)} className="btn-primary text-xs shrink-0">
            + {t('ipam.grants.add')}
          </button>
        )}
      </div>

      {adding && <GrantForm onDone={() => setAdding(false)} />}

      <div className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-700 rounded-lg p-4">
        {isLoading ? (
          <p className="text-xs text-gray-400 dark:text-zinc-500">{t('common.loading')}</p>
        ) : isError ? (
          <p className="text-xs text-portal-danger">{formatApiError(error, t('common.error_generic'))}</p>
        ) : rows.length === 0 ? (
          <p className="text-xs text-gray-400 dark:text-zinc-500 italic">{t('ipam.grants.empty')}</p>
        ) : (
          <ul>
            {rows.map((g) => (
              <li key={g.id} className="flex items-center gap-2 py-1.5 border-b border-gray-100 dark:border-zinc-800 last:border-0">
                <span className="text-xs font-medium text-gray-900 dark:text-zinc-100">{networkLabel(g, t)}</span>
                <span className="text-[11px] text-portal-text2">
                  → {t(`ipam.grants.kind_${g.grantee_kind}`)}: {g.grantee_name || `#${g.grantee_id}`}
                </span>
                <button
                  type="button"
                  onClick={() => setDelTarget(g)}
                  disabled={deleteMut.isPending}
                  className="btn-table-danger ml-auto shrink-0"
                >
                  {t('ipam.grants.revoke')}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {delTarget && (
        <ConfirmModal
          title={t('ipam.grants.revoke')}
          body={t('ipam.grants.revoke_confirm', { network: networkLabel(delTarget, t) })}
          confirmLabel={t('ipam.grants.revoke')}
          variant="danger"
          onConfirm={confirmDelete}
          onClose={() => setDelTarget(null)}
        />
      )}
    </div>
  )
}
