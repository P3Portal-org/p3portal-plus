# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-76 Phase 2a: tests for the OpenTofu engine plumbing (backend/plus/stacks/engine.py).

These exercise the pure plumbing only — no tofu binary, no Proxmox. The end-to-end
lifecycle proof is manual (docs/opentofu-foundation.md).
"""
from __future__ import annotations

import asyncio
import os

import pytest

from backend.plus.stacks import engine
from backend.services.nodes_service import NodeRow


def _node(**over) -> NodeRow:
    base = dict(
        id=1, name="n", url="https://pve.example.com:8006", proxmox_node="pve",
        verify_ssl=True, token_id="", token_secret="",
        viewer_token_id="", viewer_token_secret="",
        operator_token_id="", operator_token_secret="",
        admin_token_id="", admin_token_secret="",
        packer_token_id="", packer_token_secret="",
        tofu_token_id="portal-tofu@pve!portal-tofu", tofu_token_secret="sek",
        is_default=True, created_at="2026-01-01T00:00:00", created_by="x",
    )
    base.update(over)
    return NodeRow(**base)


# ── Per-node env (Open Point 4) ──────────────────────────────────────────────

def test_build_node_env_mapping():
    env = engine.build_node_env(_node(verify_ssl=True))
    assert env["PROXMOX_VE_ENDPOINT"] == "https://pve.example.com:8006"
    assert env["PROXMOX_VE_API_TOKEN"] == "portal-tofu@pve!portal-tofu=sek"
    assert env["PROXMOX_VE_INSECURE"] == "false"


def test_build_node_env_insecure_when_verify_ssl_false():
    env = engine.build_node_env(_node(verify_ssl=False))
    assert env["PROXMOX_VE_INSECURE"] == "true"


def test_build_node_env_raises_without_token():
    with pytest.raises(ValueError):
        engine.build_node_env(_node(tofu_token_id="", tofu_token_secret=""))


# ── State encryption (Open Point 1) ──────────────────────────────────────────

def test_build_encryption_config_contains_passphrase_and_method():
    cfg = engine.build_encryption_config("deadbeef" * 8)
    assert "deadbeef" in cfg
    assert "pbkdf2" in cfg
    assert "aes_gcm" in cfg
    assert "state {" in cfg
    assert "plan {" in cfg


def test_read_state_passphrase(tmp_path, monkeypatch):
    from backend.core.config import settings
    monkeypatch.setattr(settings, "data_dir", str(tmp_path), raising=False)
    (tmp_path / engine.STATE_KEY_FILENAME).write_text("abc123\n", encoding="utf-8")
    assert engine.read_state_passphrase() == "abc123"


def test_read_state_passphrase_missing_raises(tmp_path, monkeypatch):
    from backend.core.config import settings
    monkeypatch.setattr(settings, "data_dir", str(tmp_path), raising=False)
    with pytest.raises(FileNotFoundError):
        engine.read_state_passphrase()


def test_read_state_passphrase_empty_raises(tmp_path, monkeypatch):
    from backend.core.config import settings
    monkeypatch.setattr(settings, "data_dir", str(tmp_path), raising=False)
    (tmp_path / engine.STATE_KEY_FILENAME).write_text("   \n", encoding="utf-8")
    with pytest.raises(ValueError):
        engine.read_state_passphrase()


def test_build_tofu_env_full(tmp_path, monkeypatch):
    from backend.core.config import settings
    monkeypatch.setattr(settings, "data_dir", str(tmp_path), raising=False)
    monkeypatch.setenv("TF_LOG", "DEBUG")  # must be stripped
    (tmp_path / engine.STATE_KEY_FILENAME).write_text("a" * 32, encoding="utf-8")

    env = engine.build_tofu_env(_node(verify_ssl=False))
    assert env["PROXMOX_VE_ENDPOINT"] == "https://pve.example.com:8006"
    assert env["PROXMOX_VE_INSECURE"] == "true"
    assert "TF_ENCRYPTION" in env and "pbkdf2" in env["TF_ENCRYPTION"]
    assert env["TF_IN_AUTOMATION"] == "1"
    assert "TF_LOG" not in env          # stripped so no token leaks into debug logs
    assert "PATH" in env                # inherits process env (TF_CLI_CONFIG_FILE etc.)


# ── Paths (Open Point 5/6) ───────────────────────────────────────────────────

def test_stack_working_dir_created(tmp_path, monkeypatch):
    from backend.core.config import settings
    monkeypatch.setattr(settings, "data_dir", str(tmp_path), raising=False)
    wd = engine.stack_working_dir("stack-xyz")
    assert wd.is_dir()
    assert wd == tmp_path / "stacks" / "stack-xyz"


# ── Per-stack lock (Open Point 7) ────────────────────────────────────────────

def test_get_stack_lock_identity():
    a1 = engine.get_stack_lock("alpha")
    a2 = engine.get_stack_lock("alpha")
    b = engine.get_stack_lock("beta")
    assert a1 is a2
    assert a1 is not b


@pytest.mark.asyncio
async def test_stack_lock_serialises_access():
    """Two tasks contending on the same stack lock must not interleave."""
    lock = engine.get_stack_lock("serial-test")
    order: list[str] = []

    async def worker(tag: str):
        async with lock:
            order.append(f"{tag}-start")
            await asyncio.sleep(0.01)   # force a context switch while holding the lock
            order.append(f"{tag}-end")

    await asyncio.gather(worker("A"), worker("B"))

    # Whoever started first must have finished before the other started → no interleave.
    first = order[0].split("-")[0]
    assert order[1] == f"{first}-end"
    assert order.count("A-start") == 1 and order.count("B-start") == 1


# ── Phase 2b additions ────────────────────────────────────────────────────────

def test_mask_line_redacts_secret():
    from backend.plus.stacks.engine import _mask_line
    assert _mask_line("token=supersecret here", "supersecret") == "token=*** here"
    assert _mask_line("nothing to mask", "supersecret") == "nothing to mask"
    assert _mask_line("line", None) == "line"


def test_cancel_tofu_no_running_process():
    from backend.plus.stacks.engine import cancel_tofu
    assert cancel_tofu("nonexistent-stack") is False
