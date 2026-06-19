# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-83 Plus: Pool-/Global-Scope + Key-Tiers (Pool-Keypair, Global-Keypair).

User-Scope + Host-Zustand sind Core. Hier leben nur die zwei neuen Keypair-Tiers
und die Mediator-Auflösung der Pool-/Global-Scopes.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def ensure_plus_db_tables(engine) -> None:
    """Erstellt die Plus-Keypair-Tabellen idempotent."""
    from backend.plus.ansible_inventory.models import plus_metadata
    plus_metadata.create_all(engine, checkfirst=True)
