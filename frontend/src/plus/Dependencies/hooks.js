// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-96: React-Query-Hooks für VM-Abhängigkeiten.
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getVms } from '../../api/cluster'
import {
  fetchVmDependencies,
  createDependency,
  updateDependencyLabel,
  deleteDependency,
  fetchOrphanDependencies,
  deleteOrphanDependencies,
} from './api'

// ── VM-Detail: beide Richtungen ───────────────────────────────────────────────

export function useVmDependencies({ vmid, nodeId, node, enabled = true }) {
  return useQuery({
    queryKey: ['vm-dependencies', nodeId ?? node, vmid],
    queryFn: () => fetchVmDependencies({ vmid, nodeId, node }),
    enabled: enabled && !!vmid && (nodeId != null || !!node),
    staleTime: 30_000,
  })
}

// ── Sichtbare VMs für das Ziel-Dropdown (RBAC-gefiltert, installationsübergreifend) ──

export function useVisibleVms({ enabled = true } = {}) {
  return useQuery({
    queryKey: ['cluster-vms-for-deps'],
    queryFn: () => getVms(false),
    enabled,
    staleTime: 60_000,
  })
}

// ── Mutationen (invalidieren VM-Sicht + Topologie + Orphans) ──────────────────

function useInvalidateDependencies() {
  const qc = useQueryClient()
  return () => {
    qc.invalidateQueries({ queryKey: ['vm-dependencies'] })
    qc.invalidateQueries({ queryKey: ['topology', 'dependencies'] })
    qc.invalidateQueries({ queryKey: ['dependency-orphans'] })
  }
}

export function useCreateDependency() {
  const invalidate = useInvalidateDependencies()
  return useMutation({ mutationFn: createDependency, onSuccess: invalidate })
}

export function useUpdateDependencyLabel() {
  const invalidate = useInvalidateDependencies()
  return useMutation({
    mutationFn: ({ id, depLabel }) => updateDependencyLabel(id, depLabel),
    onSuccess: invalidate,
  })
}

export function useDeleteDependency() {
  const invalidate = useInvalidateDependencies()
  return useMutation({ mutationFn: deleteDependency, onSuccess: invalidate })
}

// ── Verwaiste Kanten ──────────────────────────────────────────────────────────

export function useOrphanDependencies() {
  return useQuery({
    queryKey: ['dependency-orphans'],
    queryFn: fetchOrphanDependencies,
    staleTime: 60_000,
  })
}

export function useDeleteOrphanDependencies() {
  const invalidate = useInvalidateDependencies()
  return useMutation({ mutationFn: deleteOrphanDependencies, onSuccess: invalidate })
}
