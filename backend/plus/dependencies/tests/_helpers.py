# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-96: shared test helpers — get_db mock + VmInfo factory."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from backend.models.cluster import VmInfo


class FakeResult:
    """Mimics a SQLAlchemy Result: .mappings().fetchall()/fetchone() + .rowcount."""

    def __init__(self, rows=None, rowcount=0):
        self._rows = list(rows) if rows is not None else []
        self.rowcount = rowcount

    def mappings(self):
        return self

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


def make_get_db(execute_results):
    """Return a fake ``get_db`` callable.

    ``execute_results`` is a list of FakeResult returned in order per
    ``session.execute()`` call (the last one repeats if more calls happen).
    A single shared session is used across all ``get_db()`` invocations so
    multi-block service functions get a consistent execute sequence.
    """
    state = {"i": 0}
    session = AsyncMock()

    async def _exec(*_a, **_k):
        i = state["i"]
        state["i"] += 1
        return execute_results[min(i, len(execute_results) - 1)]

    session.execute = _exec
    session.commit = AsyncMock()

    def _get_db():
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    return _get_db, session


def vm(vmid, pnid, *, vm_type="qemu", node="pve1", name=None,
       status="running", inst="prod"):
    return VmInfo(
        vmid=vmid, type=vm_type, status=status, node=node,
        name=name or f"vm-{vmid}", portal_node_id=pnid, portal_node_name=inst,
    )
