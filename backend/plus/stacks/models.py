# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-76 Phase 1: Stacks-Tabellen mit eigener Plus-MetaData.

Drei Tabellen:
  - stacks            (Stack-Definition, yaml_text = Single Source of Truth)
  - stack_resources   (denormalisierter Index für Listen-Filter)
  - stack_versions    (Versionshistorie pro Edit, FIFO-Cap)

Phantom-Tabellen (keep_existing=True) lösen Cross-MetaData-FKs auf (Pattern PROJ-74).
Integer-PKs sind dialect-portabel (SQLite AUTOINCREMENT / PG SERIAL via SQLAlchemy).
"""
from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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

# Eigene MetaData – getrennt vom Core-Schema (Pattern PROJ-62/63/64/70/74)
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

# Phase 2b: jobs is a Core table (TEXT/UUID PK) – Phantom for the deployment FK.
jobs_phantom = Table(
    "jobs", plus_metadata,
    Column("id", String, primary_key=True),
    keep_existing=True,
)

# ── stacks ────────────────────────────────────────────────────────────────────

stacks = Table(
    "stacks", plus_metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String(64), nullable=False),
    Column("description", Text),
    Column("yaml_text", Text, nullable=False),          # Single Source of Truth
    Column("version", String(32), nullable=False, server_default="1.0.0"),
    Column("status", String(16), nullable=False, server_default="draft"),
    # Forward-Compat-Discriminator (Tech-Design C, S574); Phase 3 ergänzt 'raw_hcl'
    Column("source_kind", String(16), nullable=False, server_default="structured"),
    Column("owner_user_id", Integer, ForeignKey("local_users.id", ondelete="SET NULL")),
    Column("is_orphan", Boolean, nullable=False, server_default="0"),
    Column("orphaned_at", String),
    Column("current_etag", String(64), nullable=False),  # SHA-256 hex von yaml_text
    Column("created_at", String, nullable=False),
    Column("updated_at", String, nullable=False),
    Column("deleted_at", String),                        # Soft-Delete
    # Phase 2b: Drift-Zustand (extern, nicht ableitbar). Plain-String, kein CHECK
    # → keine Enum-Migration je Phase (Tech-Design Open Point 4).
    Column("last_drift_state", String),                  # 'in_sync' | 'out_of_sync' | NULL
    Column("last_drift_at", String),
    CheckConstraint("status IN ('draft', 'active')", name="ck_stack_status"),
    CheckConstraint("source_kind IN ('structured')", name="ck_stack_source_kind"),
)

# ── stack_resources (denormalisiert) ─────────────────────────────────────────

stack_resources = Table(
    "stack_resources", plus_metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("stack_id", Integer,
           ForeignKey("stacks.id", ondelete="CASCADE"), nullable=False),
    Column("type", String(16), nullable=False, server_default="vm"),
    Column("name", String(64), nullable=False),         # aufgelöster Name (Suffix bei count>1)
    Column("definition_json", Text, nullable=False),
    Column("sort_index", Integer, nullable=False, server_default="0"),
)

# ── stack_versions (Historie) ────────────────────────────────────────────────

stack_versions = Table(
    "stack_versions", plus_metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("stack_id", Integer,
           ForeignKey("stacks.id", ondelete="CASCADE"), nullable=False),
    Column("version_number", Integer, nullable=False),  # monoton steigend pro Stack
    Column("yaml_text", Text, nullable=False),          # Snapshot der alten Definition
    Column("etag", String(64), nullable=False),
    Column("change_summary", Text),
    Column("edited_by_user_id", Integer,
           ForeignKey("local_users.id", ondelete="SET NULL")),
    Column("created_at", String, nullable=False),
)

# ── stack_deployments (Phase 2b: Deploy/Destroy-Historie) ────────────────────

stack_deployments = Table(
    "stack_deployments", plus_metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("stack_id", Integer,
           ForeignKey("stacks.id", ondelete="CASCADE"), nullable=False),
    Column("operation", String(16), nullable=False),     # 'apply' | 'destroy'
    Column("status", String(16), nullable=False, server_default="running"),
    # jobs.id ist TEXT/UUID (A-1) → String-FK auf das jobs-Phantom.
    Column("job_id", String, ForeignKey("jobs.id")),
    Column("plan_summary_json", Text),
    Column("triggered_by_user_id", Integer,
           ForeignKey("local_users.id", ondelete="SET NULL")),
    Column("started_at", String, nullable=False),
    Column("finished_at", String),
    Column("error_text", Text),
    CheckConstraint("operation IN ('apply', 'destroy')", name="ck_stack_deploy_op"),
    CheckConstraint(
        "status IN ('running', 'success', 'partial', 'failed')",
        name="ck_stack_deploy_status",
    ),
)

# ── stack_deployed_resources (Phase 2b: Stack ↔ reale VM) ─────────────────────

stack_deployed_resources = Table(
    "stack_deployed_resources", plus_metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("stack_id", Integer,
           ForeignKey("stacks.id", ondelete="CASCADE"), nullable=False),
    Column("deployment_id", Integer,
           ForeignKey("stack_deployments.id", ondelete="SET NULL")),
    Column("resource_name", String(64), nullable=False),
    # portal_node_id (A-2): (node, vmid) ist über mehrere Installationen mehrdeutig.
    Column("portal_node_id", Integer, ForeignKey("nodes.id", ondelete="CASCADE")),
    Column("node", String(64)),                          # Anzeige (Proxmox-Node)
    Column("vmid", Integer, nullable=False),
    Column("kind", String(16), nullable=False, server_default="vm"),
    Column("created_at", String, nullable=False),
)


# ── stack_cloud_init (PROJ-85: deklarative Login-/IP-Daten, getrennt vom YAML) ─
#
# Eine Zeile pro Ziel: vm_name='' = Stack-Default, vm_name=<resource_name> =
# Per-VM-Override. Liegt bewusst NICHT im stacks.yaml_text/stack_versions
# (kein Secret im Versionsverlauf, AC-STORE-1/3). Das Passwort ist Fernet-
# verschlüsselt (password_enc, AC-STORE-2 — Muster Node-Token-Secrets); SSH-Keys
# und IP-Felder sind nicht geheim (Klartext). Liegt in derselben plus_metadata
# → FK auf stacks löst direkt auf + wird von create_all(checkfirst=True)
# automatisch angelegt (keine eigene Migrationsfunktion, Tech-Design B).
# Hard-Delete des Stacks → CASCADE räumt die Zeilen ab (kein Cleanup-Hook nötig).

stack_cloud_init = Table(
    "stack_cloud_init", plus_metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("stack_id", Integer,
           ForeignKey("stacks.id", ondelete="CASCADE"), nullable=False),
    # '' = Stack-Default-Sentinel, sonst Resource-/Karten-Name (Override).
    # Empty-String statt NULL, weil NULL in UNIQUE in beiden Dialekten *distinct*
    # ist → sonst mehrere Defaults möglich (Bug). (Tech-Design B)
    Column("vm_name", String(64), nullable=False),
    Column("enabled", Boolean, nullable=False, server_default="0"),
    Column("username", String(64)),
    # Fernet-Blob (config_service.encrypt_secret); NIE Klartext at-rest.
    Column("password_enc", Text),
    # JSON-Array von Public-Key-Strings (Klartext, nicht geheim).
    Column("ssh_keys_json", Text),
    # 'dhcp' | 'static' | NULL — kein DB-CHECK (Validierung in Pydantic, Muster
    # last_drift_state) → keine Enum-Migration je Phase.
    Column("ip_mode", String(16)),
    Column("ip_address_cidr", String(64)),
    Column("ip_gateway", String(64)),
    Column("dns_servers", String(255)),   # komma-/leerzeichen-separiert
    Column("dns_domain", String(255)),
    Column("created_at", String, nullable=False),
    Column("updated_at", String, nullable=False),
    # Default ('') pro Stack eindeutig; Override pro (stack, name) eindeutig.
    UniqueConstraint("stack_id", "vm_name", name="uq_stack_cloud_init_target"),
)


# ── Indices ──────────────────────────────────────────────────────────────────

# Partial-UNIQUE: gleicher Name pro Owner nur bei aktiven (nicht gelöschten/orphan) Stacks
Index(
    "uq_stacks_owner_name",
    stacks.c.owner_user_id,
    stacks.c.name,
    unique=True,
    sqlite_where=(stacks.c.deleted_at.is_(None)) & (stacks.c.is_orphan == False),  # noqa: E712
    postgresql_where=(stacks.c.deleted_at.is_(None)) & (stacks.c.is_orphan == False),  # noqa: E712
)

Index("idx_stacks_owner", stacks.c.owner_user_id)
Index("idx_stacks_orphan", stacks.c.is_orphan)
Index("idx_stacks_deleted", stacks.c.deleted_at)

Index("idx_stack_resources_stack", stack_resources.c.stack_id)

Index("idx_stack_versions_stack", stack_versions.c.stack_id, stack_versions.c.version_number.desc())

# Phase 2b indices
Index(
    "idx_stack_deployments_stack",
    stack_deployments.c.stack_id,
    stack_deployments.c.started_at.desc(),
)
# Eine reale VM gehört zu höchstens einem Stack-State (AC-2B-ISO-4).
Index(
    "uq_stack_deployed_resources_node_vmid",
    stack_deployed_resources.c.portal_node_id,
    stack_deployed_resources.c.vmid,
    unique=True,
)
Index("idx_stack_deployed_resources_stack", stack_deployed_resources.c.stack_id)

# PROJ-85: lookup all cloud-init rows of a stack (default + overrides) in one query.
Index("idx_stack_cloud_init_stack", stack_cloud_init.c.stack_id)


# ── Phase 2b additive migration (existing Phase-1 installs) ───────────────────

def migrate_phase2b_columns(engine) -> None:
    """Add the 2 additive ``stacks`` columns to a pre-existing Phase-1 install.

    ``last_drift_state`` / ``last_drift_at`` are plain Strings (no CHECK) so no
    enum migration is ever needed (Tech-Design Open Point 4). Idempotent +
    dialect-aware (SQLite / PostgreSQL, PROJ-71). The 2 new tables come in via
    ``create_all(checkfirst=True)`` and need no ALTER.
    """
    from sqlalchemy import text

    with engine.connect() as conn:
        dialect = conn.dialect.name
        if dialect == "sqlite":
            cols = conn.execute(text("PRAGMA table_info(stacks)")).fetchall()
            existing = {c[1] for c in cols}
        else:
            rows = conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='stacks'"
            )).fetchall()
            existing = {r[0] for r in rows}

        if not existing:
            return  # table not created yet (fresh install handled by create_all)

        for col in ("last_drift_state", "last_drift_at"):
            if col not in existing:
                conn.execute(text(f"ALTER TABLE stacks ADD COLUMN {col} VARCHAR"))
        conn.commit()
