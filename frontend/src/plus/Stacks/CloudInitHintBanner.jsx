// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-85: Hinweis-Banner im YAML- UND Formular-Tab (AC-UI-2). Erklärt, warum
// der Login NICHT im YAML steht (liegt im verschlüsselten Cloud-Init-Store).
import { useTranslation } from 'react-i18next'

/**
 * @param {object|undefined} data CloudInitConfigResponse ({ default, overrides[] })
 *   oder undefined (neuer/ungespeicherter Stack → immer "inaktiv").
 */
export default function CloudInitHintBanner({ data }) {
  const { t } = useTranslation()
  const defaultActive = !!data?.default?.enabled
  const activeOverrides = (data?.overrides || []).filter((o) => o.enabled).length
  const active = defaultActive || activeOverrides > 0

  if (!active) {
    return (
      <div className="rounded-md border border-portal-border bg-portal-bg2 px-3 py-2 text-xs text-portal-text2">
        {t('stacks.cloudinit.banner_inactive')}
      </div>
    )
  }

  const parts = []
  if (defaultActive) parts.push(t('stacks.cloudinit.banner_default'))
  if (activeOverrides > 0) parts.push(t('stacks.cloudinit.banner_overrides', { count: activeOverrides }))

  return (
    <div className="rounded-md border border-portal-info/40 bg-portal-info/10 px-3 py-2 text-xs text-portal-info">
      {t('stacks.cloudinit.banner_active', { detail: parts.join(' + ') })}
    </div>
  )
}
