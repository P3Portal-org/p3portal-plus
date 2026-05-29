# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-74: vm_config_snapshots Tabelle mit eigener Plus-MetaData.

Phantom-Tabellen (keep_existing=True) lösen Cross-MetaData-FKs auf.
"""
from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
)

# Eigene MetaData – getrennt vom Core-Schema
plus_metadata = MetaData()

# ── Phantom-Tabellen (FK-Auflösung) ─────────────────────────────────────────
# keep_existing=True: SQLAlchemy überschreibt nicht, falls schon in dieser MetaData

local_users_phantom = Table(
    "local_users", plus_metadata,
    Column("id", Integer, primary_key=True),
    keep_existing=True,
)

nodes_phantom = Table(
    "nodes", plus_metadata,
    Column("id", Integer, primary_key=True),
    keep_existing=True,
)

# ── vm_config_snapshots ───────────────────────────────────────────────────────

vm_config_snapshots = Table(
    "vm_config_snapshots", plus_metadata,
    Column("id", String, primary_key=True),            # UUID hex, app-generiert
    Column("portal_node_id", Integer),                  # FK→nodes.id (nullable bei Orphan)
    Column("proxmox_node", String, nullable=False),
    Column("vmid", Integer, nullable=False),
    Column("kind", String(10), nullable=False),         # qemu | lxc
    Column("name", String(80), nullable=False),
    Column("note", Text, nullable=False),
    Column("payload_json", Text, nullable=False),       # Proxmox-Config-Dict (JSON)
    Column("description", Text),                        # Aus payload extrahiert
    Column("source", String(20), nullable=False, server_default="manual"),
    Column("created_at", String, nullable=False),
    Column("created_by_user_id", Integer),              # FK→local_users.id (nullable)
    Column("is_orphan", Integer, nullable=False, server_default="0"),
    Column("orphaned_at", String),
    Column("vm_name_at_delete", String),
    CheckConstraint("kind IN ('qemu', 'lxc')", name="ck_snap_kind"),
    CheckConstraint("source IN ('manual', 'pre_restore', 'upload')", name="ck_snap_source"),
)

# ── Indices ──────────────────────────────────────────────────────────────────

Index("idx_snap_vm", vm_config_snapshots.c.portal_node_id,
      vm_config_snapshots.c.proxmox_node,
      vm_config_snapshots.c.vmid,
      vm_config_snapshots.c.kind)

Index("idx_snap_node", vm_config_snapshots.c.portal_node_id,
      vm_config_snapshots.c.proxmox_node)

Index("idx_snap_created", vm_config_snapshots.c.created_at)

# Partial index für Orphan-Liste (SQLite ignoriert WHERE, PG nutzt es)
Index("idx_snap_orphan", vm_config_snapshots.c.is_orphan)
