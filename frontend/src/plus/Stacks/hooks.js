// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-76 Phase 1: React-Query-Hooks für Stacks.
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getNodeVmOptions } from '../../api/cluster'
import {
  fetchStacks,
  fetchStack,
  fetchVersions,
  fetchOrphans,
  deleteStack,
  reassignOrphan,
  purgeOrphan,
  planStack,
  deployStack,
  destroyStack,
  fetchDrift,
  fetchDeployments,
  fetchLiveResources,
} from './api'

// PROJ-76: Bridges/CPU-Typen/Tags eines Nodes (für die VM-Karten-Dropdowns).
// React Query dedupliziert identische Node-Abfragen über mehrere Karten hinweg.
export function useNodeVmOptions(node) {
  return useQuery({
    queryKey: ['stack-node-vm-options', node],
    queryFn: () => getNodeVmOptions(node),
    enabled: !!node,
    staleTime: 5 * 60_000,
  })
}

// ── Listen ────────────────────────────────────────────────────────────────

export function useStacks({ q, includeDeleted } = {}) {
  return useQuery({
    queryKey: ['stacks', q ?? '', includeDeleted ?? false],
    queryFn: () => fetchStacks({ q, includeDeleted }),
    staleTime: 30_000,
  })
}

export function useStack(id) {
  return useQuery({
    queryKey: ['stack', id],
    queryFn: () => fetchStack(id),
    enabled: !!id,
    staleTime: 30_000,
  })
}

export function useStackVersions(id) {
  return useQuery({
    queryKey: ['stack-versions', id],
    queryFn: () => fetchVersions(id),
    enabled: !!id,
    staleTime: 30_000,
  })
}

export function useOrphanStacks() {
  return useQuery({
    queryKey: ['stack-orphans'],
    queryFn: fetchOrphans,
    staleTime: 60_000,
  })
}

// ── Invalidierung ────────────────────────────────────────────────────────────

export function useInvalidateStacks() {
  const qc = useQueryClient()
  return (id) => {
    qc.invalidateQueries({ queryKey: ['stacks'] })
    if (id) {
      qc.invalidateQueries({ queryKey: ['stack', id] })
      qc.invalidateQueries({ queryKey: ['stack-versions', id] })
    }
  }
}

// ── Mutations ──────────────────────────────────────────────────────────────

export function useDeleteStack() {
  const invalidate = useInvalidateStacks()
  return useMutation({
    mutationFn: deleteStack,
    onSuccess: () => invalidate(),
  })
}

export function useReassignOrphan() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ownerUserId }) => reassignOrphan(id, ownerUserId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['stack-orphans'] })
      qc.invalidateQueries({ queryKey: ['stacks'] })
    },
  })
}

export function usePurgeOrphan() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: purgeOrphan,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['stack-orphans'] }),
  })
}

// ── Phase 2b: Deploy / Drift / Deployments / Resources ────────────────────────

export function useStackDeployments(id) {
  return useQuery({
    queryKey: ['stack-deployments', id],
    queryFn: () => fetchDeployments(id),
    enabled: !!id,
    staleTime: 10_000,
  })
}

export function useStackLiveResources(id) {
  return useQuery({
    queryKey: ['stack-resources-live', id],
    queryFn: () => fetchLiveResources(id),
    enabled: !!id,
    staleTime: 10_000,
  })
}

/** Plan (apply|destroy) – kein Cache, immer frisch über die Mutation. */
export function useStackPlan() {
  return useMutation({
    mutationFn: ({ id, operation }) => planStack(id, operation),
  })
}

/** apply – invalidiert Detail/Listen/Deployments nach Job-Start. */
export function useDeployStack() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, planToken }) => deployStack(id, planToken),
    onSuccess: (_res, { id }) => {
      qc.invalidateQueries({ queryKey: ['stack', id] })
      qc.invalidateQueries({ queryKey: ['stacks'] })
      qc.invalidateQueries({ queryKey: ['stack-deployments', id] })
    },
  })
}

/** destroy – gleiche Invalidierung wie deploy. */
export function useDestroyStack() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, planToken }) => destroyStack(id, planToken),
    onSuccess: (_res, { id }) => {
      qc.invalidateQueries({ queryKey: ['stack', id] })
      qc.invalidateQueries({ queryKey: ['stacks'] })
      qc.invalidateQueries({ queryKey: ['stack-deployments', id] })
    },
  })
}

/** Drift on-demand – schreibt last_drift_state, daher Detail invalidieren. */
export function useStackDrift() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id) => fetchDrift(id),
    onSuccess: (_res, id) => {
      qc.invalidateQueries({ queryKey: ['stack', id] })
      qc.invalidateQueries({ queryKey: ['stacks'] })
    },
  })
}
