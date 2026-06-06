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
    network: { bridge: 'vmbr0' },
    tags: [],
    start_after_create: true,
  }
}

export default function StackFormEditor({ model, onChange, nodeOptions = [], templateOptions = [] }) {
  const { t } = useTranslation()
  const resources = Array.isArray(model.resources) ? model.resources : []

  const setMeta = (key, val) => onChange({ ...model, [key]: val })

  const setResource = (idx, next) => {
    const arr = resources.slice()
    arr[idx] = next
    onChange({ ...model, resources: arr })
  }

  const addVm = () => onChange({ ...model, resources: [...resources, emptyVm()] })

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
          <label className="flex flex-col gap-1 text-xs md:col-span-1">
            <span className="text-portal-text2 font-medium">{t('stacks.form.field.stack_name')} *</span>
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

      {/* VM-Ressourcen */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-portal-white">
            {t('stacks.form.resources_title')} <span className="text-portal-text3 font-normal">({resources.length})</span>
          </h3>
        </div>

        {resources.length === 0 ? (
          <button
            type="button"
            onClick={addVm}
            className="w-full border-2 border-dashed border-portal-border rounded-lg py-8 text-sm text-portal-text2 hover:border-portal-accent hover:text-portal-white transition-colors"
          >
            + {t('stacks.form.add_first_vm')}
          </button>
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
              />
            ))}
            <button type="button" onClick={addVm} className="btn-secondary w-full">
              + {t('stacks.form.add_vm_btn')}
            </button>
          </>
        )}
      </div>
    </div>
  )
}
