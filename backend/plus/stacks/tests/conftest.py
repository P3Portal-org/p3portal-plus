# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-76: Shared fixtures for stacks tests – real (temp) DB + stacks tables."""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import text


@pytest.fixture(autouse=True)
def patch_data_dir(tmp_path, monkeypatch):
    from backend.core.config import settings
    monkeypatch.setattr(settings, "data_dir", str(tmp_path), raising=False)


@pytest_asyncio.fixture
async def stack_db():
    """Init a fresh DB and create the three stacks tables + a couple of users."""
    from backend.db.database import get_db, get_sync_engine, init_db
    from backend.plus.stacks import models as m

    await init_db()
    eng = get_sync_engine()
    if eng is not None:
        m.stacks.create(eng, checkfirst=True)
        m.stack_resources.create(eng, checkfirst=True)
        m.stack_versions.create(eng, checkfirst=True)

    # Seed two local users for owner/orphan tests
    async with get_db() as db:
        for uid, uname in ((10, "alice"), (20, "bob")):
            try:
                await db.execute(
                    text(
                        "INSERT INTO local_users (id, username, password_hash, role, "
                        "active, created_at) "
                        "VALUES (:id, :u, 'x', 'operator', 1, '2026-01-01T00:00:00')"
                    ),
                    {"id": uid, "u": uname},
                )
            except Exception:
                pass
        await db.commit()
    yield
