// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-92: Build-Editor-Tab (in ImageFactoryPage gerendert, gated
// useCapability('packer_editor')). Schaltet zwischen Definitions-Liste und dem
// SoT-Formular (Neu / Bearbeiten). Beim Bearbeiten wird das strukturierte Modell
// aus dem .p3editor.json-Sidecar geladen (AC-ROUND-1).
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useDefinition } from './hooks'
import { emptyInstaller } from './model'
import DefinitionList from './DefinitionList'
import PackerEditorForm from './PackerEditorForm'
import Watermark from '../../components/common/Watermark'

// Geladenes Modell für die Formular-Eingabe normalisieren: Passwort-Plain-Felder
// auf '' (write-only; gespeicherter Hash bleibt erhalten + steuert „●●● gesetzt").
function normalizeForForm(model) {
  if (!model) return model
  const next = { ...model, _idTouched: true }
  if (next.installer) {
    next.installer = {
      ...emptyInstaller(),
      ...next.installer,
      root_password_plain: '',
      user_password_plain: '',
    }
  }
  return next
}

function EditLoader({ id, onClose, onSaved }) {
  const { t } = useTranslation()
  const { data, isLoading, error } = useDefinition(id)
  if (isLoading) return <p className="text-sm text-portal-text2">{t('common.loading')}</p>
  if (error || !data) return <p className="text-sm text-portal-danger">{t('packer_editor.load_error')}</p>
  return (
    <PackerEditorForm
      initialModel={normalizeForForm(data)}
      isEdit
      onClose={onClose}
      onSaved={onSaved}
    />
  )
}

export default function PackerEditorTab() {
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
          <PackerEditorForm isEdit={false} onClose={backToList} onSaved={backToList} />
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
