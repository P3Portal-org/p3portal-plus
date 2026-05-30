# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-77: Auto-Snapshots-Plus-Modul.

Bietet:
- vm_native_snapshots Plus-Tabelle (eigene MetaData).
- PROJ-74 vm_config_snapshots Erweiterung (created_by_scheduled_job_id +
  CHECK-Constraint 'auto').
- CHECK-Constraint-Erweiterung scheduled_jobs.job_type um 'auto_config_snapshot'
  und 'auto_vm_snapshot' (CREATE-NEW-TABLE-Pattern bei SQLite, DROP/ADD bei PG).

Reihenfolge in ensure_plus_db_tables (siehe Sektion B.3 der Spec):
  1) PROJ-62 / 63 / 70 / 64 / 74 (bisheriger Stand)
  2) PROJ-77.ensure_plus_db_tables()
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

__all__ = ["router", "ensure_plus_db_tables"]


def ensure_plus_db_tables(engine) -> None:
    """Richtet alle PROJ-77-DDL idempotent ein.

    1) Erweitert ``vm_config_snapshots`` (PROJ-74) um ``created_by_scheduled_job_id``
       und CHECK ``source IN (…, 'auto')`` (SQLite CREATE-NEW, PostgreSQL DROP/ADD).
    2) Erweitert ``scheduled_jobs`` (PROJ-70) CHECK ``job_type IN (…, 'auto_*')``.
    3) Erstellt ``vm_native_snapshots`` (eigene MetaData).
    """
    from sqlalchemy import text

    # 0) Eigene Plus-Tabelle anlegen (PROJ-77)
    try:
        from .models import plus_metadata as _auto_meta
        _auto_meta.create_all(engine, checkfirst=True)
    except Exception as exc:
        logger.warning("PROJ-77: vm_native_snapshots create_all fehlgeschlagen: %s", exc)

    # 1) PROJ-74-Erweiterung
    try:
        _migrate_proj74_extension(engine)
    except Exception as exc:
        logger.warning("PROJ-77: PROJ-74-Erweiterung fehlgeschlagen: %s", exc)

    # 2) PROJ-70 scheduled_jobs CHECK-Constraint-Erweiterung
    try:
        _migrate_scheduled_jobs_check(engine)
    except Exception as exc:
        logger.warning("PROJ-77: scheduled_jobs CHECK-Erweiterung fehlgeschlagen: %s", exc)


# ─── Migration-Helfer ────────────────────────────────────────────────────────

def _migrate_proj74_extension(engine) -> None:
    """Fügt ``created_by_scheduled_job_id`` hinzu und erweitert die source-CHECK.

    Idempotent:
    - Spalte fehlt → ALTER TABLE ADD COLUMN (SQLite und PostgreSQL).
    - CHECK enthält 'auto' nicht → SQLite: CREATE-NEW-TABLE, PostgreSQL: DROP+ADD.
    """
    from sqlalchemy import text

    with engine.connect() as conn:
        dialect = conn.dialect.name

        # ─── 1a) Spalte hinzufügen falls fehlt ────────────────────────────────
        if dialect == "sqlite":
            cols = conn.execute(text("PRAGMA table_info(vm_config_snapshots)")).fetchall()
            existing_cols = {c[1] for c in cols}
        else:
            row = conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='vm_config_snapshots'"
            )).fetchall()
            existing_cols = {r[0] for r in row}

        if existing_cols and "created_by_scheduled_job_id" not in existing_cols:
            conn.execute(text(
                "ALTER TABLE vm_config_snapshots ADD COLUMN created_by_scheduled_job_id TEXT"
            ))
            conn.commit()
            logger.info("PROJ-77: vm_config_snapshots.created_by_scheduled_job_id angelegt")

        # ─── 1b) CHECK-Constraint-Erweiterung für 'auto' ──────────────────────
        if dialect == "sqlite":
            row = conn.execute(text(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='vm_config_snapshots'"
            )).fetchone()
            if row and "'auto'" not in (row[0] or ""):
                _sqlite_rebuild_config_snapshots(conn)
        elif dialect == "postgresql":
            chk = conn.execute(text(
                "SELECT 1 FROM information_schema.check_constraints "
                "WHERE constraint_schema='public' "
                "AND constraint_name='ck_snap_source' "
                "AND check_clause LIKE '%auto%'"
            )).fetchone()
            if chk is None:
                conn.execute(text(
                    "ALTER TABLE vm_config_snapshots DROP CONSTRAINT IF EXISTS ck_snap_source"
                ))
                conn.execute(text(
                    "ALTER TABLE vm_config_snapshots ADD CONSTRAINT ck_snap_source "
                    "CHECK (source IN ('manual','pre_restore','upload','auto'))"
                ))
                conn.commit()
                logger.info("PROJ-77: vm_config_snapshots ck_snap_source erweitert (PG)")


