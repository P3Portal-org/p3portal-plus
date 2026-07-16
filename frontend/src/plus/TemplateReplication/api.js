// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-101: API-Client für die Template-Replikation (Plus).
// Zwei Endpoints: Preflight (read-only, treibt das Modal) und Start (202 → Job).
import api from '../../api/client'

// Quell-Storage-Status (shared?) + verfügbare Ziel-Nodes samt Datastores.
export async function preflightReplication(sourceNode, sourceVmid) {
  const params = new URLSearchParams({
    source_node: sourceNode,
    source_vmid: String(sourceVmid),
  })
  const { data } = await api.get(`/api/template-replication/preflight?${params.toString()}`)
  return data
}

// Startet die Replikation als Job. body: {
//   source_node, source_vmid, targets: [{ node, storage, newid? }],
//   remove_source_after_shared
// }. Liefert JobResponse (→ Live-Log unter /events/<id>).
export async function startReplication(body) {
  const { data } = await api.post('/api/template-replication/replicate', body)
  return data
}
