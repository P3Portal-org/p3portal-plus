// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-92: Generischer CodeMirror-6-Wrapper (keine Sprach-Erweiterung) für
// Installer-Freitext / Nebendateien / Skripte. Liegt im Plus-Lazy-Chunk —
// nutzt dieselben @codemirror/*-Primitiven wie der Stacks-YAML-Editor, also
// keine neue npm-Dep. Dünner Wrapper analog StackYamlEditor.
import { useEffect, useRef } from 'react'
import { EditorState } from '@codemirror/state'
import { EditorView, lineNumbers, keymap, highlightActiveLine } from '@codemirror/view'
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands'

export default function PlainCodeEditor({ value, onChange, readOnly = false, minHeight = '220px' }) {
  const hostRef = useRef(null)
  const viewRef = useRef(null)
  const onChangeRef = useRef(onChange)
  onChangeRef.current = onChange

  // Mount once (re-mount only on readOnly toggle, analog StackYamlEditor).
  useEffect(() => {
    if (!hostRef.current) return
    const updateListener = EditorView.updateListener.of((vu) => {
      if (vu.docChanged && !readOnly) {
        onChangeRef.current?.(vu.state.doc.toString())
      }
    })
    const state = EditorState.create({
      doc: value ?? '',
      extensions: [
        lineNumbers(),
        highlightActiveLine(),
        history(),
        keymap.of([...defaultKeymap, ...historyKeymap, indentWithTab]),
        EditorView.editable.of(!readOnly),
        EditorState.readOnly.of(readOnly),
        EditorView.lineWrapping,
        updateListener,
        EditorView.theme({
          '&': { fontSize: '13px', height: '100%' },
          '.cm-scroller': { fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', overflow: 'auto' },
          '&.cm-focused': { outline: 'none' },
        }),
      ],
    })
    const view = new EditorView({ state, parent: hostRef.current })
    viewRef.current = view
    return () => { view.destroy(); viewRef.current = null }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [readOnly])

  // Sync external value → editor (only when it diverges).
  useEffect(() => {
    const view = viewRef.current
    if (!view) return
    const current = view.state.doc.toString()
    if (value != null && value !== current) {
      view.dispatch({ changes: { from: 0, to: current.length, insert: value } })
    }
  }, [value])

  return (
    <div
      ref={hostRef}
      style={{ minHeight }}
      className="border border-portal-border rounded-md overflow-hidden bg-portal-bg2"
      data-testid="plain-code-editor"
    />
  )
}
