// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-92: React-Query-Hooks für den Packer Visual Editor + Dropdown-Quellen.
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getPackerNodes, getPackerIsos, fetchProxmoxTemplates } from '../../api/packer'
import { listDefinitions, getDefinition, deleteDefinition } from './api'

// ── Editor-Definitionen ──────────────────────────────────────────────────────

export function useDefinitions() {
  return useQuery({
    queryKey: ['packer-editor-definitions'],
    queryFn: listDefinitions,
    staleTime: 15_000,
  })
}

export function useDefinition(id) {
  return useQuery({
    queryKey: ['packer-editor-definition', id],
    queryFn: () => getDefinition(id),
    enabled: !!id,
    staleTime: 30_000,
  })
}

export function useDeleteDefinition() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: deleteDefinition,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['packer-editor-definitions'] }),
  })
}

// ── Dropdown-Quellen (Reuse bestehender Packer-EPs, kein neuer Hilfs-EP) ──────

/** Proxmox-Nodes (Dropdown für node-Hinweise/Filter). Best-effort. */
export function usePackerNodes() {
  return useQuery({
    queryKey: ['packer-editor-nodes'],
    queryFn: getPackerNodes,
    staleTime: 5 * 60_000,
    retry: false,
  })
}

/** Fertige Proxmox-Templates (Quell-Template-Dropdown für proxmox-clone). */
export function useProxmoxTemplates() {
  return useQuery({
    queryKey: ['packer-editor-proxmox-templates'],
    queryFn: fetchProxmoxTemplates,
    staleTime: 5 * 60_000,
    retry: false,
  })
}

/**
 * ISOs eines Nodes (ISO-Dropdown für proxmox-iso). `node` steuert die Abfrage;
 * ohne Node keine Abfrage. Fehler/leere Liste → Freitext-Fallback in der UI.
 */
export function usePackerIsos(node) {
  return useQuery({
    queryKey: ['packer-editor-isos', node],
    queryFn: () => getPackerIsos(node),
    enabled: !!node,
    staleTime: 60_000,
    retry: false,
  })
}
