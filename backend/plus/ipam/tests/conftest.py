# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-42 Phase 2: gemeinsame Fixtures für die IPAM-Plus-Tests (echte DB)."""
from __future__ import annotations

import pytest
import pytest_asyncio

pytestmark = pytest.mark.plus_only


@pytest.fixture(autouse=True)
def patch_data_dir(tmp_path, monkeypatch):
    from backend.core.config import settings
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))


@pytest_asyncio.fixture
async def db():
    """Legt Core- (init_db) + Plus-Tabellen (create_all) an einer frischen DB an."""
    from backend.db.database import init_db, get_sync_engine
    from backend.plus.ipam.models import plus_metadata
    await init_db()
    engine = get_sync_engine()
    plus_metadata.create_all(engine, checkfirst=True)
    # Stacks-Tabellen (u. a. stack_deployed_resources) für die Stacks-IPAM-Tests
    try:
        from backend.plus.stacks.models import plus_metadata as _stacks_meta
        _stacks_meta.create_all(engine, checkfirst=True)
    except Exception:
        pass
    yield


async def _make_pool(**kw) -> int:
    """Legt einen Core-ip_pool an und gibt seine id zurück."""
    from backend.features.ipam import service as core_pools
    from backend.features.ipam.schemas import IpPoolCreateRequest
    base = dict(kind="bridge", network_name="vmbr0", node="pve",
                cidr="192.168.2.0/24", gateway="192.168.2.1")
    base.update(kw)
    pool = await core_pools.create_pool(IpPoolCreateRequest(**base), created_by="admin")
    return pool.id


async def _enable_global():
    from backend.plus.ipam import config_service
    await config_service.update_config(global_enabled=True, updated_by="admin")
