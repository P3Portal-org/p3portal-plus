# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-93: Ansible Visual Editor (Plus-only).

A schema-driven task builder that creates an Ansible playbook in the portal and
writes it as a real directory into the ansible mount, structurally identical to
a hand-written ``ansible/<id>/``. The structured model is the source of truth
(Sidecar ``.p3editor.json``); the ``<id>.yml`` + ``meta.yaml`` + side-files are a
generated projection (Stacks-style structured-SoT, no YAML reverse parser).

The task parameter schema is **dynamic** — generated from ``ansible-doc -j`` and
served from a build-time cache (``doc_cache.py``), so new/changed core modules
render automatically without hand-maintained module knowledge.
"""
