// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-77: 4-Tab Target-Selektor für Auto-Snapshot-Jobs (AC-TGT-1..7).
// Tabs: Einzeln / Pool / Node / Tag-Filter; Werte werden in einem TargetSpec
// -Objekt zusammengeführt:
//   {
//     singles:           [{portal_node_id, vmid, kind}],
//     pool_ids:          [int],
//     portal_node_ids:   [int],
//     tags:              [string],
//     kind_filter:       'qemu' | 'lxc' | 'both',
//   }
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { getVms } from '../../api/cluster'
import { getNodes } from '../../api/cluster'
import { poolsApi } from '../Pools/api'

const inputCls = 'w-full text-sm border border-gray-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-gray-900 dark:text-zinc-100 px-3 py-2 rounded focus:outline-none focus:ring-1 focus:ring-orange-500 placeholder-gray-400 dark:placeholder-zinc-500'

function CountBadge({ count }) {
  if (!count) return null
  return (
    <span className="ml-1 px-1.5 py-0.5 text-[10px] rounded-full bg-orange-500/20 text-orange-700 dark:text-orange-300 font-medium">
      {count}
    </span>
  )
}

function VmKey(vm) {
  return `${vm.portal_node_id ?? 0}:${vm.vmid}:${vm.type ?? vm.kind}`
}

// ─── Einzeln-Tab ────────────────────────────────────────────────────────────

