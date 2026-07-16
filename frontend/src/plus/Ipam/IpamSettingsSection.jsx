// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-42 Phase 2: „Einstellungen"-Tab (Plus). Zwei Toggles (US-11):
//  · global_enabled           – zustandsbehaftete IPAM-Ebene an/aus (Default AUS)
//  · strict_network_visibility – strikte Netz-Sicht (Default AUS; wirkt nur wenn global AN)
// Muster PROJ-50 MasterToggleSection.
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { formatApiError } from '../../api/errors'
import { useIpamConfig, useUpdateIpamConfig } from './hooks'

function Toggle({ checked, onChange, disabled }) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      disabled={disabled}
      className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-portal-accent disabled:opacity-50 ${
        checked ? 'bg-portal-success' : 'bg-portal-bg3'
      }`}
    >
      <span
        className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
          checked ? 'translate-x-6' : 'translate-x-1'
        }`}
      />
    </button>
  )
}

export default function IpamSettingsSection() {
  const { t } = useTranslation()
  const { data: config, isLoading } = useIpamConfig()
  const updateMut = useUpdateIpamConfig()
  const [error, setError] = useState('')

  const globalEnabled = config?.global_enabled ?? false
  const strict = config?.strict_network_visibility ?? false

  const patch = async (payload) => {
    setError('')
    try {
      await updateMut.mutateAsync(payload)
    } catch (err) {
      setError(formatApiError(err, t('common.error_generic')))
    }
  }

  if (isLoading) return <p className="text-sm text-gray-400 dark:text-zinc-500 py-4">{t('common.loading')}</p>

  return (
    <div className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-700 rounded-lg p-4 space-y-4 max-w-2xl">
      {/* Global an/aus */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-sm font-medium text-gray-900 dark:text-zinc-100">{t('ipam.settings.global_title')}</p>
          <p className="text-xs text-portal-text2 mt-0.5">{t('ipam.settings.global_hint')}</p>
        </div>
        <Toggle
          checked={globalEnabled}
          disabled={updateMut.isPending}
          onChange={(v) => patch({ global_enabled: v })}
        />
      </div>

      {/* Strikte Netz-Sicht */}
      <div className="flex items-start justify-between gap-4 pt-3 border-t border-gray-100 dark:border-zinc-800">
        <div>
          <p className={`text-sm font-medium ${globalEnabled ? 'text-gray-900 dark:text-zinc-100' : 'text-gray-400 dark:text-zinc-500'}`}>
            {t('ipam.settings.strict_title')}
          </p>
          <p className="text-xs text-portal-text2 mt-0.5">{t('ipam.settings.strict_hint')}</p>
          {!globalEnabled && (
            <p className="text-[11px] text-portal-warn mt-1">{t('ipam.settings.strict_needs_global')}</p>
          )}
        </div>
        <Toggle
          checked={strict}
          disabled={updateMut.isPending || !globalEnabled}
          onChange={(v) => patch({ strict_network_visibility: v })}
        />
      </div>

      {error && <p className="text-sm text-portal-danger">{error}</p>}
    </div>
  )
}
