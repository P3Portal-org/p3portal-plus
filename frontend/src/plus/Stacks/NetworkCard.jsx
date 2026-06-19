// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-87/89: eine stack-eigene Netz-Karte im Formular-Editor.
//  - kind="bridge": Node-Bridge (bpg proxmox_virtual_environment_network_linux_bridge),
//    node-lokal, kein cluster-weiter SDN-Apply.
//  - kind="vnet" (PROJ-89): stack-eigenes SDN-VNet (Simple-Zone + VNet + Subnet,
//    optional SNAT-Egress). Cluster-weite Wirkung (globaler `PUT /cluster/sdn`).

const inputCls =
  'w-full px-2 py-1.5 text-sm rounded-md border border-portal-border bg-portal-bg2 text-portal-text focus:outline-none focus:ring-1 focus:ring-portal-accent'

// Node-Bridge-Name wie Backend `_BRIDGE_NAME_RE` (vmbrN, 1–4 Ziffern).
const BRIDGE_RE = /^vmbr\d{1,4}$/
// SDN-ID (VNet-/Zone-Name) wie Backend `_SDN_ID_RE` (≤8 alnum, führender Buchstabe).
const SDN_ID_RE = /^[A-Za-z][A-Za-z0-9]{0,7}$/

// Frische Skelette je kind (beim Umschalten gesetzt → keine stale Felder).
function emptyBridge() {
  return { kind: 'bridge', name: '', node: '', vlan_aware: false }
}
function emptyVnet() {
  return { kind: 'vnet', name: '', zone: '', subnet_cidr: '', subnet_gateway: '', snat: false }
}

/**
 * NetworkCard – ein stack-owned Netz (Bridge oder SDN-VNet). Discriminated union
 * über `kind`. Felder werden über `onChange(index, next)` zurückgemeldet (Muster
 * StackResourceCard). Beim kind-Wechsel wird auf ein frisches Skelett gesetzt.
 */
