# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-96: vm_dependencies Tabelle mit eigener Plus-MetaData.

Gerichtete Kante (source → target) = „source hängt von target ab".
Phantom-Tabellen (keep_existing=True) lösen Cross-MetaData-FKs auf (Muster PROJ-74/76).

Die proxmox_node/name-Spalten sind denormalisierte Snapshots zur Anlegezeit
(Muster PROJ-74 vm_name_at_delete): sie machen die Impact-Warnung + die
Orphan-Liste ohne einen Live-Cluster-Fetch beschriftbar (besonders wenn eine VM
nicht mehr existiert). Die VM-Identität für Matching/Verwaisung ist immer
(portal_node_id, vmid).
"""
from __future__ import annotations

from sqlalchemy import (
    Column,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)

# Eigene MetaData – getrennt vom Core-Schema
plus_metadata = MetaData()

# ── Phantom-Tabellen (FK-Auflösung) ─────────────────────────────────────────
# keep_existing=True: SQLAlchemy überschreibt nicht, falls schon in dieser MetaData

nodes_phantom = Table(
    "nodes", plus_metadata,
    Column("id", Integer, primary_key=True),
    keep_existing=True,
)

local_users_phantom = Table(
    "local_users", plus_metadata,
    Column("id", Integer, primary_key=True),
    keep_existing=True,
)

# ── vm_dependencies ───────────────────────────────────────────────────────────

vm_dependencies = Table(
    "vm_dependencies", plus_metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    # Quelle = die abhängige VM („Dienst")
    Column("source_node_id", Integer, ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False),
    Column("source_vmid", Integer, nullable=False),
    Column("source_node", String, nullable=False),          # proxmox node name (Snapshot)
    Column("source_name", String),                          # VM name (Snapshot, nullable)
    # Ziel = die VM, von der sie abhängt („DB")
    Column("target_node_id", Integer, ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False),
    Column("target_vmid", Integer, nullable=False),
    Column("target_node", String, nullable=False),
    Column("target_name", String),
    Column("dep_label", Text),                              # optionaler Grund/Typ (Freitext)
    Column("created_at", String, nullable=False),
    Column("created_by", Integer),                          # FK→local_users.id (nullable bei Proxmox-Auth/User-Delete)
    Column("stale", Integer, nullable=False, server_default="0"),
    Column("stale_at", String),
    UniqueConstraint(
        "source_node_id", "source_vmid", "target_node_id", "target_vmid",
        name="uq_vm_dependency_edge",
    ),
)

# ── Indices ──────────────────────────────────────────────────────────────────
# Impact-Lookup: alle Kanten, die auf eine Ziel-VM zeigen (Abhängige finden).
Index("idx_dep_target", vm_dependencies.c.target_node_id, vm_dependencies.c.target_vmid)
# Detail-Sicht: alle Kanten, die von einer Quell-VM ausgehen.
Index("idx_dep_source", vm_dependencies.c.source_node_id, vm_dependencies.c.source_vmid)
# Orphan-Liste / Verwaist-Markierung.
Index("idx_dep_stale", vm_dependencies.c.stale)
