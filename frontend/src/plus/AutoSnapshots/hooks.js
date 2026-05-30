// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-77: React-Query-Hooks für Auto-Snapshots.
import { useQuery } from '@tanstack/react-query'
import { fetchRunDetails, fetchNativeSnapshots } from './api'

export function useRunDetails(runId, enabled = true) {
  return useQuery({
    queryKey: ['auto-snapshot-run-details', runId],
    queryFn: () => fetchRunDetails(runId),
    enabled: enabled && !!runId,
    staleTime: 30_000,
  })
}

export function useNativeSnapshots({ portalNodeId, proxmoxNode, vmid, kind }, enabled = true) {
  return useQuery({
    queryKey: ['auto-snapshot-native', portalNodeId, proxmoxNode, vmid, kind],
    queryFn: () => fetchNativeSnapshots({ portalNodeId, proxmoxNode, vmid, kind }),
    enabled: enabled && !!(portalNodeId && proxmoxNode && vmid && kind),
    staleTime: 30_000,
  })
}
