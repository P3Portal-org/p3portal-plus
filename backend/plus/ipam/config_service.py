# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-42 Phase 2: IPAM-Konfiguration (Single-Row ``ipam_config``, id=1).

Zwei Toggles (Muster PROJ-64 ``approval_workflow_config``), beide Default AUS:
- ``global_enabled``            – schaltet die zustandsbehaftete Plus-Ebene
  (Allocation-Store, Reservierungs-Lebenszyklus, Orphan, Delete-Impact). AUS =
  Verhalten wie Phase 1 (best-effort Vorschlag bleibt, aber keine Reservierung).
- ``strict_network_visibility`` – strict Default-Deny für die Netz-Sicht (nur wenn
  ``global_enabled`` AN; Admin sieht immer alles).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text

from backend.db.database import get_db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_DEFAULTS = {
    "global_enabled": False,
    "strict_network_visibility": False,
    "updated_by": None,
    "updated_at": None,
}


async def get_config() -> dict:
    """Liest ``ipam_config`` (id=1); Defaults, wenn noch keine Zeile existiert."""
    async with get_db() as db:
        result = await db.execute(text("SELECT * FROM ipam_config WHERE id = 1"))
        row = result.mappings().fetchone()
    if row is None:
        return dict(_DEFAULTS)
    return {
        "global_enabled": bool(row["global_enabled"]),
        "strict_network_visibility": bool(row["strict_network_visibility"]),
        "updated_by": row["updated_by"],
        "updated_at": row["updated_at"],
    }


async def is_global_enabled() -> bool:
    return (await get_config())["global_enabled"]


async def is_strict_visibility() -> bool:
    cfg = await get_config()
    # strict wirkt nur, wenn IPAM global aktiv ist
    return cfg["global_enabled"] and cfg["strict_network_visibility"]


async def _ensure_row(db) -> None:
    """Legt die Single-Row idempotent an (dialect-portabel, PROJ-71)."""
    await db.execute(
        text(
            "INSERT INTO ipam_config (id, global_enabled, strict_network_visibility) "
            "VALUES (1, 0, 0) ON CONFLICT DO NOTHING"
        )
    )


async def update_config(
    global_enabled: Optional[bool] = None,
    strict_network_visibility: Optional[bool] = None,
    updated_by: Optional[str] = None,
) -> dict:
    if global_enabled is None and strict_network_visibility is None:
        return await get_config()
    set_parts = ["updated_at = :now", "updated_by = :by"]
    params: dict = {"now": _now(), "by": updated_by}
    if global_enabled is not None:
        set_parts.append("global_enabled = :ge")
        params["ge"] = 1 if global_enabled else 0
    if strict_network_visibility is not None:
        set_parts.append("strict_network_visibility = :sv")
        params["sv"] = 1 if strict_network_visibility else 0
    sql = f"UPDATE ipam_config SET {', '.join(set_parts)} WHERE id = 1"
    async with get_db() as db:
        await _ensure_row(db)
        await db.execute(text(sql), params)
        await db.commit()
    return await get_config()
