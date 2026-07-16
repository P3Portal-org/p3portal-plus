// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-42 Phase 2: React-Query-Hooks für das interne Plus-IPAM.
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { listPools } from '../../api/ipam'
import {
  getIpamConfig,
  updateIpamConfig,
  poolUsage,
  addManualAllocation,
  releaseAllocation,
  listOrphans,
  releaseOrphans,
  listGrants,
  createGrant,
  deleteGrant,
} from './api'

// ── Pools (Core-Endpoint, für Selektoren wiederverwendet) ────────────────────
export function useIpamPools({ enabled = true } = {}) {
  return useQuery({
    queryKey: ['ipam', 'pools'],
    queryFn: listPools,
    enabled,
    staleTime: 30_000,
  })
}

// ── Config (Toggles) ─────────────────────────────────────────────────────────
export function useIpamConfig({ enabled = true } = {}) {
  return useQuery({
    queryKey: ['ipam', 'config'],
    queryFn: getIpamConfig,
    enabled,
    staleTime: 30_000,
  })
}

export function useUpdateIpamConfig() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: updateIpamConfig,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['ipam', 'config'] }),
  })
}

// ── Allocations / Usage ──────────────────────────────────────────────────────
export function usePoolUsage(poolId, { enabled = true } = {}) {
  return useQuery({
    queryKey: ['ipam', 'usage', poolId],
    queryFn: () => poolUsage(poolId),
    enabled: enabled && poolId != null,
    staleTime: 15_000,
  })
}

export function useAddManualAllocation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: addManualAllocation,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['ipam'] }),
  })
}

export function useReleaseAllocation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: releaseAllocation,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['ipam'] }),
  })
}

// ── Orphans ──────────────────────────────────────────────────────────────────
export function useOrphans({ enabled = true } = {}) {
  return useQuery({
    queryKey: ['ipam', 'orphans'],
    queryFn: listOrphans,
    enabled,
    staleTime: 15_000,
  })
}

export function useReleaseOrphans() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (ids) => releaseOrphans(ids),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['ipam'] }),
  })
}

// ── Network grants ───────────────────────────────────────────────────────────
export function useGrants({ enabled = true } = {}) {
  return useQuery({
    queryKey: ['ipam', 'grants'],
    queryFn: listGrants,
    enabled,
    staleTime: 30_000,
  })
}

export function useCreateGrant() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: createGrant,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['ipam', 'grants'] }),
  })
}

export function useDeleteGrant() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: deleteGrant,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['ipam', 'grants'] }),
  })
}
