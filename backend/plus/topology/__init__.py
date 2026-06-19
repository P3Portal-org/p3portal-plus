# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-75: Cluster-Topologie-Ansicht (Plus-only).

Reine Read-View (keine DB-Tabelle, keine Audit-Events). Zwei Endpoints:
``GET /api/topology/cluster`` (Compute, billig) + ``GET /api/topology/network``
(Netz, lazy). Wiederverwendung der Dashboard-Datenpfade (RBAC single-source).

Hinweis: Der Router wird in main.py über ``backend.plus.topology.router`` direkt
importiert; hier KEIN ``from .router import router`` (würde das Submodul
``router.py`` durch das gleichnamige Attribut verschatten).
"""
