// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-77: API-Client für Auto-Snapshots (2 Plus-only Endpoints).
import client from '../../api/client'

const BASE = '/api/auto-snapshots'

export async function fetchRunDetails(runId) {
  const { data } = await client.get(`${BASE}/runs/${runId}/details`)
  return data
}

export async function fetchNativeSnapshots({ portalNodeId, proxmoxNode, vmid, kind }) {
  const { data } = await client.get(`${BASE}/native-snapshots`, {
    params: {
      portal_node_id: portalNodeId,
      proxmox_node: proxmoxNode,
      vmid,
      kind,
    },
  })
  return data
}
