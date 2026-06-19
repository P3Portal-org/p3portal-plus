# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-87: network-usage fan-out for the stack destroy-protection (AC-DES).

Before a stack-owned bridge is torn down we check whether any **foreign** guest
(not part of this stack) references it — if so the destroy is blocked (HTTP 409,
Tech-Design G). Reuses the PROJ-79 node-local segment-match fan-out (exact
``bridge=<name>`` segment, never a substring → vmbr1↔vmbr10 trap) via the node's
viewer token. Stack-owned guests at the bridge are NOT a blocker (they go in the
same destroy) — they are excluded via ``stack_deployed_resources``.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from backend.services.nodes_service import NodeRow
from backend.services.proxmox import ProxmoxAuth, ProxmoxClient

from . import deployments

logger = logging.getLogger(__name__)

_FANOUT_LIMIT = 10


def _bridge_in_config(cfg: dict, bridge: str) -> bool:
    """True if any ``netX=...,bridge=<bridge>,...`` segment matches exactly.

    Exact segment match (not substring) so ``vmbr1`` never matches ``vmbr10``
    (PROJ-79 lesson, BUG-79-2 family).
    """
    for key, val in cfg.items():
        if not (isinstance(key, str) and key.startswith("net") and isinstance(val, str)):
            continue
        for segment in val.split(","):
            if "=" in segment:
                k, v = segment.split("=", 1)
                if k.strip() == "bridge" and v.strip() == bridge:
                    return True
    return False


async def find_foreign_network_users(
    node: NodeRow, bridge_name: str, stack_id: int, bridge_node: str | None = None,
) -> list[dict[str, Any]]:
    """Foreign guests that reference bridge ``bridge_name`` (AC-DES-1).

    "Foreign" = the guest's ``(portal_node_id, vmid)`` is NOT in this stack's
    ``stack_deployed_resources`` (so the stack's own guests at the bridge are not
    reported). When ``bridge_node`` is given the fan-out is scoped to guests on
    that physical node — bridges are node-local, so a same-named bridge on another
    node is a *different* bridge (PROJ-79 lesson, avoids false positives + cheaper).
    Bounded by a Semaphore. Best-effort: an unreadable config is skipped (it does
    not falsely block the destroy). Returns ``[{vmid, name, node, kind}]``.
    """
    auth = ProxmoxAuth(
        kind="token",
        value=node.viewer_token_id or node.token_id,
        secret=node.viewer_token_secret or node.token_secret,
    )
    client = ProxmoxClient(base_url=node.url, verify_ssl=node.verify_ssl)
    try:
        vms = await client.get_cluster_resources_v2(auth, "vm")
    except Exception as exc:  # pragma: no cover – network
        logger.warning("PROJ-87: cluster resources for bridge usage failed: %r", exc)
        return []

    # VMIDs this stack already owns on this installation are excluded.
    own = {
        int(r["vmid"])
        for r in await deployments.list_deployed_resources(stack_id)
        if r.get("vmid") is not None and r.get("portal_node_id") == node.id
    }

    # Bridges are node-local → only inspect guests on the bridge's node (when
    # known). The cluster-resource ``node`` field is the physical PVE node name;
    # the stack bridge's ``node`` is the same name (transpiler node_name=net.node).
    targets = [
        r for r in vms
        if r.get("vmid") is not None and int(r["vmid"]) not in own
        and (bridge_node is None or str(r.get("node") or "") == bridge_node)
    ]

    sem = asyncio.Semaphore(_FANOUT_LIMIT)

    async def _check(r: dict) -> dict | None:
        vmid = int(r["vmid"])
        guest_node = str(r.get("node") or "")
        kind = "lxc" if str(r.get("type", "")).lower() == "lxc" else "qemu"
        async with sem:
            try:
                cfg = await client.get_vm_config(auth, guest_node, vmid, kind)
            except Exception:
                return None
        if not isinstance(cfg, dict) or not _bridge_in_config(cfg, bridge_name):
            return None
        return {
            "vmid": vmid,
            "name": str(r.get("name") or vmid),
            "node": guest_node,
            "kind": kind,
        }

    results = await asyncio.gather(*[_check(r) for r in targets], return_exceptions=True)
    return [x for x in results if isinstance(x, dict)]
