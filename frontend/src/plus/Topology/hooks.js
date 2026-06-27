// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-75: React-Query-Hooks für die Cluster-Topologie.
import { useQuery } from '@tanstack/react-query'
import { fetchTopologyCluster, fetchTopologyNetwork, fetchTopologyDependencies } from './api'

/**
 * Compute-Sicht. Auto-Polling alle 60 s (AC-TAB-11); pausiert wenn das Fenster
 * im Hintergrund ist. Liefert auch die Daten für das kompakte Dashboard-Widget.
 */
export function useTopologyCluster({ enabled = true, poll = true } = {}) {
  return useQuery({
    queryKey: ['topology', 'cluster'],
    queryFn: fetchTopologyCluster,
    enabled,
    // poll=false (z. B. eingeklapptes Widget): einmal laden für die Stats, aber
    // kein 60-s-Hintergrund-Poll → keine teuren per-VM-IP-Abrufe im Leerlauf.
    refetchInterval: poll ? 60_000 : false,
    refetchIntervalInBackground: false,
    staleTime: 30_000,
    // Während eines Hintergrund-Polls die vorherigen Daten behalten → die Knoten
    // verschwinden nicht für einen Frame (sonst „nur noch das Raster").
    placeholderData: (prev) => prev,
  })
}

/**
 * Netz-Sicht (lazy). `enabled` wird erst true, sobald der Nutzer in die
 * Netz-Sicht umschaltet → kein teurer per-VM-Fetch im Default-Poll (AC-PERF-5).
 */
export function useTopologyNetwork({ enabled = false } = {}) {
  return useQuery({
    queryKey: ['topology', 'network'],
    queryFn: fetchTopologyNetwork,
    enabled,
    refetchInterval: enabled ? 60_000 : false,
    refetchIntervalInBackground: false,
    staleTime: 30_000,
    placeholderData: (prev) => prev,
  })
}

/**
 * PROJ-96: Abhängigkeits-Sicht (lazy). `enabled` wird erst true, sobald der
 * Nutzer in die Abhängigkeits-Sicht umschaltet (AC-VIEW-1).
 */
export function useTopologyDependencies({ enabled = false } = {}) {
  return useQuery({
    queryKey: ['topology', 'dependencies'],
    queryFn: fetchTopologyDependencies,
    enabled,
    refetchInterval: enabled ? 60_000 : false,
    refetchIntervalInBackground: false,
    staleTime: 30_000,
    placeholderData: (prev) => prev,
  })
}
