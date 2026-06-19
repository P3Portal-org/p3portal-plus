// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-76 Phase 1: Formular-Editor (Wizard) für Stacks (AC-UI-4).
// Bearbeitet ein strukturiertes Modell { name, description, version, resources[] }.
// Live-Sync mit dem YAML-Editor übernimmt die übergeordnete StackEditorPage.
import { useTranslation } from 'react-i18next'
import StackResourceCard from './StackResourceCard'
import NetworkCard from './NetworkCard'
import StackSecurityGroupCard from './StackSecurityGroupCard'

const inputCls =
  'w-full px-2 py-1.5 text-sm rounded-md border border-portal-border bg-portal-bg2 text-portal-text focus:outline-none focus:ring-1 focus:ring-portal-accent'

function emptyVm() {
  return {
    type: 'vm',
    name: '',
    node: '',
    template: '',
    count: 1,
    cores: 1,
    sockets: 1,
    memory: 2048,
    disk: 32,
    cpu_type: 'host',
    agent: true,
    network: { bridge: 'vmbr0' },
    tags: [],
    start_after_create: true,
  }
}

// PROJ-86: leerer LXC-Container (Defaults analog Backend-Schema; unprivileged AN).
function emptyLxc() {
  return {
    type: 'lxc',
    name: '',
    node: '',
    template: '',
    hostname: '',
    count: 1,
    cores: 1,
    memory: 512,
    swap: 512,
    rootfs_size: 8,
    rootfs_datastore: '',
    unprivileged: true,
    network: { bridge: 'vmbr0' },
    tags: [],
    start_after_create: true,
  }
}

// PROJ-87: leere stack-owned Bridge (Defaults analog Backend-Schema BridgeNetwork).
function emptyBridge() {
  return { kind: 'bridge', name: '', node: '', vlan_aware: false }
}

// PROJ-91: leere stack-owned Security-Group (Defaults analog Backend StackSecurityGroup).
function emptySecurityGroup() {
  return { name: '', rules: [] }
}

