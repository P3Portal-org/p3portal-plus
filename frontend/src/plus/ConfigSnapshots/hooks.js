// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-74: React-Query-Hooks für Config-Snapshots.
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  fetchSnapshots,
  fetchSnapshotsByNode,
  fetchOrphans,
  deleteSnapshot,
  deleteOrphan,
  bulkDeleteSnapshots,
} from './api'

// ── VM/LXC-Tab-Liste ─────────────────────────────────────────────────────

export function useConfigSnapshots({ portalNodeId, proxmoxNode, vmid, kind }) {
  return useQuery({
    queryKey: ['config-snapshots', portalNodeId, proxmoxNode, vmid, kind],
    queryFn: () => fetchSnapshots({ portalNodeId, proxmoxNode, vmid, kind }),
    enabled: !!(portalNodeId && proxmoxNode && vmid && kind),
    staleTime: 30_000,
  })
}

// ── Node-Übersicht ────────────────────────────────────────────────────────

export function useConfigSnapshotsByNode({ portalNodeId, q, kind, userId, since }, enabled = true) {
  return useQuery({
    queryKey: ['config-snapshots-by-node', portalNodeId, q, kind, userId, since],
    queryFn: () => fetchSnapshotsByNode({ portalNodeId, q, kind, userId, since }),
    enabled: enabled && !!portalNodeId,
    staleTime: 30_000,
  })
}

// ── Orphan-Liste ──────────────────────────────────────────────────────────

export function useOrphans() {
  return useQuery({
    queryKey: ['config-snapshots-orphans'],
    queryFn: fetchOrphans,
    staleTime: 60_000,
  })
}

// ── Invalidierung nach Mutations ──────────────────────────────────────────

export function useInvalidateSnapshots() {
  const qc = useQueryClient()
  return ({ portalNodeId, proxmoxNode, vmid, kind } = {}) => {
    qc.invalidateQueries({ queryKey: ['config-snapshots', portalNodeId, proxmoxNode, vmid, kind] })
    qc.invalidateQueries({ queryKey: ['config-snapshots-by-node'] })
  }
}

// ── Delete-Mutation ───────────────────────────────────────────────────────

export function useDeleteSnapshot(invalidateParams) {
  const invalidate = useInvalidateSnapshots()
  return useMutation({
    mutationFn: deleteSnapshot,
    onSuccess: () => invalidate(invalidateParams),
  })
}

// ── Bulk-Delete-Mutation ──────────────────────────────────────────────────

export function useBulkDeleteSnapshots(invalidateParams) {
  const invalidate = useInvalidateSnapshots()
  return useMutation({
    mutationFn: bulkDeleteSnapshots,
    onSuccess: () => invalidate(invalidateParams),
  })
}

// ── Orphan-Delete-Mutation ────────────────────────────────────────────────

export function useDeleteOrphan() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: deleteOrphan,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['config-snapshots-orphans'] }),
  })
}
