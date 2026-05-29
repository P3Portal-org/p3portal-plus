# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""Layer 3 – Config-file parser/validator for upload hardening.

Parses a raw Proxmox `.conf` text string line-by-line, enforces
key whitelists for QEMU and LXC VMs, drops unknown keys with a
warning (forward-compat), skips `[snap-*]` sections, and rejects
lines with forbidden control characters.

Returns a cleaned dict + description text + list of warnings.
The caller (service.py) wraps the remaining layers (transport,
encoding, semantics).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# ── Key whitelists ─────────────────────────────────────────────────────────────
# Proxmox QEMU .conf keys (qm.conf man-page + common additions)
PROXMOX_QEMU_KEYS: frozenset[str] = frozenset([
    "acpi", "affinity", "agent", "args", "audio0", "autostart",
    "balloon", "bios", "boot", "bootdisk",
    "cdrom", "cicustom", "cipassword", "citype", "ciupgrade", "ciuser",
    "clone", "cores", "cpu", "cpulimit", "cpuunits",
    "description",
    "efidisk0",
    "freeze",
    "hookscript", "hostpci0", "hostpci1", "hostpci2", "hostpci3",
    "hotplug", "hugepages", "hvvendorid",
    "ide0", "ide1", "ide2", "ide3",
    "ipconfig0", "ipconfig1", "ipconfig2", "ipconfig3",
    "ivshmem",
    "keyboard", "kvm",
    "localtime", "lock",
    "machine", "memory", "migrate_downtime", "migrate_speed",
    "name", "nameserver", "net0", "net1", "net2", "net3",
    "net4", "net5", "net6", "net7",
    "numa", "numa0", "numa1",
    "onboot", "ostype",
    "parallel0", "parallel1", "parent", "protection",
    "reboot", "rng0",
    "sata0", "sata1", "sata2", "sata3", "sata4", "sata5",
    "scsi0", "scsi1", "scsi2", "scsi3", "scsi4", "scsi5",
    "scsi6", "scsi7", "scsi8", "scsi9", "scsi10", "scsi11",
    "scsi12", "scsi13", "scsi14", "scsi15", "scsi16", "scsi17",
    "scsi18", "scsi19", "scsi20", "scsi21", "scsi22", "scsi23",
    "scsi24", "scsi25", "scsi26", "scsi27", "scsi28", "scsi29",
    "scsi30",
    "searchdomain", "serial0", "serial1", "serial2", "serial3",
    "shares", "skiplock", "smbios1", "smp", "sockets",
    "spice_enhancements", "sshkeys", "startdate", "startup",
    "tablet", "tags", "tdf", "template",
    "tpmstate0", "type",
    "unused0", "unused1", "unused2", "unused3", "unused4",
    "unused5", "unused6", "unused7",
    "usb0", "usb1", "usb2", "usb3",
    "vcpus", "vga", "virtio0", "virtio1", "virtio2", "virtio3",
    "virtio4", "virtio5", "virtio6", "virtio7", "virtio8", "virtio9",
    "virtio10", "virtio11", "virtio12", "virtio13", "virtio14",
    "virtio15",
    "vmgenid", "vmid", "vmstatestorage",
    "watchdog",
])

# Proxmox LXC .conf keys (pct.conf man-page + common additions)
PROXMOX_LXC_KEYS: frozenset[str] = frozenset([
    "arch", "cmode", "console",
    "cores", "cpulimit", "cpuunits",
    "debug", "description",
    "features",
    "hookscript", "hostname",
    "lock",
    "memory", "mount", "mp0", "mp1", "mp2", "mp3",
    "mp4", "mp5", "mp6", "mp7",
    "nameserver", "net0", "net1", "net2", "net3",
    "net4", "net5", "net6", "net7",
    "onboot", "ostemplate", "ostype",
    "parent", "protection",
    "rootfs",
    "searchdomain", "startup", "swap",
    "tags", "template", "tty",
    "unprivileged",
    "unused0", "unused1", "unused2", "unused3",
])

# Keys that carry identity/meta information — dropped silently on upload
_IDENTITY_KEYS: frozenset[str] = frozenset(["vmid", "parent"])

