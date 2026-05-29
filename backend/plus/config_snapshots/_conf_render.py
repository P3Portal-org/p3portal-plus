# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""Serialize a Proxmox VM/LXC config dict back to `.conf` text format.

Format:
- description lines come first, each prefixed with `# `
- key: value pairs follow, sorted alphabetically
- one blank line between description and key-value section (if both present)
"""
from __future__ import annotations


def render_conf(
    keys: dict[str, str],
    description: str = "",
) -> str:
    """Produce Proxmox `.conf` text from a parsed key dict + description.

    Parameters
    ----------
    keys:
        Dict of config key → value pairs (all strings).
    description:
        Multi-line description text (without `# ` prefix).

    Returns
    -------
    str
        Rendered `.conf` content ready to download.
    """
    lines: list[str] = []

    if description:
        for desc_line in description.splitlines():
            lines.append(f"# {desc_line}" if desc_line.strip() else "#")
        lines.append("")  # blank separator

    for key in sorted(keys):
        value = keys[key]
        lines.append(f"{key}: {value}")

    return "\n".join(lines) + ("\n" if lines else "")
