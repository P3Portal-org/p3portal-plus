# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-101: shared test helpers (fake NodeRow / ProxmoxClient / get_db)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from backend.services.nodes_service import NodeRow


def node_row(cluster_nodes=("pve2", "pve3")):
    # PROJ-26-Realität: proxmox_node = primäre Node (pve1); cluster_nodes listet nur
    # die ZUSÄTZLICHEN Member (pve2/pve3). Die primäre Node steht bewusst NICHT drin.
    return NodeRow(
        id=1, name="prod", url="https://pve:8006", proxmox_node="pve1", verify_ssl=False,
        token_id="", token_secret="", viewer_token_id="", viewer_token_secret="",
        operator_token_id="", operator_token_secret="",
        admin_token_id="admin@pve!t", admin_token_secret="secret",
        packer_token_id="", packer_token_secret="", tofu_token_id="", tofu_token_secret="",
        is_default=True, created_at="t", created_by="admin",
        cluster_nodes=list(cluster_nodes),
    )


def fake_client(*, config, storages_by_node, node_vms=None, next_vmid=999):
    """A MagicMock ProxmoxClient with the read methods the service needs."""
    c = MagicMock()
    c.get_vm_config = AsyncMock(return_value=config)
    c.get_node_image_storages = AsyncMock(side_effect=lambda auth, node: storages_by_node.get(node, []))
    c.get_node_vms = AsyncMock(return_value=node_vms or [])
    c.get_next_vmid = AsyncMock(return_value=next_vmid)
    return c


class FakeResult:
    def __init__(self, rows=None):
        self._rows = list(rows) if rows is not None else []

    def mappings(self):
        return self

    def fetchone(self):
        return self._rows[0] if self._rows else None


def make_get_db(results):
    state = {"i": 0}
    session = AsyncMock()

    async def _exec(*_a, **_k):
        i = state["i"]
        state["i"] += 1
        return results[min(i, len(results) - 1)]

    session.execute = _exec
    session.commit = AsyncMock()

    def _get_db():
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    return _get_db