# Forbidden control characters in values (null, backspace, form-feed)
_FORBIDDEN_CHARS_RE = re.compile(r"[\x00\x08\x0c]")

# Snapshot section header pattern
_SNAP_SECTION_RE = re.compile(r"^\[snap", re.IGNORECASE)
_SECTION_RE = re.compile(r"^\[")

# Per-line and aggregate limits (Layer 3 adds on top of Layer 2)
_MAX_DESCRIPTION_LINES = 100
_MAX_DESCRIPTION_LINE_CHARS = 80
_MAX_VALUE_LEN = 4096


@dataclass
class ParsedConf:
    """Result of a successful `parse_conf_text` call."""
    keys: dict[str, str] = field(default_factory=dict)
    description: str = ""         # raw multi-line text (without leading #)
    warnings: list[str] = field(default_factory=list)


class UnsafeConfValue(ValueError):
    """Raised when a conf line contains a forbidden control character."""


def parse_conf_text(
    text: str,
    kind: str,                        # "qemu" | "lxc"
    expected_name: Optional[str] = None,
) -> ParsedConf:
    """Parse and sanitise a Proxmox .conf text upload.

    Layer 3 rules applied here:
    - `#`-prefixed lines → description accumulator (max 100 lines × 80 chars)
    - `[snap-*]` section header → skip rest of file
    - Other `[...]` section headers → skipped (non-main section)
    - `key: value` lines: unknown keys dropped + warning, identity keys
      dropped silently, forbidden chars in value → UnsafeConfValue
    - Trailing whitespace stripped from both key and value
    """
    whitelist = PROXMOX_QEMU_KEYS if kind == "qemu" else PROXMOX_LXC_KEYS
    result = ParsedConf()
    description_lines: list[str] = []
    in_non_main_section = False

    for raw_line in text.splitlines():
        line = raw_line.rstrip()

        # Skip rest of file on snapshot section
        if _SNAP_SECTION_RE.match(line):
            break

        # Non-main section header → skip lines until next header or EOF
        if _SECTION_RE.match(line):
            in_non_main_section = True
            continue

        if in_non_main_section:
            continue

        # Description line
        if line.startswith("#"):
            comment_text = line[1:].strip()
            if len(description_lines) < _MAX_DESCRIPTION_LINES:
                if len(comment_text) > _MAX_DESCRIPTION_LINE_CHARS:
                    comment_text = comment_text[:_MAX_DESCRIPTION_LINE_CHARS]
                description_lines.append(comment_text)
            continue

        # Skip blank lines
        if not line:
            continue

        # Key: value line
        if ":" not in line:
            result.warnings.append(f"unparseable_line:{line[:40]!r}")
            continue

        raw_key, _, raw_value = line.partition(":")
        key = raw_key.strip().lower()
        value = raw_value.strip()

        if len(value) > _MAX_VALUE_LEN:
            result.warnings.append(f"value_too_long:{key}")
            value = value[:_MAX_VALUE_LEN]

        # Reject forbidden control characters
        if _FORBIDDEN_CHARS_RE.search(value):
            raise UnsafeConfValue(
                f"forbidden control character in value for key {key!r}"
            )

        # Drop identity/meta keys silently
        if key in _IDENTITY_KEYS:
            continue

        # Enforce whitelist — unknown keys dropped with warning
        if key not in whitelist:
            result.warnings.append(f"unknown_key:{key}")
            continue

        result.keys[key] = value

    result.description = "\n".join(description_lines)

    # Warn on name mismatch (Layer 4 hint — non-fatal)
    if expected_name and "name" in result.keys:
        if result.keys["name"] != expected_name and kind == "qemu":
            result.warnings.append(
                f"name_mismatch:upload={result.keys['name']!r},vm={expected_name!r}"
            )
    if expected_name and "hostname" in result.keys:
        if result.keys["hostname"] != expected_name and kind == "lxc":
            result.warnings.append(
                f"hostname_mismatch:upload={result.keys['hostname']!r},vm={expected_name!r}"
            )

    return result
