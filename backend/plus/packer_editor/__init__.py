# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-92: Packer Visual Editor (Plus-only).

A form-driven editor that builds a complete Packer build definition in the
portal and writes it as a real directory into the packer mount, structurally
identical to a hand-written ``packer/<id>/``. The structured model is the
source of truth (Sidecar ``.p3editor.json``); the ``.pkr.json`` + side-files
are a generated projection (Stacks-style structured-SoT, no HCL parser).
"""
