// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-93: Playbook-Editor-Tab (in AutomationPage gerendert, gated
// useCapability('ansible_editor') && isAdmin). Schaltet zwischen Definitions-
// Liste und dem SoT-Formular (Neu / Bearbeiten). Beim Bearbeiten wird das
// strukturierte Modell aus dem .p3editor.json-Sidecar geladen (AC-ROUND-1).
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useDefinition } from './hooks'
import { ensureTaskUids } from './model'
import DefinitionList from './DefinitionList'
import AnsibleEditorForm from './AnsibleEditorForm'
import Watermark from '../../components/common/Watermark'

// Geladenes Modell normalisieren: Tasks stabile _uids geben (Reorder-Stabilität)
// + id als „berührt" markieren (kein Auto-Ableiten beim Bearbeiten).
function normalizeForForm(model) {
  if (!model) return model
  return { ...ensureTaskUids(model), _idTouched: true }
}

function EditLoader({ id, onClose, onSaved }) {
  const { t } = useTranslation()
  const { data, isLoading, error } = useDefinition(id)
  if (isLoading) return <p className="text-sm text-portal-text2">{t('common.loading')}</p>
  if (error || !data) return <p className="text-sm text-portal-danger">{t('ansible_editor.load_error')}</p>
  return (
    <AnsibleEditorForm initialModel={normalizeForForm(data)} isEdit onClose={onClose} onSaved={onSaved} />
  )
}

export default function AnsibleEditorTab() {
  // view: 'list' | 'new' | { edit: id }
  const [view, setView] = useState('list')
  const backToList = () => setView('list')

  return (
    <div className="flex-1 min-h-0 overflow-y-auto">
      {view === 'list' && (
        <DefinitionList onNew={() => setView('new')} onEdit={(id) => setView({ edit: id })} />
      )}

      {view === 'new' && (
        <div className="p-6">
          <AnsibleEditorForm isEdit={false} onClose={backToList} onSaved={backToList} />
          <Watermark />
        </div>
      )}

      {typeof view === 'object' && view.edit && (
        <div className="p-6">
          <EditLoader id={view.edit} onClose={backToList} onSaved={backToList} />
          <Watermark />
        </div>
      )}
    </div>
  )
}
