// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-96: Gerichtete Abhängigkeits-Kante (source „hängt von" target ab).
// Optisch von den Netz-/Compute-Kanten unterscheidbar (portal-info, Pfeil);
// verwaiste Kanten (stale) werden gestrichelt + gedimmt gezeichnet. Der Pfeil
// (markerEnd) wird im Modell gesetzt; BaseEdge reicht ihn durch.
import { BaseEdge, getSmoothStepPath, EdgeLabelRenderer } from 'reactflow'

export default function DependencyEdge({
  id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition,
  markerEnd, style, data,
}) {
  const [path, labelX, labelY] = getSmoothStepPath({
    sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, borderRadius: 8,
  })
  return (
    <>
      <BaseEdge id={id} path={path} markerEnd={markerEnd} style={style} />
      {data?.label && (
        <EdgeLabelRenderer>
          <div
            style={{ transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)` }}
            className="absolute pointer-events-none px-1 py-0.5 rounded text-[9px] font-medium bg-white/90 dark:bg-zinc-900/90 text-portal-info border border-portal-info/30"
          >
            {data.label}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  )
}
