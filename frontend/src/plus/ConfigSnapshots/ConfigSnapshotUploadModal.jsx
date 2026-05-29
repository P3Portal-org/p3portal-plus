// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-74: Upload-Modal für Config-Snapshots (AC-UPLOAD-1..10).
import { useState, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { uploadSnapshot } from './api'

const ALLOWED_EXT = /\.(conf|txt)$/i
const MAX_SIZE = 100 * 1024 // 100 KB

export default function ConfigSnapshotUploadModal({ portalNodeId, proxmoxNode, vmid, kind, onClose, onUploaded }) {
  const { t } = useTranslation()
  const [file, setFile] = useState(null)
  const [note, setNote] = useState('')
  const [action, setAction] = useState('upload_only')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [validationError, setValidationError] = useState(null)
  const fileInputRef = useRef(null)

  const validateFile = f => {
    if (!f) return null
    if (f.size > MAX_SIZE) return t('config_snapshots.upload_too_large')
    if (!ALLOWED_EXT.test(f.name)) return t('config_snapshots.upload_invalid_ext')
    return null
  }

  const handleFileChange = e => {
    const f = e.target.files[0] || null
    setFile(f)
    setValidationError(f ? validateFile(f) : null)
    setError(null)
  }

  const handleSubmit = async e => {
    e.preventDefault()
    if (!file || !note.trim()) return
    const ve = validateFile(file)
    if (ve) { setValidationError(ve); return }
    setBusy(true)
    setError(null)
    try {
      const snap = await uploadSnapshot({ portalNodeId, proxmoxNode, vmid, kind, file, note: note.trim(), action })
      onUploaded(snap)
    } catch (err) {
      setError(err?.response?.data?.detail ?? t('config_snapshots.upload_error'))
    } finally {
      setBusy(false)
    }
  }

  const canSubmit = file && !validationError && note.trim() && !busy

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-700 rounded-lg w-full max-w-lg mx-4 shadow-xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200 dark:border-zinc-700">
          <h2 className="text-sm font-semibold text-gray-900 dark:text-zinc-100">{t('config_snapshots.upload_title')}</h2>
          <button onClick={onClose} className="btn-ghost text-gray-400 hover:text-gray-600 dark:text-zinc-500 dark:hover:text-zinc-300" aria-label={t('common.close')}>✕</button>
        </div>

        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          {/* File picker */}
          <div>
            <label className="block text-xs font-medium text-gray-700 dark:text-zinc-300 mb-1">
              {t('config_snapshots.upload_file')} <span className="text-red-500">*</span>
            </label>
            <div
              className="border-2 border-dashed border-gray-300 dark:border-zinc-600 rounded-md p-4 text-center cursor-pointer hover:border-[var(--accent)] transition-colors"
              onClick={() => fileInputRef.current?.click()}
            >
              {file ? (
                <p className="text-sm text-gray-700 dark:text-zinc-300">{file.name} <span className="text-gray-400 dark:text-zinc-500">({(file.size / 1024).toFixed(1)} KB)</span></p>
              ) : (
                <p className="text-sm text-gray-400 dark:text-zinc-500">{t('config_snapshots.upload_drop_hint')}</p>
              )}
            </div>
            <input ref={fileInputRef} type="file" accept=".conf,.txt" className="hidden" onChange={handleFileChange} />
            {validationError && <p className="mt-1 text-xs text-red-500">{validationError}</p>}
            <p className="mt-1 text-xs text-gray-400 dark:text-zinc-500">{t('config_snapshots.upload_size_hint')}</p>
          </div>

          {/* Note */}
          <div>
            <label htmlFor="upload-note" className="block text-xs font-medium text-gray-700 dark:text-zinc-300 mb-1">
              {t('config_snapshots.field_note')} <span className="text-red-500">*</span>
            </label>
            <textarea
              id="upload-note"
              maxLength={500}
              rows={3}
              value={note}
              onChange={e => setNote(e.target.value)}
              placeholder={t('config_snapshots.note_placeholder')}
              className="w-full text-sm bg-white dark:bg-zinc-800 border border-gray-300 dark:border-zinc-600 rounded-md px-3 py-2 text-gray-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-orange-500 resize-none"
            />
            <p className="mt-1 text-xs text-gray-400 dark:text-zinc-500 text-right">{note.length}/500</p>
          </div>

          {/* Action */}
          <div>
            <label className="block text-xs font-medium text-gray-700 dark:text-zinc-300 mb-2">
              {t('config_snapshots.upload_action_label')}
            </label>
            <div className="space-y-2">
              {['upload_only', 'upload_and_restore'].map(opt => (
                <label key={opt} className="flex items-start gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="upload-action"
                    value={opt}
                    checked={action === opt}
                    onChange={() => setAction(opt)}
                    className="mt-0.5"
                  />
                  <span className="text-xs text-gray-700 dark:text-zinc-300">
                    <span className="font-medium">{t(`config_snapshots.upload_action_${opt}`)}</span>
                    <br />
                    <span className="text-gray-400 dark:text-zinc-500">{t(`config_snapshots.upload_action_${opt}_desc`)}</span>
                  </span>
                </label>
              ))}
            </div>
          </div>

          {error && <p className="text-xs text-red-500">{error}</p>}

          <div className="flex justify-end gap-2 pt-1">
            <button type="button" onClick={onClose} className="btn-secondary">{t('common.cancel')}</button>
            <button type="submit" disabled={!canSubmit} className="btn-primary">
              {busy ? t('common.saving') : t('config_snapshots.upload_submit')}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
