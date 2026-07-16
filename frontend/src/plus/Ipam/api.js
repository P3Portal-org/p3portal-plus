// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
/**
 * PROJ-42 Phase 2 – API client for the internal Plus-IPAM (`/api/ipam` Plus routes).
 *
 * The stateful layer on top of the Core Simple-IPAM: allocations (lifecycle),
 * pool usage, foreign-IP entry, orphans, network grants and the two toggles.
 * Every endpoint is `_check_plus()`-gated (404 in Core) and `manage_ipam`/Admin
 * gated on the backend — except the read-only `allocationForVm` (any VM viewer).
 */
import api from '../../api/client'

// ── Config (toggles) ─────────────────────────────────────────────────────────
export async function getIpamConfig() {
  const { data } = await api.get('/api/ipam/config')
  return data // { global_enabled, strict_network_visibility, updated_by, updated_at }
}

export async function updateIpamConfig(payload) {
  const { data } = await api.put('/api/ipam/config', payload)
  return data
}

// ── Allocations (lifecycle / usage) ──────────────────────────────────────────
export async function listAllocations({ poolId = null, status = null } = {}) {
  const params = {}
  if (poolId != null) params.pool_id = poolId
  if (status) params.status = status
  const { data } = await api.get('/api/ipam/allocations', { params })
  return data // AllocationResponse[]
}

// Read-only allocation for one VM/LXC (VM detail card; not manage-gated).
export async function allocationForVm({ portalNodeId, vmid }) {
  const { data } = await api.get('/api/ipam/allocations/for-vm', {
    params: { portal_node_id: portalNodeId, vmid },
  })
  return data // AllocationResponse | null
}

export async function poolUsage(poolId) {
  const { data } = await api.get(`/api/ipam/pools/${poolId}/usage`)
  return data // { pool_id, total, used, free, allocations[] }
}

export async function addManualAllocation({ poolId, ip, note = null }) {
  const { data } = await api.post('/api/ipam/allocations', {
    pool_id: poolId,
    ip,
    note: note || null,
  })
  return data
}

export async function releaseAllocation(allocId) {
  await api.delete(`/api/ipam/allocations/${allocId}`)
}

// ── Orphans ──────────────────────────────────────────────────────────────────
export async function listOrphans() {
  const { data } = await api.get('/api/ipam/orphans')
  return data // AllocationResponse[]
}

// Empty ids → release all orphans. axios repeats `ids` per array entry.
export async function releaseOrphans(ids = []) {
  const { data } = await api.delete('/api/ipam/orphans', {
    params: ids.length ? { ids } : {},
    paramsSerializer: { indexes: null },
  })
  return data // { released: number }
}

// ── Network grants ───────────────────────────────────────────────────────────
export async function listGrants() {
  const { data } = await api.get('/api/ipam/grants')
  return data // NetworkGrantResponse[]
}

export async function createGrant(payload) {
  const { data } = await api.post('/api/ipam/grants', payload)
  return data
}

export async function deleteGrant(grantId) {
  await api.delete(`/api/ipam/grants/${grantId}`)
}
