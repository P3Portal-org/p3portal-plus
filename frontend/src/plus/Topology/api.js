// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-75: API-Helper für die Cluster-Topologie-Ansicht.
// Zwei Endpoints: /cluster (billig, 60-s-Poll) und /network (lazy, on-demand).
import client from '../../api/client'

const BASE = '/api/topology'

/**
 * Compute-Sicht: Installationen → Nodes → Gäste + Stats + Stack-Liste.
 * Billig (Cluster-Cache + Bulk-SELECTs, kein per-VM-Call) → 60-s-Poll-tauglich.
 */
export async function fetchTopologyCluster() {
  const { data } = await client.get(`${BASE}/cluster`)
  return data
}

/**
 * Netz-Sicht (lazy): Netz-Knoten (Bridges/VNets/Stack-Bridges) + Konnektivität.
 * Teuer (per-VM `get_vm_config` für sichtbare Gäste) → erst beim Umschalten.
 */
export async function fetchTopologyNetwork() {
  const { data } = await client.get(`${BASE}/network`)
  return data
}

/**
 * PROJ-96: Abhängigkeits-Sicht (lazy): gerichtete VM-Abhängigkeits-Kanten.
 * Nur Kanten zwischen für den Betrachter sichtbaren VMs (serverseitig
 * RBAC-gefiltert). Liefert { guests:[…], edges:[…] }.
 */
export async function fetchTopologyDependencies() {
  const { data } = await client.get(`${BASE}/dependencies`)
  return data
}
