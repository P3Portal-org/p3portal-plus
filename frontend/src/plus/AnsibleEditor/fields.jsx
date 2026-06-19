// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-93: geteilte Formular-Bausteine (Field/ComboField/Toggle/Section), Muster
// aus dem Packer-/Stacks-Editor übernommen. Pflichtfelder tragen ein „ *" im
// Label → theme-passende Akzent-Umrandung (portal-* Tokens).
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

export const inputCls =
  'w-full px-2 py-1.5 text-sm rounded-md border border-portal-border bg-portal-bg2 text-portal-text focus:outline-none focus:ring-1 focus:ring-portal-accent disabled:opacity-60 disabled:cursor-not-allowed'

const REQUIRED_RING =
  ' [&_input]:border-portal-accent [&_select]:border-portal-accent [&_textarea]:border-portal-accent'

export function Field({ label, hint, children }) {
  const required = typeof label === 'string' && /\*\s*$/.test(label)
  const text = required ? label.replace(/\s*\*\s*$/, '') : label
  return (
    <label className={'flex flex-col gap-1 text-xs' + (required ? REQUIRED_RING : '')}>
      <span className="text-portal-text2 font-medium">
        {text}
        {required && <span className="text-portal-accent font-semibold"> *</span>}
      </span>
      {children}
      {hint && <span className="text-portal-text3 text-[11px] leading-tight">{hint}</span>}
    </label>
  )
}

export function TextField({ label, value, onChange, placeholder, disabled, type = 'text' }) {
  return (
    <Field label={label}>
      <input
        type={type}
        className={inputCls}
        value={value ?? ''}
        placeholder={placeholder}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      />
    </Field>
  )
}

export function Toggle({ label, checked, onChange, disabled }) {
  return (
    <label className="flex items-center gap-2 text-xs text-portal-text2 cursor-pointer select-none">
      <input
        type="checkbox"
        className="accent-[var(--accent)]"
        checked={!!checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      {label}
    </label>
  )
}

const MANUAL = '__manual__'

/**
 * Echtes <select>-Dropdown mit Optionen; fällt auf ein Text-Feld zurück, wenn
 * keine Optionen vorliegen oder der Nutzer „Eigener Wert…" wählt.
 */
export function ComboField({ label, value, onChange, options, placeholder, disabled, hint }) {
  const { t } = useTranslation()
  const opts = Array.isArray(options) ? options : []
  const [manual, setManual] = useState(false)

  let inner
  if (opts.length === 0) {
    inner = (
      <input
        className={inputCls}
        value={value ?? ''}
        placeholder={placeholder}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      />
    )
  } else if (manual) {
    inner = (
      <div className="flex gap-1">
        <input
          className={inputCls}
          value={value ?? ''}
          placeholder={placeholder}
          disabled={disabled}
          autoFocus
          onChange={(e) => onChange(e.target.value)}
        />
        <button
          type="button"
          className="btn-table shrink-0"
          onClick={() => setManual(false)}
          title={t('ansible_editor.use_list')}
        >☰</button>
      </div>
    )
  } else {
    const showCurrent = value != null && value !== '' && !opts.includes(value)
    inner = (
      <select
        className={inputCls}
        value={value ?? ''}
        disabled={disabled}
        onChange={(e) => {
          if (e.target.value === MANUAL) { setManual(true); return }
          onChange(e.target.value)
        }}
      >
        <option value="">{placeholder}</option>
        {showCurrent && <option value={value}>{value}</option>}
        {opts.map((o) => <option key={o} value={o}>{o}</option>)}
        <option value={MANUAL}>{t('ansible_editor.custom_value')}</option>
      </select>
    )
  }
  return label ? <Field label={label} hint={hint}>{inner}</Field> : inner
}

/** Section-Karte (einheitlicher Rahmen + Titel + optionale Aktion rechts). */
export function Section({ title, desc, action, children }) {
  return (
    <div className="rounded-lg border border-portal-border bg-portal-bg2/40 p-4 space-y-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h4 className="text-sm font-semibold text-portal-text">{title}</h4>
          {desc && <p className="text-[11px] text-portal-text3 leading-snug mt-0.5">{desc}</p>}
        </div>
        {action}
      </div>
      {children}
    </div>
  )
}
