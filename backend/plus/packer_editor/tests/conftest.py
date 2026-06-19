# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-92: shared fixtures — a temp packer mount per test (file-based, no DB)."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def patch_packer_dir(tmp_path, monkeypatch):
    """Point settings.packer_dir at an isolated temp directory for each test."""
    from backend.core.config import settings

    packer = tmp_path / "packer"
    packer.mkdir()
    monkeypatch.setattr(settings, "packer_dir", str(packer), raising=False)
    # init_db() (router tests) needs a writable data_dir; /app/data is read-only.
    monkeypatch.setattr(settings, "data_dir", str(tmp_path), raising=False)
    return packer
