// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-93: Play-Start-Node der n8n-Canvas (der „Trigger"). Hält den Play-Header
// (Ziel guest|localhost + become + gather_facts). Von hier geht die lineare
// Task-Kette aus (source-Handle rechts). Alle Eingaben tragen `nodrag`, damit
// React Flow den Node beim Tippen nicht verschiebt.
import { Handle, Position } from 'reactflow'
import { useTranslation } from 'react-i18next'
import { inputCls } from '../fields'

function PlayIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} className="w-4 h-4 shrink-0 text-portal-accent">
      <path d="M5 3l14 9-14 9V3z" />
    </svg>
  )
}

export default function PlayNode({ data }) {
  const { t } = useTranslation()
  const { header, onHeaderChange } = data

  return (
    <div className="w-[260px] rounded-xl border-2 border-portal-accent/60 bg-portal-bg shadow-md">
      <div className="flex items-center gap-1.5 px-3 py-2 border-b border-portal-border rounded-t-xl bg-portal-accent/5">
        <PlayIcon />
        <span className="text-xs font-semibold text-portal-text">{t('ansible_editor.canvas.play_title')}</span>
      </div>
      <div className="px-3 py-2.5 space-y-2.5">
        <div className="space-y-1">
          <span className="text-[11px] font-medium text-portal-text2">{t('ansible_editor.header.targets')}</span>
          <select className={inputCls + ' nodrag'} value={header?.targets || 'guest'}
            onChange={(e) => onHeaderChange({ targets: e.target.value })}>
            <option value="guest">{t('ansible_editor.header.target_guest')}</option>
            <option value="localhost">{t('ansible_editor.header.target_localhost')}</option>
          </select>
          <span className="block text-[10px] text-portal-text3 leading-tight">
            {header?.targets === 'localhost' ? t('ansible_editor.header.localhost_hint') : t('ansible_editor.header.targets_hint')}
          </span>
        </div>
        <label className="flex items-center gap-2 text-[11px] text-portal-text2 cursor-pointer select-none nodrag">
          <input type="checkbox" className="accent-[var(--accent)]" checked={!!header?.become}
            onChange={(e) => onHeaderChange({ become: e.target.checked })} />
          {t('ansible_editor.header.become')}
        </label>
        <label className="flex items-center gap-2 text-[11px] text-portal-text2 cursor-pointer select-none nodrag">
          <input type="checkbox" className="accent-[var(--accent)]" checked={!!header?.gather_facts}
            onChange={(e) => onHeaderChange({ gather_facts: e.target.checked })} />
          {t('ansible_editor.header.gather_facts')}
        </label>
      </div>
      <Handle type="source" position={Position.Right} className="!bg-portal-accent !w-2 !h-2 !border-0" />
    </div>
  )
}