export default function StackFormEditor({
  model, onChange, nodeOptions = [], templateOptions = [],
  fwRefs = [], fwMacros = [], clusterSgNames = [],
}) {
  const { t } = useTranslation()
  const resources = Array.isArray(model.resources) ? model.resources : []
  // PROJ-87: stack-deklarierte Netze – Namen ins Bridge-Dropdown der Gäste (AC-MODEL-2).
  const networks = Array.isArray(model.networks) ? model.networks : []
  const stackNetworkNames = [...new Set(networks.map((n) => n?.name).filter(Boolean))]
  // PROJ-91: stack-eigene Security-Groups; ihre Namen + die bestehenden Cluster-SGs
  // speisen das group-Regel-Aktions-Dropdown der Gäste (AC-SG-2/3).
  const securityGroups = Array.isArray(model.security_groups) ? model.security_groups : []
  const stackSgNames = securityGroups.map((g) => g?.name).filter(Boolean)
  const sgActionNames = [...new Set([...stackSgNames, ...clusterSgNames])]

  const setMeta = (key, val) => onChange({ ...model, [key]: val })

  const setSg = (idx, next) => {
    const arr = securityGroups.slice()
    arr[idx] = next
    onChange({ ...model, security_groups: arr })
  }
  const addSg = () => onChange({ ...model, security_groups: [...securityGroups, emptySecurityGroup()] })
  const removeSg = (idx) => {
    const arr = securityGroups.slice()
    arr.splice(idx, 1)
    // Leere Liste nicht persistieren (reine VM/LXC-Stacks byte-genau).
    onChange({ ...model, security_groups: arr.length ? arr : undefined })
  }

  const setNetwork = (idx, next) => {
    const arr = networks.slice()
    arr[idx] = next
    onChange({ ...model, networks: arr })
  }
  const addNetwork = () => onChange({ ...model, networks: [...networks, emptyBridge()] })
  const removeNetwork = (idx) => {
    const arr = networks.slice()
    arr.splice(idx, 1)
    // Leere Liste nicht persistieren (reine VM/LXC-Stacks byte-genau).
    onChange({ ...model, networks: arr.length ? arr : undefined })
  }

  const setResource = (idx, next) => {
    const arr = resources.slice()
    arr[idx] = next
    onChange({ ...model, resources: arr })
  }

  const addVm = () => onChange({ ...model, resources: [...resources, emptyVm()] })
  const addLxc = () => onChange({ ...model, resources: [...resources, emptyLxc()] })

  const removeVm = (idx) => {
    const arr = resources.slice()
    arr.splice(idx, 1)
    onChange({ ...model, resources: arr })
  }

  const moveVm = (from, to) => {
    if (to < 0 || to >= resources.length) return
    const arr = resources.slice()
    const [item] = arr.splice(from, 1)
    arr.splice(to, 0, item)
    onChange({ ...model, resources: arr })
  }

  // VM duplizieren: tiefe Kopie direkt hinter dem Original, Name mit „-copy"-Suffix
  // (vermeidet sofortige Duplikat-Namen-Warnung).
  const duplicateVm = (idx) => {
    const src = resources[idx]
    if (!src) return
    const copy = JSON.parse(JSON.stringify(src))
    if (copy.name) copy.name = `${copy.name}-copy`
    // Hat die Quelle eine feste VMID, bekommt die Kopie die nächste FREIE VMID
    // im Stack (Quelle + 1, hochzählen bis frei) – kollidiert so weder mit der
    // Quelle noch mit anderen VMs. Ohne feste VMID bleibt die Kopie auf Auto.
    const srcVmid = Number(src.vmid)
    if (Number.isFinite(srcVmid)) {
      const used = new Set(
        resources.map((x) => Number(x.vmid)).filter((n) => Number.isFinite(n)),
      )
      let next = srcVmid + 1
      while (used.has(next)) next += 1
      copy.vmid = next
    }
    const arr = resources.slice()
    arr.splice(idx + 1, 0, copy)
    onChange({ ...model, resources: arr })
  }

  return (
    <div className="space-y-5">
      {/* Stack-Metadaten */}
      <div className="border border-portal-border rounded-lg bg-portal-bg2 p-4 space-y-3">
        <h3 className="text-sm font-semibold text-portal-white">{t('stacks.form.meta_title')}</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <label className="flex flex-col gap-1 text-xs md:col-span-1 [&_input]:border-portal-accent">
            <span className="text-portal-text2 font-medium">{t('stacks.form.field.stack_name')} <span className="text-portal-accent font-semibold">*</span></span>
            <input className={inputCls} value={model.name ?? ''} onChange={(e) => setMeta('name', e.target.value)} placeholder="webserver-cluster" />
          </label>
          <label className="flex flex-col gap-1 text-xs md:col-span-1">
            <span className="text-portal-text2 font-medium">{t('stacks.form.field.version')}</span>
            <input className={inputCls} value={model.version ?? '1.0.0'} onChange={(e) => setMeta('version', e.target.value)} />
          </label>
          <label className="flex flex-col gap-1 text-xs md:col-span-3">
            <span className="text-portal-text2 font-medium">{t('stacks.form.field.description')}</span>
            <input className={inputCls} value={model.description ?? ''} maxLength={500} onChange={(e) => setMeta('description', e.target.value)} />
          </label>
        </div>
      </div>

      {/* Ressourcen (VM + LXC) */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-portal-white">
            {t('stacks.form.resources_title')} <span className="text-portal-text3 font-normal">({resources.length})</span>
          </h3>
        </div>

        {resources.length === 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <button
              type="button"
              onClick={addVm}
              className="w-full border-2 border-dashed border-portal-border rounded-lg py-8 text-sm text-portal-text2 hover:border-portal-accent hover:text-portal-white transition-colors"
            >
              + {t('stacks.form.add_first_vm')}
            </button>
            <button
              type="button"
              onClick={addLxc}
              className="w-full border-2 border-dashed border-portal-border rounded-lg py-8 text-sm text-portal-text2 hover:border-portal-accent hover:text-portal-white transition-colors"
            >
              + {t('stacks.form.add_first_lxc')}
            </button>
          </div>
        ) : (
          <>
            {resources.map((r, idx) => (
              <StackResourceCard
                key={idx}
                resource={r}
                index={idx}
                total={resources.length}
                onChange={setResource}
                onRemove={removeVm}
                onMove={moveVm}
                onDuplicate={duplicateVm}
                nodeOptions={nodeOptions}
                templateOptions={templateOptions}
                stackNetworks={stackNetworkNames}
                fwRefs={fwRefs}
                fwMacros={fwMacros}
                securityGroupNames={sgActionNames}
              />
            ))}
            <div className="flex flex-wrap gap-2">
              <button type="button" onClick={addVm} className="btn-secondary flex-1">
                + {t('stacks.form.add_vm_btn')}
              </button>
              <button type="button" onClick={addLxc} className="btn-secondary flex-1">
                + {t('stacks.form.add_lxc_btn')}
              </button>
            </div>
          </>
        )}
      </div>

      {/* PROJ-87: Stack-eigene Netzwerke (Bridge; VNet als Folge-Phase deaktiviert) */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-portal-white">
            {t('stacks.networks.title')} <span className="text-portal-text3 font-normal">({networks.length})</span>
          </h3>
        </div>
        <p className="text-xs text-portal-text2">{t('stacks.networks.hint')}</p>

        {networks.length === 0 ? (
          <button
            type="button"
            onClick={addNetwork}
            className="w-full border-2 border-dashed border-portal-border rounded-lg py-6 text-sm text-portal-text2 hover:border-portal-accent hover:text-portal-white transition-colors"
          >
            + {t('stacks.networks.add_first')}
          </button>
        ) : (
          <>
            {networks.map((n, idx) => (
              <NetworkCard
                key={idx}
                t={t}
                net={n}
                index={idx}
                nodeOptions={nodeOptions}
                onChange={setNetwork}
                onRemove={removeNetwork}
              />
            ))}
            <button type="button" onClick={addNetwork} className="btn-secondary w-full">
              + {t('stacks.networks.add')}
            </button>
          </>
        )}
      </div>

      {/* PROJ-91: Stack-eigene Security-Groups (wiederverwendbare Regelsätze) */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-portal-white">
            {t('stacks.security_groups.title')} <span className="text-portal-text3 font-normal">({securityGroups.length})</span>
          </h3>
        </div>
        <p className="text-xs text-portal-text2">{t('stacks.security_groups.hint')}</p>

        {securityGroups.length === 0 ? (
          <button
            type="button"
            onClick={addSg}
            className="w-full border-2 border-dashed border-portal-border rounded-lg py-6 text-sm text-portal-text2 hover:border-portal-accent hover:text-portal-white transition-colors"
          >
            + {t('stacks.security_groups.add_first')}
          </button>
        ) : (
          <>
            {securityGroups.map((g, idx) => (
              <StackSecurityGroupCard
                key={idx}
                t={t}
                group={g}
                index={idx}
                refs={fwRefs}
                macros={fwMacros}
                onChange={setSg}
                onRemove={removeSg}
              />
            ))}
            <button type="button" onClick={addSg} className="btn-secondary w-full">
              + {t('stacks.security_groups.add')}
            </button>
          </>
        )}
      </div>
    </div>
  )
}