export default function NetworkCard({ t, net, index, nodeOptions = [], onChange, onRemove }) {
  const n = net || {}
  const kind = n.kind || 'bridge'
  const isVnet = kind === 'vnet'
  const set = (key, val) => onChange(index, { ...n, [key]: val })
  const switchKind = (next) => onChange(index, next === 'vnet' ? emptyVnet() : emptyBridge())

  const nodeNames = [...new Set((nodeOptions || []).filter(Boolean))]
  const bridgeNameInvalid = !isVnet && n.name && !BRIDGE_RE.test(n.name)
  const vnetNameInvalid = isVnet && n.name && !SDN_ID_RE.test(n.name)
  const zoneInvalid = isVnet && n.zone && !SDN_ID_RE.test(n.zone)

  const title = isVnet ? t('stacks.networks.card_title_vnet') : t('stacks.networks.card_title')

  return (
    <div className="border border-portal-border rounded-lg bg-portal-bg2 p-3 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <h4 className="text-sm font-semibold text-gray-900 dark:text-zinc-100 flex items-center gap-2 min-w-0">
          <span className="text-portal-text3">#{index + 1}</span>
          <span className="shrink-0">{title}</span>
          {n.name ? <span className="text-portal-text2 font-normal truncate">— {n.name}</span> : null}
        </h4>
        <button
          type="button"
          onClick={() => onRemove(index)}
          className="btn-table-danger shrink-0"
          aria-label={t('stacks.networks.remove')}
        >{t('common.remove')}</button>
      </div>

      <div className="grid grid-cols-2 gap-3">
        {/* Typ: bridge (node-lokal) oder vnet (SDN, cluster-weit, PROJ-89) */}
        <label className="flex flex-col gap-1 text-xs">
          <span className="text-portal-text2 font-medium">{t('stacks.networks.field.kind')}</span>
          <select
            className={inputCls}
            value={kind}
            onChange={(e) => switchKind(e.target.value)}
          >
            <option value="bridge">{t('stacks.networks.kind.bridge')}</option>
            <option value="vnet">{t('stacks.networks.kind.vnet')}</option>
          </select>
        </label>

        <label className="flex flex-col gap-1 text-xs">
          <span className="text-portal-text2 font-medium">{t('stacks.networks.field.name')}</span>
          <input
            className={inputCls}
            value={n.name ?? ''}
            placeholder={isVnet ? 'vnet0' : 'vmbr10'}
            onChange={(e) => set('name', e.target.value)}
          />
          {bridgeNameInvalid && (
            <span className="text-[11px] text-portal-danger">{t('stacks.networks.name_hint')}</span>
          )}
          {vnetNameInvalid && (
            <span className="text-[11px] text-portal-danger">{t('stacks.networks.vnet_name_hint')}</span>
          )}
        </label>

        {!isVnet && (
          <>
            {/* Bridge: node-lokal */}
            <label className="flex flex-col gap-1 text-xs">
              <span className="text-portal-text2 font-medium">{t('stacks.networks.field.node')}</span>
              {nodeNames.length > 0 ? (
                <select className={inputCls} value={n.node ?? ''} onChange={(e) => set('node', e.target.value)}>
                  <option value="">{t('stacks.form.select_ph')}</option>
                  {nodeNames.map((nd) => <option key={nd} value={nd}>{nd}</option>)}
                </select>
              ) : (
                <input className={inputCls} value={n.node ?? ''} onChange={(e) => set('node', e.target.value)} />
              )}
            </label>

            <label className="flex flex-col gap-1 text-xs">
              <span className="text-portal-text2 font-medium">{t('stacks.networks.field.mtu')}</span>
              <input
                type="number"
                min={1280}
                max={65520}
                className={inputCls}
                value={n.mtu ?? ''}
                placeholder={t('stacks.networks.mtu_ph')}
                onChange={(e) => set('mtu', e.target.value === '' ? undefined : Number(e.target.value))}
              />
            </label>

            <label className="flex items-center gap-2 text-xs col-span-2 mt-1">
              <input
                type="checkbox"
                className="accent-portal-accent"
                checked={!!n.vlan_aware}
                onChange={(e) => set('vlan_aware', e.target.checked)}
              />
              <span className="text-portal-text2 font-medium">{t('stacks.networks.field.vlan_aware')}</span>
            </label>

            <label className="flex flex-col gap-1 text-xs col-span-2">
              <span className="text-portal-text2 font-medium">{t('stacks.networks.field.comment')}</span>
              <input
                className={inputCls}
                value={n.comment ?? ''}
                maxLength={255}
                onChange={(e) => set('comment', e.target.value || undefined)}
              />
            </label>
          </>
        )}

        {isVnet && (
          <>
            {/* SDN-VNet (PROJ-89): eigene Simple-Zone + Subnet, optional SNAT-Egress */}
            <label className="flex flex-col gap-1 text-xs">
              <span className="text-portal-text2 font-medium">{t('stacks.networks.field.zone')}</span>
              <input
                className={inputCls}
                value={n.zone ?? ''}
                placeholder="zone0"
                onChange={(e) => set('zone', e.target.value)}
              />
              {zoneInvalid && (
                <span className="text-[11px] text-portal-danger">{t('stacks.networks.zone_hint')}</span>
              )}
            </label>

            <label className="flex flex-col gap-1 text-xs">
              <span className="text-portal-text2 font-medium">{t('stacks.networks.field.subnet_cidr')}</span>
              <input
                className={inputCls}
                value={n.subnet_cidr ?? ''}
                placeholder="10.10.0.0/24"
                onChange={(e) => set('subnet_cidr', e.target.value)}
              />
            </label>

            <label className="flex flex-col gap-1 text-xs">
              <span className="text-portal-text2 font-medium">{t('stacks.networks.field.subnet_gateway')}</span>
              <input
                className={inputCls}
                value={n.subnet_gateway ?? ''}
                placeholder="10.10.0.1"
                onChange={(e) => set('subnet_gateway', e.target.value)}
              />
            </label>

            <label className="flex items-center gap-2 text-xs col-span-2 mt-1">
              <input
                type="checkbox"
                className="accent-portal-accent"
                checked={!!n.snat}
                onChange={(e) => set('snat', e.target.checked)}
              />
              <span className="text-portal-text2 font-medium">{t('stacks.networks.field.snat')}</span>
            </label>
            <p className="text-[11px] text-portal-text3 col-span-2 -mt-1">{t('stacks.networks.snat_hint')}</p>

            <div className="col-span-2 rounded-md border border-portal-warn/40 bg-portal-warn/10 p-2 text-[11px] text-portal-warn">
              {t('stacks.networks.vnet_cluster_warn')}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
