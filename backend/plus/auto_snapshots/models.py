# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-77: vm_native_snapshots Plus-Tabelle mit eigener MetaData.

Phantom-Tabellen (keep_existing=True) lösen Cross-MetaData-FKs auf,
analog zu PROJ-62/63/64/70/74-Pattern.
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
    UniqueConstraint,
)

# Eigene MetaData – getrennt vom Core-Schema und anderen Plus-Modulen
plus_metadata = MetaData()


# ── Phantom-Tabellen (FK-Auflösung, werden NICHT erstellt) ────────────────────

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

# scheduled_jobs.id ist TEXT (UUID-hex)
scheduled_jobs_phantom = Table(
    "scheduled_jobs", plus_metadata,
    Column("id", String, primary_key=True),
    keep_existing=True,
)


# ── vm_native_snapshots (Plus, PROJ-77) ───────────────────────────────────────

vm_native_snapshots = Table(
    "vm_native_snapshots", plus_metadata,
    Column("id", String, primary_key=True),                # UUID hex
    Column("scheduled_job_id", String, nullable=False),    # FK String-Ref → scheduled_jobs.id
    Column("portal_node_id", Integer, nullable=False),
    Column("proxmox_node", String, nullable=False),
    Column("vmid", Integer, nullable=False),
    Column("kind", String(4), nullable=False),
    Column("snapname", String(40), nullable=False),
    Column("created_at", String, nullable=False),          # ISO-8601 UTC
    Column("include_ram", Integer, nullable=False, server_default="0"),
    Column("gfs_tiers", Text, nullable=False, server_default="[]"),  # JSON-Array: ['daily','weekly','monthly']
    Column("status", String(20), nullable=False, server_default="active"),
    Column("rotated_reason", String(30)),                  # 'keep_last_exceeded'|'gfs_aged_out'|'vm_deleted'
    Column("rotated_at", String),
    Column("error_msg", Text),
    Column("last_rotation_check_at", String),
    CheckConstraint("kind IN ('qemu', 'lxc')", name="ck_vm_native_snap_kind"),
    CheckConstraint(
        "status IN ('active', 'deleted_externally', 'rotated', 'failed')",
        name="ck_vm_native_snap_status",
    ),
    UniqueConstraint(
        "portal_node_id", "proxmox_node", "vmid", "kind", "snapname",
        name="uq_vm_native_snap_identity",
    ),
)

Index(
    "idx_vm_native_snap_job_status",
    vm_native_snapshots.c.scheduled_job_id,
    vm_native_snapshots.c.status,
)

Index(
    "idx_vm_native_snap_vm_created",
    vm_native_snapshots.c.portal_node_id,
    vm_native_snapshots.c.vmid,
    vm_native_snapshots.c.kind,
    vm_native_snapshots.c.created_at.desc(),
)

# Rotation-Query: alle aktiven Snapshots eines Jobs für ein bestimmtes Target
Index(
    "idx_vm_native_snap_rotation",
    vm_native_snapshots.c.scheduled_job_id,
    vm_native_snapshots.c.portal_node_id,
    vm_native_snapshots.c.vmid,
    vm_native_snapshots.c.kind,
    vm_native_snapshots.c.status,
)


# ── Konstanten ────────────────────────────────────────────────────────────────

SNAP_NAME_PREFIX = "p3auto_"
JOB_ID_SHORT_LEN = 8                # erste 8 Zeichen der scheduled_jobs.id (UUID-hex)
PROXMOX_SNAPNAME_MAX = 40           # Proxmox-Limit für Snapshot-Namen