function SingleTab({ value, onChange }) {
  const { t } = useTranslation()
  const [vms, setVms] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')

  useEffect(() => {
    let alive = true
    getVms()
      .then((data) => { if (alive) { setVms(Array.isArray(data) ? data : []); setError('') } })
      .catch(() => { if (alive) setError(t('common.error_generic')) })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [t])

  const selectedSet = useMemo(() => new Set(
    (value ?? []).map(v => `${v.portal_node_id}:${v.vmid}:${v.kind}`)
  ), [value])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return vms.filter(vm => {
      // Templates ausblenden
      if (vm.template) return false
      if (!q) return true
      return (
        String(vm.vmid).includes(q) ||
        (vm.name ?? '').toLowerCase().includes(q) ||
        (vm.node ?? '').toLowerCase().includes(q)
      )
    })
  }, [vms, search])

  const toggle = (vm) => {
    const kind = vm.type === 'lxc' || vm.kind === 'lxc' ? 'lxc' : 'qemu'
    const target = { portal_node_id: vm.portal_node_id ?? 0, vmid: vm.vmid, kind }
    const key = `${target.portal_node_id}:${target.vmid}:${target.kind}`
    if (selectedSet.has(key)) {
      onChange((value ?? []).filter(v => `${v.portal_node_id}:${v.vmid}:${v.kind}` !== key))
    } else {
      onChange([...(value ?? []), target])
    }
  }

  return (
    <div className="space-y-2">
      <input
        type="search"
        placeholder={t('config_snapshots.filter_search', 'Suchen…')}
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className={inputCls}
      />
      {loading && <p className="text-xs text-gray-500 dark:text-zinc-400">{t('common.loading')}</p>}
      {error && <p className="text-xs text-red-500">{error}</p>}
      {!loading && !error && filtered.length === 0 && (
        <p className="text-xs text-gray-400 dark:text-zinc-500 py-4 text-center">
          {t('auto_snapshots.target.single.empty')}
        </p>
      )}
      {!loading && !error && filtered.length > 0 && (
        <div className="max-h-64 overflow-y-auto border border-gray-200 dark:border-zinc-700 rounded divide-y divide-gray-100 dark:divide-zinc-800">
          {filtered.slice(0, 200).map(vm => {
            const kind = vm.type === 'lxc' || vm.kind === 'lxc' ? 'lxc' : 'qemu'
            const key = `${vm.portal_node_id ?? 0}:${vm.vmid}:${kind}`
            const checked = selectedSet.has(key)
            return (
              <label key={VmKey(vm)} className="flex items-center gap-2 px-3 py-1.5 text-xs hover:bg-gray-50 dark:hover:bg-zinc-800/50 cursor-pointer">
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => toggle(vm)}
                  className="w-3.5 h-3.5 rounded border-gray-300 dark:border-zinc-600 text-orange-500 focus:ring-orange-500"
                />
                <span className="font-mono text-gray-500 dark:text-zinc-400 w-12 shrink-0">{vm.vmid}</span>
                <span className={`text-[10px] uppercase px-1 rounded shrink-0 ${kind === 'lxc' ? 'bg-purple-100 dark:bg-purple-900/40 text-purple-700 dark:text-purple-300' : 'bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300'}`}>
                  {kind}
                </span>
                <span className="text-gray-700 dark:text-zinc-300 truncate flex-1">{vm.name ?? '–'}</span>
                <span className="text-gray-400 dark:text-zinc-500 text-[11px] shrink-0">{vm.node}</span>
              </label>
            )
          })}
          {filtered.length > 200 && (
            <p className="px-3 py-2 text-[11px] text-gray-400 dark:text-zinc-500">
              {t('auto_snapshots.target.single.truncated', { count: filtered.length - 200 })}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Pool-Tab ───────────────────────────────────────────────────────────────

function PoolTab({ value, onChange }) {
  const { t } = useTranslation()
  const [pools, setPools] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    poolsApi.list()
      .then((data) => { if (alive) { setPools(Array.isArray(data) ? data : []); setError('') } })
      .catch(() => { if (alive) setError(t('common.error_generic')) })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [t])

  const selected = new Set(value ?? [])

  const toggle = (id) => {
    if (selected.has(id)) onChange((value ?? []).filter(v => v !== id))
    else onChange([...(value ?? []), id])
  }

  return (
    <div className="space-y-2">
      {loading && <p className="text-xs text-gray-500 dark:text-zinc-400">{t('common.loading')}</p>}
      {error && <p className="text-xs text-red-500">{error}</p>}
      {!loading && !error && pools.length === 0 && (
        <p className="text-xs text-gray-400 dark:text-zinc-500 py-4 text-center">
          {t('auto_snapshots.target.pool.empty')}
        </p>
      )}
      {!loading && pools.length > 0 && (
        <div className="max-h-64 overflow-y-auto border border-gray-200 dark:border-zinc-700 rounded divide-y divide-gray-100 dark:divide-zinc-800">
          {pools.map(pool => (
            <label key={pool.id} className="flex items-center gap-2 px-3 py-2 text-xs hover:bg-gray-50 dark:hover:bg-zinc-800/50 cursor-pointer">
              <input
                type="checkbox"
                checked={selected.has(pool.id)}
                onChange={() => toggle(pool.id)}
                className="w-3.5 h-3.5 rounded border-gray-300 dark:border-zinc-600 text-orange-500 focus:ring-orange-500"
              />
              <span className="font-medium text-gray-700 dark:text-zinc-300 flex-1">{pool.name}</span>
              {pool.description && (
                <span className="text-gray-400 dark:text-zinc-500 text-[11px] truncate max-w-[180px]">
                  {pool.description}
                </span>
              )}
            </label>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── Node-Tab ───────────────────────────────────────────────────────────────

function NodeTab({ value, onChange }) {
  const { t } = useTranslation()
  const [nodes, setNodes] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    getNodes()
      .then((data) => { if (alive) { setNodes(Array.isArray(data) ? data : []); setError('') } })
      .catch(() => { if (alive) setError(t('common.error_generic')) })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [t])

  const selected = new Set(value ?? [])

  const toggle = (id) => {
    if (selected.has(id)) onChange((value ?? []).filter(v => v !== id))
    else onChange([...(value ?? []), id])
  }

  // Dedupliziere nach portal_node_id (es können mehrere Cluster-Member auf eine
  // Portal-Node-Zeile zeigen).
  const uniquePortalNodes = useMemo(() => {
    const seen = new Map()
    for (const n of nodes) {
      const pid = n.portal_node_id
      if (pid == null || seen.has(pid)) continue
      seen.set(pid, n)
    }
    return Array.from(seen.values())
  }, [nodes])

  return (
    <div className="space-y-2">
      {loading && <p className="text-xs text-gray-500 dark:text-zinc-400">{t('common.loading')}</p>}
      {error && <p className="text-xs text-red-500">{error}</p>}
      {!loading && uniquePortalNodes.length === 0 && (
        <p className="text-xs text-gray-400 dark:text-zinc-500 py-4 text-center">
          {t('auto_snapshots.target.node.empty')}
        </p>
      )}
      {!loading && uniquePortalNodes.length > 0 && (
        <div className="max-h-64 overflow-y-auto border border-gray-200 dark:border-zinc-700 rounded divide-y divide-gray-100 dark:divide-zinc-800">
          {uniquePortalNodes.map(node => (
            <label key={node.portal_node_id} className="flex items-center gap-2 px-3 py-2 text-xs hover:bg-gray-50 dark:hover:bg-zinc-800/50 cursor-pointer">
              <input
                type="checkbox"
                checked={selected.has(node.portal_node_id)}
                onChange={() => toggle(node.portal_node_id)}
                className="w-3.5 h-3.5 rounded border-gray-300 dark:border-zinc-600 text-orange-500 focus:ring-orange-500"
              />
              <span className="font-medium text-gray-700 dark:text-zinc-300 flex-1">
                {node.portal_node_name ?? node.node}
              </span>
              {node.node && node.node !== node.portal_node_name && (
                <span className="text-gray-400 dark:text-zinc-500 text-[11px]">{node.node}</span>
              )}
            </label>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── Tag-Tab ────────────────────────────────────────────────────────────────

function TagTab({ value, onChange }) {
  const { t } = useTranslation()
  const [input, setInput] = useState('')

  const addTag = () => {
    const tag = input.trim()
    if (!tag) return
    if ((value ?? []).includes(tag)) return
    if ((value ?? []).length >= 10) return
    onChange([...(value ?? []), tag])
    setInput('')
  }

  const removeTag = (tag) => {
    onChange((value ?? []).filter(v => v !== tag))
  }

  return (
    <div className="space-y-2">
      <p className="text-[11px] text-gray-400 dark:text-zinc-500">
        {t('auto_snapshots.target.tag.hint')}
      </p>
      <div className="flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addTag() } }}
          placeholder={t('auto_snapshots.target.tag.placeholder')}
          maxLength={32}
          className={inputCls}
        />
        <button type="button" onClick={addTag} disabled={(value ?? []).length >= 10} className="btn-secondary text-xs shrink-0">
          {t('common.add', 'Hinzufügen')}
        </button>
      </div>
      {(value ?? []).length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {(value ?? []).map(tag => (
            <span key={tag} className="inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded-full bg-gray-100 dark:bg-zinc-800 text-gray-700 dark:text-zinc-300 border border-gray-200 dark:border-zinc-700">
              {tag}
              <button
                type="button"
                onClick={() => removeTag(tag)}
                aria-label={`Tag ${tag} entfernen`}
                className="hover:text-red-500 transition-colors"
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}
      {(value ?? []).length >= 10 && (
        <p className="text-[11px] text-portal-warn">
          {t('auto_snapshots.target.tag.max_reached')}
        </p>
      )}
    </div>
  )
}

// ─── Haupt-Komponente ───────────────────────────────────────────────────────

export default function TargetSelector({ value, onChange }) {
  const { t } = useTranslation()
  const [active, setActive] = useState('single')

  const spec = value ?? {
    singles: [],
    pool_ids: [],
    portal_node_ids: [],
    tags: [],
    kind_filter: 'both',
  }

  const update = (key, val) => onChange({ ...spec, [key]: val })

  const tabCls = (id) =>
    `px-3 py-1.5 text-xs font-medium border-b-2 transition-colors flex items-center gap-1 ${
      active === id
        ? 'border-orange-500 text-gray-900 dark:text-zinc-100'
        : 'border-transparent text-gray-500 dark:text-zinc-400 hover:text-gray-700 dark:hover:text-zinc-200'
    }`

  return (
    <div className="space-y-3 border-t border-gray-100 dark:border-zinc-800 pt-3">
      <p className="text-xs font-medium text-gray-500 dark:text-zinc-400 uppercase tracking-wider">
        {t('auto_snapshots.target.title')} <span className="text-red-500">*</span>
      </p>

      {/* Tab-Leiste */}
      <div className="flex border-b border-gray-100 dark:border-zinc-800">
        <button type="button" onClick={() => setActive('single')} className={tabCls('single')}>
          {t('auto_snapshots.target.tab.single')}
          <CountBadge count={spec.singles?.length ?? 0} />
        </button>
        <button type="button" onClick={() => setActive('pool')} className={tabCls('pool')}>
          {t('auto_snapshots.target.tab.pool')}
          <CountBadge count={spec.pool_ids?.length ?? 0} />
        </button>
        <button type="button" onClick={() => setActive('node')} className={tabCls('node')}>
          {t('auto_snapshots.target.tab.node')}
          <CountBadge count={spec.portal_node_ids?.length ?? 0} />
        </button>
        <button type="button" onClick={() => setActive('tag')} className={tabCls('tag')}>
          {t('auto_snapshots.target.tab.tag')}
          <CountBadge count={spec.tags?.length ?? 0} />
        </button>
      </div>

      {/* Inhalt pro Tab */}
      {active === 'single' && (
        <SingleTab value={spec.singles} onChange={(v) => update('singles', v)} />
      )}
      {active === 'pool' && (
        <PoolTab value={spec.pool_ids} onChange={(v) => update('pool_ids', v)} />
      )}
      {active === 'node' && (
        <NodeTab value={spec.portal_node_ids} onChange={(v) => update('portal_node_ids', v)} />
      )}
      {active === 'tag' && (
        <TagTab value={spec.tags} onChange={(v) => update('tags', v)} />
      )}

      {/* Kind-Filter (immer sichtbar) */}
      <div>
        <label htmlFor="as-kind-filter" className="block text-xs font-medium text-gray-700 dark:text-zinc-300 mb-1">
          {t('auto_snapshots.target.kind_filter')}
        </label>
        <select
          id="as-kind-filter"
          value={spec.kind_filter ?? 'both'}
          onChange={(e) => update('kind_filter', e.target.value)}
          className={inputCls}
        >
          <option value="both">{t('auto_snapshots.target.kind_both')}</option>
          <option value="qemu">QEMU (VM)</option>
          <option value="lxc">LXC</option>
        </select>
      </div>
    </div>
  )
}
