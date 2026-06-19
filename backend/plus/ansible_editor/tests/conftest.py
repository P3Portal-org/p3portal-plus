# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-93: shared fixtures — temp ansible mount + a deterministic mini
ansible-doc schema cache (so the bulk of the suite needs no live ansible-doc).

The mini cache mirrors the reduced on-disk form produced by ``doc_cache._reduce_raw``
for a handful of representative modules (apt/copy/service/ping/uri/lineinfile/file).
Tests that verify the **real** ansible-doc integration skip when it is absent.
"""
from __future__ import annotations

import json

import pytest

_MINI_MODULES = {
    "ansible.builtin.apt": "Manages apt-packages",
    "ansible.builtin.copy": "Copy files to remote locations",
    "ansible.builtin.service": "Manage services",
    "ansible.builtin.ping": "Try to connect to host, verify a usable python and return pong on success",
    "ansible.builtin.uri": "Interacts with webservices",
    "ansible.builtin.lineinfile": "Manage lines in text files",
    "ansible.builtin.file": "Manage files and file properties",
}


def _opt(type="str", required=False, default=None, choices=None, elements=None, has_sub=False, desc=""):
    return {
        "type": type, "elements": elements, "required": required, "default": default,
        "choices": choices, "has_suboptions": has_sub, "description": desc,
    }


_MINI_SCHEMAS = {
    "ansible.builtin.apt": {
        "name": _opt("list", elements="str", desc="A list of package names."),
        "state": _opt(choices=["absent", "latest", "present"], default="present", desc="Desired state."),
        "update_cache": _opt("bool", desc="Run apt-get update before the operation."),
    },
    "ansible.builtin.copy": {
        "dest": _opt("path", required=True, desc="Remote absolute path."),
        "src": _opt("path", desc="Local path to copy."),
        "content": _opt("str", desc="Inline content."),
        "mode": _opt("raw", desc="Permissions of the destination."),
        "owner": _opt("str", desc="Owner of the file."),
    },
    "ansible.builtin.service": {
        "name": _opt(required=True, desc="Name of the service."),
        "state": _opt(choices=["reloaded", "restarted", "started", "stopped"], desc="State."),
        "enabled": _opt("bool", desc="Enable at boot."),
    },
    "ansible.builtin.ping": {
        "data": _opt("str", default="pong", desc="Data to return."),
    },
    "ansible.builtin.uri": {
        "url": _opt(required=True, desc="HTTP(S) URL."),
        "headers": _opt("dict", desc="Custom headers."),
        "status_code": _opt("list", elements="int", desc="Valid status codes."),
        "method": _opt(choices=["GET", "POST", "PUT", "DELETE"], default="GET", desc="HTTP method."),
    },
    "ansible.builtin.lineinfile": {
        "path": _opt("path", required=True, desc="File to modify."),
        "line": _opt("str", desc="Line to ensure present."),
        "regexp": _opt("str", desc="Regex to match."),
    },
    "ansible.builtin.file": {
        "path": _opt("path", required=True, desc="Path to the file/dir."),
        "state": _opt(choices=["absent", "directory", "file", "touch"], desc="State."),
        "mode": _opt("raw", desc="Permissions."),
    },
}


def write_mini_cache(cache_dir) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "_modules.json").write_text(json.dumps(_MINI_MODULES))
    for fqcn, opts in _MINI_SCHEMAS.items():
        (cache_dir / f"{fqcn}.json").write_text(
            json.dumps(
                {
                    "module": fqcn,
                    "short_description": _MINI_MODULES[fqcn],
                    "description": "",
                    "options": opts,
                }
            )
        )


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Temp ansible mount + writable data_dir + a mini ansible-doc cache."""
    from backend.core.config import settings

    ansible = tmp_path / "ansible"
    ansible.mkdir()
    monkeypatch.setattr(settings, "ansible_dir", str(ansible), raising=False)
    # init_db() (router tests) needs a writable data_dir; /app/data is read-only.
    monkeypatch.setattr(settings, "data_dir", str(tmp_path), raising=False)

    cache = tmp_path / "doc-cache"
    write_mini_cache(cache)
    monkeypatch.setenv("P3_ANSIBLE_DOC_CACHE_DIR", str(cache))

    from backend.plus.ansible_editor import doc_cache

    doc_cache._reset_cache()
    yield ansible
    doc_cache._reset_cache()
