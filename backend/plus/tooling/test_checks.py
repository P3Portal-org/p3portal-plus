# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-66 Phase 2: Tests für den OpenTofu-Health-Runner + Plus-Hook.

Lebt unter backend/plus/ → wird in Core-Builds physisch gestrippt (kein Marker
nötig). Mockt Subprozess (_run_cmd) + Mirror-Helper, kein echtes tofu/Netz.
"""
from __future__ import annotations

import pytest

from backend.plus.tooling.checks import _parse_tofu_version, run_tofu_check


# ── Version-Parsing ─────────────────────────────────────────────────────────

def test_parse_version_standard():
    assert _parse_tofu_version("OpenTofu v1.9.1\non linux_amd64") == "1.9.1"


def test_parse_version_case_insensitive_and_no_v():
    assert _parse_tofu_version("opentofu 1.8.0") == "1.8.0"


def test_parse_version_none_on_garbage():
    assert _parse_tofu_version("not a version string") is None


# ── run_tofu_check Status-Ableitung (AC-P2-CHECK-3) ─────────────────────────

@pytest.mark.asyncio
async def test_ready_binary_and_mirror(monkeypatch):
    """Binary läuft + Mirror vorhanden → ready."""
    async def fake_run_cmd(cmd):
        return 0, "OpenTofu v1.9.1\non linux_amd64", ""

    monkeypatch.setattr("backend.plus.tooling.checks._run_cmd", fake_run_cmd)
    monkeypatch.setattr(
        "backend.plus.stacks.engine.tofu_provider_mirror_present", lambda: True
    )

    result = await run_tofu_check()
    assert result.status == "ready"
    assert result.version == "1.9.1"
    assert "tofu version" in result.stdout


@pytest.mark.asyncio
async def test_degraded_mirror_missing(monkeypatch):
    """Binary läuft, Mirror fehlt → degraded + Klartext-Detail (AC-P2-CHECK-4)."""
    async def fake_run_cmd(cmd):
        return 0, "OpenTofu v1.9.1", ""

    monkeypatch.setattr("backend.plus.tooling.checks._run_cmd", fake_run_cmd)
    monkeypatch.setattr(
        "backend.plus.stacks.engine.tofu_provider_mirror_present", lambda: False
    )

    result = await run_tofu_check()
    assert result.status == "degraded"
    assert result.version == "1.9.1"
    assert "Provider-Mirror nicht gefunden" in result.stderr


@pytest.mark.asyncio
async def test_down_binary_missing(monkeypatch):
    """Binary nicht im PATH (rc -2 von _run_cmd) → down (AC-P2-CHECK-5)."""
    async def fake_run_cmd(cmd):
        return -2, "", "tofu: command not found"

    monkeypatch.setattr("backend.plus.tooling.checks._run_cmd", fake_run_cmd)
    # Mirror-Helper darf bei down gar nicht aufgerufen werden – aber sicherheitshalber:
    monkeypatch.setattr(
        "backend.plus.stacks.engine.tofu_provider_mirror_present", lambda: True
    )

    result = await run_tofu_check()
    assert result.status == "down"
    assert result.version is None
    assert "command not found" in result.stderr


@pytest.mark.asyncio
async def test_down_on_timeout(monkeypatch):
    """tofu version Timeout (rc -1) → down (EC-P2-4)."""
    async def fake_run_cmd(cmd):
        return -1, "", "timeout after 10s"

    monkeypatch.setattr("backend.plus.tooling.checks._run_cmd", fake_run_cmd)
    result = await run_tofu_check()
    assert result.status == "down"


# ── Aktive Plus-Impl get_additional_tooling_checks (binary-gekoppelt) ────────

def test_hook_returns_config_when_binary_present(monkeypatch):
    """which tofu vorhanden → Tofu-Config mit Runner-Callable (AC-P2-HOOK-1)."""
    from backend.plus import _PlusGateBehavior

    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/tofu")
    cfgs = _PlusGateBehavior().get_additional_tooling_checks()
    assert len(cfgs) == 1
    assert cfgs[0]["tool_id"] == "opentofu"
    assert cfgs[0]["display_name"] == "OpenTofu"
    assert callable(cfgs[0]["runner"])
    assert cfgs[0]["runner"] is run_tofu_check


def test_hook_returns_empty_when_binary_absent(monkeypatch):
    """Kein tofu-Binary → [] → kein 'down'-Dauerpunkt (AC-P2-HOOK-3, EC-P2-1)."""
    from backend.plus import _PlusGateBehavior

    monkeypatch.setattr("shutil.which", lambda name: None)
    assert _PlusGateBehavior().get_additional_tooling_checks() == []
