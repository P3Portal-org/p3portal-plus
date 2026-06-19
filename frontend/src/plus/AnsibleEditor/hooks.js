// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-93: React-Query-Hooks für den Ansible Visual Editor.
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { listDefinitions, getDefinition, deleteDefinition, listModules, getModuleSchema } from './api'

// ── Editor-Definitionen ──────────────────────────────────────────────────────

export function useDefinitions() {
  return useQuery({
    queryKey: ['ansible-editor-definitions'],
    queryFn: listDefinitions,
    staleTime: 15_000,
  })
}

export function useDefinition(id) {
  return useQuery({
    queryKey: ['ansible-editor-definition', id],
    queryFn: () => getDefinition(id),
    enabled: !!id,
    staleTime: 30_000,
  })
}

export function useDeleteDefinition() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: deleteDefinition,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['ansible-editor-definitions'] }),
  })
}

// ── Module & Schema (gecacht; der dynamische ansible-doc-Hebel) ───────────────

/** Alle ansible.builtin-Module für den Picker. Lange gecacht (Schema ist stabil). */
export function useModules() {
  return useQuery({
    queryKey: ['ansible-editor-modules'],
    queryFn: listModules,
    staleTime: 30 * 60_000,
    retry: false,
  })
}

/** Parameter-Schema eines Moduls (generischer Feld-Renderer). Ohne Namen keine Abfrage. */
export function useModuleSchema(name) {
  return useQuery({
    queryKey: ['ansible-editor-module-schema', name],
    queryFn: () => getModuleSchema(name),
    enabled: !!name,
    staleTime: 30 * 60_000,
    retry: false,
  })
}