def _sqlite_rebuild_config_snapshots(conn) -> None:
    """SQLite-CREATE-NEW-Pattern für vm_config_snapshots: source-CHECK um 'auto'."""
    from sqlalchemy import text

    conn.execute(text("""
        CREATE TABLE vm_config_snapshots_new (
            id TEXT NOT NULL PRIMARY KEY,
            portal_node_id INTEGER,
            proxmox_node TEXT NOT NULL,
            vmid INTEGER NOT NULL,
            kind TEXT NOT NULL,
            name TEXT NOT NULL,
            note TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            description TEXT,
            source TEXT NOT NULL DEFAULT 'manual',
            created_at TEXT NOT NULL,
            created_by_user_id INTEGER,
            created_by_scheduled_job_id TEXT,
            is_orphan INTEGER NOT NULL DEFAULT 0,
            orphaned_at TEXT,
            vm_name_at_delete TEXT,
            CONSTRAINT ck_snap_kind CHECK (kind IN ('qemu', 'lxc')),
            CONSTRAINT ck_snap_source CHECK (
                source IN ('manual','pre_restore','upload','auto')
            )
        )
    """))
    conn.execute(text("""
        INSERT INTO vm_config_snapshots_new
            (id, portal_node_id, proxmox_node, vmid, kind, name, note,
             payload_json, description, source, created_at, created_by_user_id,
             created_by_scheduled_job_id, is_orphan, orphaned_at, vm_name_at_delete)
        SELECT
            id, portal_node_id, proxmox_node, vmid, kind, name, note,
            payload_json, description, source, created_at, created_by_user_id,
            NULL, is_orphan, orphaned_at, vm_name_at_delete
        FROM vm_config_snapshots
    """))
    conn.execute(text("DROP TABLE vm_config_snapshots"))
    conn.execute(text("ALTER TABLE vm_config_snapshots_new RENAME TO vm_config_snapshots"))
    # Indices wieder anlegen (PROJ-74-Pattern aus models.py)
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_snap_vm ON vm_config_snapshots(portal_node_id, proxmox_node, vmid, kind)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_snap_node ON vm_config_snapshots(portal_node_id, proxmox_node)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_snap_created ON vm_config_snapshots(created_at)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_snap_orphan ON vm_config_snapshots(is_orphan)"))
    conn.commit()
    logger.info("PROJ-77: vm_config_snapshots umgebaut (SQLite, source=auto zugelassen)")


def _migrate_scheduled_jobs_check(engine) -> None:
    """Erweitert die ``ck_scheduled_jobs_type``-CHECK um auto_config_snapshot + auto_vm_snapshot."""
    from sqlalchemy import text

    with engine.connect() as conn:
        dialect = conn.dialect.name
        new_types = (
            "'playbook', 'ssh', 'power_action', 'git_sync', "
            "'auto_config_snapshot', 'auto_vm_snapshot'"
        )

        if dialect == "sqlite":
            row = conn.execute(text(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='scheduled_jobs'"
            )).fetchone()
            if not row:
                return
            sql = row[0] or ""
            if "auto_config_snapshot" in sql:
                return  # bereits migriert

            conn.execute(text(f"""
                CREATE TABLE scheduled_jobs_new (
                    id TEXT NOT NULL PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    job_type TEXT NOT NULL,
                    cron_expression TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    config TEXT NOT NULL DEFAULT '{{}}',
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_run_at TEXT,
                    last_run_status TEXT,
                    next_run_at TEXT,
                    parent_job_id TEXT,
                    CONSTRAINT ck_scheduled_jobs_type CHECK (
                        job_type IN ({new_types})
                    )
                )
            """))
            conn.execute(text("""
                INSERT INTO scheduled_jobs_new
                    (id, name, description, job_type, cron_expression, active, config,
                     created_by, created_at, updated_at, last_run_at, last_run_status,
                     next_run_at, parent_job_id)
                SELECT id, name, description, job_type, cron_expression, active, config,
                       created_by, created_at, updated_at, last_run_at, last_run_status,
                       next_run_at, parent_job_id
                FROM scheduled_jobs
            """))
            conn.execute(text("DROP TABLE scheduled_jobs"))
            conn.execute(text("ALTER TABLE scheduled_jobs_new RENAME TO scheduled_jobs"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_created_by ON scheduled_jobs(created_by)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_active ON scheduled_jobs(active)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_next_run_at ON scheduled_jobs(next_run_at)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_parent ON scheduled_jobs(parent_job_id)"))
            conn.commit()
            logger.info("PROJ-77: scheduled_jobs CHECK erweitert (SQLite, auto_* zugelassen)")

        elif dialect == "postgresql":
            chk = conn.execute(text(
                "SELECT 1 FROM information_schema.check_constraints "
                "WHERE constraint_schema='public' "
                "AND constraint_name='ck_scheduled_jobs_type' "
                "AND check_clause LIKE '%auto_config_snapshot%'"
            )).fetchone()
            if chk is None:
                conn.execute(text(
                    "ALTER TABLE scheduled_jobs DROP CONSTRAINT IF EXISTS ck_scheduled_jobs_type"
                ))
                conn.execute(text(
                    f"ALTER TABLE scheduled_jobs ADD CONSTRAINT ck_scheduled_jobs_type "
                    f"CHECK (job_type IN ({new_types}))"
                ))
                conn.commit()
                logger.info("PROJ-77: scheduled_jobs CHECK erweitert (PG, auto_* zugelassen)")


# Router-Import erfolgt erst in den Plus-Loader (main.py / backend/plus/__init__.py)
# Direkter Import könnte beim Modul-Laden Zirkularität verursachen.
try:
    from .router import router  # noqa: F401
except Exception:  # pragma: no cover
    router = None  # type: ignore[assignment]
