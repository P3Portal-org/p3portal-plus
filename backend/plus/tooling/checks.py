# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-66 Phase 2: OpenTofu health-check runner (Plus-only).

Probes the OpenTofu engine that ships with the Plus image (Stacks Phase 2a):
  1. ``tofu version`` → version string + "binary runs?"
  2. bpg provider offline-mirror presence (filesystem check, no network)

Status derivation (AC-P2-CHECK-3):
  binary ok  + mirror present → ready
  binary ok  + mirror missing → degraded  (+ Klartext-Detail in stderr, AC-P2-CHECK-4)
  binary fails / FileNotFound / timeout → down (AC-P2-CHECK-5)

Reuses the core subprocess helpers (``_run_cmd``/``_cap``) so timeout/cap/
no-shell semantics are identical to the Phase-1 ansible/packer runners.
The mirror path is imported from ``stacks.engine`` (single source, §C).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from backend.features.tooling.runners import CheckResult, _cap, _run_cmd

# Klartext-Begründung für degraded (AC-P2-CHECK-4) – erscheint im Slide-Over.
_MIRROR_MISSING_DETAIL = (
    "Provider-Mirror nicht gefunden — Stack-Deploys würden offline scheitern"
)


def _parse_tofu_version(stdout: str) -> str | None:
    """Extrahiert '1.9.1' aus 'OpenTofu v1.9.1\\non linux_amd64'."""
    m = re.search(r"OpenTofu\s+v?([\d.]+)", stdout, re.IGNORECASE)
    return m.group(1) if m else None


async def run_tofu_check() -> CheckResult:
    """Führt ``tofu version`` + Provider-Mirror-Präsenz-Prüfung durch.

    FileNotFoundError (kein ``tofu`` im PATH) und Timeout werden von ``_run_cmd``
    in negative Return-Codes übersetzt → status ``down``, kein ungefangener
    Fehler (passt in ``asyncio.gather(..., return_exceptions=True)``).
    """
    # Späte Import-Bindung: engine.py lebt im Plus-Zweig und parst keine HCL,
    # die Konstante/Helper sind die single source für den Mirror-Pfad (§C).
    from backend.plus.stacks.engine import tofu_provider_mirror_present

    now = datetime.now(timezone.utc)

    ver_rc, ver_out, ver_err = await _run_cmd(["tofu", "version"])
    if ver_rc < 0:
        # Binary fehlt / Timeout / unerwarteter Fehler → down (AC-P2-CHECK-5).
        return CheckResult(
            status="down",
            version=None,
            stdout="",
            stderr=ver_err,
            checked_at=now,
        )

    version = _parse_tofu_version(ver_out)
    mirror_present = tofu_provider_mirror_present()

    combined_out = _cap(f"=== tofu version ===\n{ver_out}")

    if mirror_present:
        status = "ready"
        combined_err = _cap(f"=== tofu version ===\n{ver_err}")
    else:
        # Binary läuft, aber air-gapped Provider-Mirror fehlt (AC-P2-CHECK-3/4).
        status = "degraded"
        combined_err = _cap(
            f"=== tofu version ===\n{ver_err}\n"
            f"=== provider mirror ===\n{_MIRROR_MISSING_DETAIL}"
        )

    return CheckResult(
        status=status,
        version=version,
        stdout=combined_out,
        stderr=combined_err,
        checked_at=now,
    )
