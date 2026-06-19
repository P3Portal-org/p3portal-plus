# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-83 Plus: Keypair-Tiers (Pool-Key, Global-Key) – eigene Plus-MetaData.

Phantom-Tabelle `pools` (keep_existing=True) löst die Cross-MetaData-FK auf
(Muster PROJ-74). Private Keys Fernet at-rest (config_service).
"""
from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
)

plus_metadata = MetaData()

# ── Phantom-Tabelle (FK-Auflösung) ──────────────────────────────────────────
pools_phantom = Table(
    "pools", plus_metadata,
    Column("id", Integer, primary_key=True),
    keep_existing=True,
)

# ── ansible_pool_keys (ein Keypair pro Pool) ────────────────────────────────
ansible_pool_keys = Table(
    "ansible_pool_keys", plus_metadata,
    Column("pool_id", Integer, ForeignKey("pools.id", ondelete="CASCADE"), primary_key=True),
    Column("private_key_enc", Text, nullable=False),   # Fernet at-rest
    Column("public_key", Text, nullable=False),
    Column("created_at", String, nullable=False),
    Column("rotated_at", String),
)

# ── ansible_global_keypair (Singleton, id=1) ────────────────────────────────
ansible_global_keypair = Table(
    "ansible_global_keypair", plus_metadata,
    Column("id", Integer, primary_key=True),
    Column("private_key_enc", Text, nullable=False),   # Fernet at-rest
    Column("public_key", Text, nullable=False),
    Column("created_at", String, nullable=False),
    Column("rotated_at", String),
    CheckConstraint("id = 1", name="ck_ansible_global_keypair_singleton"),
)
