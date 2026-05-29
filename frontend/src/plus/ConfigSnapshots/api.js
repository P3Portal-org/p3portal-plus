// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-74: API-Helper für VM/LXC Config-Snapshots.
import client from '../../api/client'

const BASE = '/api/config-snapshots'

// ── List (VM/LXC-Tab) ─────────────────────────────────────────────────────

export async function fetchSnapshots({ portalNodeId, proxmoxNode, vmid, kind }) {
  const { data } = await client.get(BASE, {
    params: { portal_node_id: portalNodeId, proxmox_node: proxmoxNode, vmid, kind },
  })
  return data
}

// ── List (Node-Übersicht) ─────────────────────────────────────────────────

export async function fetchSnapshotsByNode({ portalNodeId, q, kind, userId, since }) {
  const params = { portal_node_id: portalNodeId }
  if (q) params.q = q
  if (kind) params.kind = kind
  if (userId) params.user_id = userId
  if (since) params.since = since
  const { data } = await client.get(`${BASE}/by-node/${portalNodeId}`, { params })
  return data
}

// ── Create ────────────────────────────────────────────────────────────────

export async function createSnapshot({ portalNodeId, proxmoxNode, vmid, kind, note, name }) {
  const { data } = await client.post(
    `${BASE}/${portalNodeId}/${proxmoxNode}/${vmid}/create`,
    { note, name },
    { params: { kind } },
  )
  return data
}

// ── Upload ────────────────────────────────────────────────────────────────

export async function uploadSnapshot({ portalNodeId, proxmoxNode, vmid, kind, file, note, action }) {
  const form = new FormData()
  form.append('file', file)
  form.append('note', note)
  form.append('action', action)
  const { data } = await client.post(
    `${BASE}/${portalNodeId}/${proxmoxNode}/${vmid}/upload`,
    form,
    { params: { kind } },
  )
  return data
}

// ── Detail ────────────────────────────────────────────────────────────────

export async function fetchSnapshotDetail(id) {
  const { data } = await client.get(`${BASE}/${id}`)
  return data
}

// ── Download (einzeln) ───────────────────────────────────────────────────

export async function downloadSnapshot(id, filename) {
  const resp = await client.get(`${BASE}/${id}/download`, { responseType: 'blob' })
  const url = URL.createObjectURL(resp.data)
  const a = document.createElement('a')
  a.href = url
  a.download = filename || 'snapshot.conf'
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

// ── Bulk-Download ────────────────────────────────────────────────────────

export async function bulkDownloadSnapshots(ids, zipName) {
  const resp = await client.post(`${BASE}/bulk-download`, { ids }, { responseType: 'blob' })
  const url = URL.createObjectURL(resp.data)
  const a = document.createElement('a')
  a.href = url
  a.download = zipName || 'config-snapshots.zip'
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

// ── Diff (Snapshot vs. Live-Config) ──────────────────────────────────────

export async function fetchDiffLive(id) {
  const { data } = await client.get(`${BASE}/${id}/diff-live`)
  return data
}

// ── Diff (A vs. B) ────────────────────────────────────────────────────────

export async function fetchDiffAB(idA, idB) {
  const { data } = await client.get(`${BASE}/diff`, { params: { a: idA, b: idB } })
  return data
}

// ── Restore ───────────────────────────────────────────────────────────────

export async function restoreSnapshot(id, { vmNameConfirm, createPreRestoreSnapshot, restartAfterRestore, etag }) {
  const { data } = await client.post(`${BASE}/${id}/restore`, {
    vm_name_confirm: vmNameConfirm,
    create_pre_restore_snapshot: createPreRestoreSnapshot,
    restart_after_restore: restartAfterRestore,
    etag,
  })
  return data
}

// ── Restore selected keys ────────────────────────────────────────────────

export async function restoreKeys(id, { keys, etag }) {
  const { data } = await client.post(`${BASE}/${id}/restore-keys`, { keys, etag })
  return data
}

// ── Delete (einzeln) ─────────────────────────────────────────────────────

export async function deleteSnapshot(id) {
  await client.delete(`${BASE}/${id}`)
}

// ── Bulk-Delete ───────────────────────────────────────────────────────────

export async function bulkDeleteSnapshots(ids) {
  await client.post(`${BASE}/bulk-delete`, { ids })
}

// ── Orphans ───────────────────────────────────────────────────────────────

export async function fetchOrphans() {
  const { data } = await client.get(`${BASE}/orphans`)
  return data
}

export async function deleteOrphan(id) {
  await client.delete(`${BASE}/orphans/${id}`)
}
