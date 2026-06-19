// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-96: API-Helper für VM-Abhängigkeiten (Verwalten + Aufräumen).
// Die Topologie-Sicht (/api/topology/dependencies) liegt in Topology/api.js.
import client from '../../api/client'

const BASE = '/api/dependencies'

/**
 * Beide Richtungen einer VM: { depends_on:[…], dependents:[…] }.
 * @param {{ vmid:number, nodeId?:number, node?:string }} p
 */
export async function fetchVmDependencies({ vmid, nodeId, node }) {
  const params = { vmid }
  if (nodeId != null) params.node_id = nodeId
  else if (node) params.node = node
  const { data } = await client.get(BASE, { params })
  return data
}

/** Kante anlegen (source hängt von target ab). */
export async function createDependency(body) {
  const { data } = await client.post(BASE, body)
  return data
}

/** Label einer Kante bearbeiten. */
export async function updateDependencyLabel(id, depLabel) {
  const { data } = await client.patch(`${BASE}/${id}`, { dep_label: depLabel })
  return data
}

/** Eine Kante löschen. */
export async function deleteDependency(id) {
  await client.delete(`${BASE}/${id}`)
}

/** Verwaiste Kanten (deren VM verschwunden ist). */
export async function fetchOrphanDependencies() {
  const { data } = await client.get(`${BASE}/orphans`)
  return data
}

/** Verwaiste Kanten löschen — leere Liste = alle verwaisten. */
export async function deleteOrphanDependencies(ids) {
  const params = (ids && ids.length) ? { ids } : {}
  const { data } = await client.delete(`${BASE}/orphans`, {
    params,
    // axios serialisiert Arrays als ids=1&ids=2 (Repeat) → passt zu FastAPI list[int]
    paramsSerializer: { indexes: null },
  })
  return data
}
