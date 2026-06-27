// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-76 Phase 1: Restore-Bestätigung einer alten Version (AC-UI-11, AC-VER-4).
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { formatApiError } from '../../api/errors'
import { restoreVersion } from './api'

export default function StackRestoreModal({ stackId, versionNumber, currentEtag, onRestored, onClose }) {
  const { t } = useTranslation()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const handleRestore = async () => {
    setBusy(true); setError(null)
    try {
      await restoreVersion(stackId, {
        versionNumber,
        changeSummary: t('stacks.restore.summary', { v: versionNumber }),
        expectedEtag: currentEtag,   // ETag-Concurrency-Schutz (BUG-76-2)
      })
      onRestored?.()
      onClose?.()
    } catch (err) {
      // 202 = pending approval (PUT-Pfad nutzt restore-version nicht direkt, aber defensiv)
      if (err?.response?.status === 409 && err.response.data?.current_etag) {
        setError(t('stacks.error.etag_mismatch'))
      } else {
        setError(formatApiError(err, t('common.error_generic')))
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-700 rounded-xl shadow-2xl w-full max-w-md flex flex-col">
        <div className="px-6 py-4 border-b border-gray-100 dark:border-zinc-800">
          <h2 className="text-base font-semibold text-gray-900 dark:text-zinc-100">{t('stacks.restore.title')}</h2>
        </div>
        <div className="px-6 py-4 space-y-3">
          <p className="text-sm text-gray-700 dark:text-zinc-300">{t('stacks.restore.body', { v: versionNumber })}</p>
          <p className="text-xs text-portal-text3">{t('stacks.restore.note')}</p>
          {error && (
            <p className="text-sm text-portal-danger bg-portal-danger/10 border border-portal-danger/30 rounded-lg px-3 py-2">{error}</p>
          )}
        </div>
        <div className="px-6 py-3 border-t border-gray-100 dark:border-zinc-800 flex items-center justify-end gap-2">
          <button type="button" onClick={onClose} disabled={busy} className="btn-secondary">{t('common.cancel')}</button>
          <button type="button" onClick={handleRestore} disabled={busy} className="btn-primary">
            {busy ? t('common.loading') : t('stacks.versions.restore_btn')}
          </button>
        </div>
      </div>
    </div>
  )
}
