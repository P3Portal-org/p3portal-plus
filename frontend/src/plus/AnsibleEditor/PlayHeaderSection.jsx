// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-93: Play-Header (Ziel/Verhalten, AC-PLAY). targets guest|localhost +
// become + gather_facts. Bei localhost ein ehrlicher MVP-Hinweis (AC-PLAY-3).
import { useTranslation } from 'react-i18next'
import { Field, Section, Toggle, inputCls } from './fields'

export default function PlayHeaderSection({ header, onChange }) {
  const { t } = useTranslation()
  const h = header || {}
  const isLocalhost = h.targets === 'localhost'

  return (
    <Section title={t('ansible_editor.header.title')} desc={t('ansible_editor.header.desc')}>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <Field label={t('ansible_editor.header.targets')} hint={t('ansible_editor.header.targets_hint')}>
          <select
            className={inputCls}
            value={h.targets ?? 'guest'}
            onChange={(e) => onChange({ targets: e.target.value })}
          >
            <option value="guest">{t('ansible_editor.header.target_guest')}</option>
            <option value="localhost">{t('ansible_editor.header.target_localhost')}</option>
          </select>
        </Field>
        <div className="flex flex-col gap-2 justify-center">
          <Toggle
            label={t('ansible_editor.header.become')}
            checked={!!h.become}
            onChange={(v) => onChange({ become: v })}
          />
          <Toggle
            label={t('ansible_editor.header.gather_facts')}
            checked={!!h.gather_facts}
            onChange={(v) => onChange({ gather_facts: v })}
          />
        </div>
      </div>
      {isLocalhost && (
        <p className="text-[11px] text-portal-warn rounded-md border border-portal-warn/30 bg-portal-warn/10 px-2 py-1.5 leading-snug">
          {t('ansible_editor.header.localhost_hint')}
        </p>
      )}
    </Section>
  )
}
