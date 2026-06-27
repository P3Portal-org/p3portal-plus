// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-74: Modal zum Anlegen eines Config-Snapshots (AC-CREATE-1..8).
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { createSnapshot } from './api'

function defaultName(proxmoxNode, vmid) {
  const now = new Date()
  const pad = n => String(n).padStart(2, '0')
  const ts = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}`
  return `snapshot-config-${proxmoxNode}-${vmid}-${ts}`
}

export default function ConfigSnapshotCreateModal({ portalNodeId, proxmoxNode, vmid, kind, onClose, onCreated }) {
  const { t } = useTranslation()
  const [name, setName] = useState(defaultName(proxmoxNode, vmid))
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const handleSubmit = async e => {
    e.preventDefault()
    if (!note.trim()) return
    setBusy(true)
    setError(null)
    try {
      const snap = await createSnapshot({ portalNodeId, proxmoxNode, vmid, kind, note: note.trim(), name: name.trim() || undefined })
      onCreated(snap)
    } catch (err) {
      const detail = err?.response?.data?.detail
      const status = err?.response?.status
      console.error('[ConfigSnapshot] create failed', { status, detail, err })
      let msg
      if (Array.isArray(detail)) {
        msg = detail.map(d => d.msg || String(d)).join('; ')
      } else if (typeof detail === 'string' && detail) {
        msg = detail
      } else if (status) {
        msg = `HTTP ${status}: ${t('config_snapshots.create_error')}`
      } else {
        msg = t('config_snapshots.create_error')
      }
      setError(msg)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-700 rounded-lg w-full max-w-lg mx-4 shadow-xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200 dark:border-zinc-700">
          <h2 className="text-sm font-semibold text-gray-900 dark:text-zinc-100">{t('config_snapshots.create_title')}</h2>
          <button onClick={onClose} className="btn-ghost text-gray-400 hover:text-gray-600 dark:text-zinc-500 dark:hover:text-zinc-300" aria-label={t('common.close')}>✕</button>
        </div>

        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          {/* Name */}
          <div>
            <label htmlFor="snap-name" className="block text-xs font-medium text-gray-700 dark:text-zinc-300 mb-1">
              {t('config_snapshots.field_name')}
            </label>
            <input
              id="snap-name"
              type="text"
              maxLength={80}
              value={name}
              onChange={e => setName(e.target.value)}
              className="w-full text-sm bg-white dark:bg-zinc-800 border border-gray-300 dark:border-zinc-600 rounded-md px-3 py-2 text-gray-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-portal-accent"
            />
          </div>

          {/* Note (Pflicht) */}
          <div>
            <label htmlFor="snap-note" className="block text-xs font-medium text-gray-700 dark:text-zinc-300 mb-1">
              {t('config_snapshots.field_note')} <span className="text-portal-danger">*</span>
            </label>
            <textarea
              id="snap-note"
              maxLength={500}
              rows={3}
              value={note}
              onChange={e => setNote(e.target.value)}
              placeholder={t('config_snapshots.note_placeholder')}
              className="w-full text-sm bg-white dark:bg-zinc-800 border border-gray-300 dark:border-zinc-600 rounded-md px-3 py-2 text-gray-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-portal-accent resize-none"
            />
            {!note.trim() && busy === false && (
              <p className="mt-1 text-xs text-portal-danger">{t('config_snapshots.note_required')}</p>
            )}
            <p className="mt-1 text-xs text-gray-400 dark:text-zinc-500 text-right">{note.length}/500</p>
          </div>

          {error && <p className="text-xs text-portal-danger">{error}</p>}

          <div className="flex justify-end gap-2 pt-1">
            <button type="button" onClick={onClose} className="btn-secondary">{t('common.cancel')}</button>
            <button type="submit" disabled={busy || !note.trim()} className="btn-primary">
              {busy ? t('common.saving') : t('config_snapshots.create_submit')}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
