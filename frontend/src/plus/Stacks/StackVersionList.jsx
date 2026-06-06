// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-76 Phase 1: Versionshistorie-Tab mit Diff (A-vs-aktuell + A-vs-B) und Restore (AC-UI-9).
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useStackVersions } from './hooks'
import StackDiffModal from './StackDiffModal'
import StackRestoreModal from './StackRestoreModal'

export default function StackVersionList({ stackId, canWrite, currentEtag, onRestored }) {
  const { t } = useTranslation()
  const { data, isLoading, error } = useStackVersions(stackId)
  const versions = data ?? []

  const [selected, setSelected] = useState([])          // up to 2 version_numbers
  const [diff, setDiff] = useState(null)                // { from, to, fromLabel, toLabel }
  const [restoreV, setRestoreV] = useState(null)

  const toggle = (vn) => {
    setSelected((prev) => {
      if (prev.includes(vn)) return prev.filter((x) => x !== vn)
      if (prev.length >= 2) return [prev[1], vn]
      return [...prev, vn]
    })
  }

  const compareSelected = () => {
    if (selected.length !== 2) return
    const [a, b] = [...selected].sort((x, y) => x - y)
    setDiff({ from: `v${a}`, to: `v${b}`, fromLabel: `v${a}`, toLabel: `v${b}` })
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <p className="text-xs text-portal-text2">{t('stacks.versions.hint')}</p>
        <div className="flex-1" />
        <button
          onClick={compareSelected}
          disabled={selected.length !== 2}
          className="btn-secondary disabled:opacity-40"
        >
          {t('stacks.versions.compare_btn')} {selected.length === 2 ? `(v${[...selected].sort((a,b)=>a-b).join(' ↔ v')})` : ''}
        </button>
      </div>

      {isLoading ? (
        <p className="text-sm text-portal-text2">{t('common.loading')}</p>
      ) : error ? (
        <p className="text-sm text-portal-danger">{t('common.error_generic')}</p>
      ) : versions.length === 0 ? (
        <p className="text-sm text-portal-text3 italic">{t('stacks.versions.empty')}</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-portal-text3 border-b border-portal-border text-left">
              <th className="px-3 py-2 w-8"></th>
              <th className="px-3 py-2 font-medium">{t('stacks.versions.col_version')}</th>
              <th className="px-3 py-2 font-medium">{t('stacks.versions.col_summary')}</th>
              <th className="px-3 py-2 font-medium">{t('stacks.versions.col_by')}</th>
              <th className="px-3 py-2 font-medium">{t('stacks.versions.col_at')}</th>
              <th className="px-3 py-2 font-medium text-right">{t('stacks.col.actions')}</th>
            </tr>
          </thead>
          <tbody>
            {versions.map((v) => (
              <tr key={v.version_number} className="border-b border-portal-border/50 hover:bg-portal-bg3/30">
                <td className="px-3 py-2">
                  <input
                    type="checkbox"
                    checked={selected.includes(v.version_number)}
                    onChange={() => toggle(v.version_number)}
                    className="accent-[var(--accent)]"
                    aria-label={`v${v.version_number}`}
                  />
                </td>
                <td className="px-3 py-2 font-mono text-portal-text">v{v.version_number}</td>
                <td className="px-3 py-2 text-portal-text2">{v.change_summary || '—'}</td>
                <td className="px-3 py-2 text-portal-text2">{v.edited_by_username || (v.edited_by_user_id ? `#${v.edited_by_user_id}` : '—')}</td>
                <td className="px-3 py-2 text-portal-text3 text-xs">{(v.created_at || '').replace('T', ' ').slice(0, 16)}</td>
                <td className="px-3 py-2 text-right whitespace-nowrap">
                  <button
                    onClick={() => setDiff({ from: `v${v.version_number}`, to: 'current', fromLabel: `v${v.version_number}`, toLabel: t('stacks.versions.current') })}
                    className="btn-table"
                  >
                    {t('stacks.versions.diff_btn')}
                  </button>
                  {canWrite && (
                    <button onClick={() => setRestoreV(v.version_number)} className="btn-table ml-1">
                      {t('stacks.versions.restore_btn')}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {diff && (
        <StackDiffModal
          stackId={stackId}
          from={diff.from}
          to={diff.to}
          fromLabel={diff.fromLabel}
          toLabel={diff.toLabel}
          onClose={() => setDiff(null)}
        />
      )}

      {restoreV != null && (
        <StackRestoreModal
          stackId={stackId}
          versionNumber={restoreV}
          currentEtag={currentEtag}
          onRestored={onRestored}
          onClose={() => setRestoreV(null)}
        />
      )}
    </div>
  )
}
