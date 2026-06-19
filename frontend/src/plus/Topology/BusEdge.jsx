// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-75: Orthogonale „Bus"-Kante für die Compute-Sicht. Statt einer diagonal
// mäandernden Kante je VM routet sie strikt rechtwinklig: vom Node senkrecht
// runter auf eine gemeinsame Verteiler-Höhe (Trunk), waagerecht zur Spalte des
// Ziels, dann senkrecht runter zur VM. Da alle Kanten eines Nodes denselben
// Trunk und je Spalte dieselbe X-Position teilen, überlagern sie sich optisch zu
// einem sauberen Bus (Trunk + Steigleitungen) — wie handgezeichnet gewünscht.
// Jede VM hat weiterhin GENAU EINE Kante (ein Andockpunkt oben).
import { BaseEdge } from 'reactflow'

const TRUNK_OFFSET = 20 // Abstand Node-Unterkante → horizontaler Verteiler

export default function BusEdge({ id, sourceX, sourceY, targetX, targetY, markerEnd, style }) {
  const trunkY = sourceY + TRUNK_OFFSET
  // M Quelle → senkrecht auf Trunk → waagerecht zur Ziel-Spalte → senkrecht zur VM.
  const path = `M ${sourceX},${sourceY} L ${sourceX},${trunkY} L ${targetX},${trunkY} L ${targetX},${targetY}`
  return <BaseEdge id={id} path={path} markerEnd={markerEnd} style={style} />
}
