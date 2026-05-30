# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-77 – Concurrent-Conflict-Erkennung (Sektion K).

Klassifiziert Proxmox-API-Antworten in „Lock-Konflikt" vs. „echter Fehler".
Bei Lock-Konflikt: Snapshot wird übersprungen, kein Retry im selben Run.
"""
from __future__ import annotations

LOCK_PATTERNS = frozenset({
    "vm is locked",
    "ct is locked",
    "can't lock file",
    "backup write lock",
    "backup lock",
    "got lock timeout",
    "snapshot lock",
    "migration lock",
    "trying to acquire lock",
    "lock_file failed",
    "locked",                      # generischer Fallback (Proxmox sagt z.B. "VM is locked (backup)")
})

# Proxmox-Migration-Tunnel-Statuscodes
_LOCKED_HTTP_STATUS = frozenset({595, 596, 598})


def is_locked_response(
    http_status: int | None = None,
    body: str | dict | None = None,
    task_exitstatus: str = "",
) -> bool:
    """Liefert True wenn die Proxmox-Antwort auf einen Lock-Konflikt hindeutet.

    Args:
        http_status: HTTP-Statuscode der Proxmox-API-Response (oder None).
        body: Response-Body (String oder JSON-Dict).
        task_exitstatus: Proxmox-Task-Exit-Status aus get_task_status (z.B. "OK", "lock timeout").
    """
    if http_status is not None and http_status in _LOCKED_HTTP_STATUS:
        return True
    haystack = ""
    if body is not None:
        haystack += str(body)
    if task_exitstatus:
        haystack += " " + task_exitstatus
    haystack_lower = haystack.lower()
    if not haystack_lower:
        return False
    return any(pat in haystack_lower for pat in LOCK_PATTERNS)
