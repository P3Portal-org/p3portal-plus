# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-101: Template-Replikation über Nodes (Plus).

Repliziert ein bestehendes VM-Template von einer Node auf andere Nodes **desselben
PVE-Clusters** – storage-bewusst:

- **lokaler** Ziel-Datastore → echte Kopie ``clone → migrate → to_template``,
- **shared** Ziel-Datastore (Ceph/NFS) → „auf shared heben": genau **eine** Kopie
  clusterweit (N Ziel-Nodes mit demselben shared Storage kollabieren zu 1),
- Quelle liegt bereits auf shared → **kein-Op**.

Nutzt die generischen Core-Primitive aus PROJ-102 (`clone_vm`/`migrate_vm`/
`convert_to_template`) sowie die Job-/Live-Log-Infrastruktur wieder. Plus-Gate → 404
in Core; RBAC via delegierbarer Permission ``replicate_templates`` (Admin ODER Träger).
"""
