// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-77: Render-Prop-Komponente die für eine VM die `vm_native_snapshots`
// abfragt und ein Lookup ``{snapname: scheduled_job_id}`` an die Children
// liefert. Dadurch kann der Core-Code (VmSnapshotSection) die Auto-Badges
// einblenden ohne direkten Plus-Import.
//
// Wird ausschließlich gemountet wenn ``hasAutoSnapshots`` Capability aktiv ist
// (sonst kein lazy import).
import { useNativeSnapshots } from './hooks'

export default function NativeSnapshotBadgeMap({ portalNodeId, proxmoxNode, vmid, kind, children }) {
  const { data } = useNativeSnapshots(
    { portalNodeId, proxmoxNode, vmid, kind },
    !!(portalNodeId && proxmoxNode && vmid && kind),
  )
  const lookup = {}
  for (const entry of data ?? []) {
    if (entry?.snapname) lookup[entry.snapname] = entry.scheduled_job_id
  }
  return children(lookup)
}
