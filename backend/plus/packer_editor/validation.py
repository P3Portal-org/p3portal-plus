# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-92: semantic validation — non-blocking warnings (Tech-Design § I).

Pure function, no Proxmox roundtrip. Hard validation (required fields, types,
id pattern, charset/length caps) is done by Pydantic and raises 422 in the
router. These warnings never block saving — they only hint at likely build-time
problems.

Proxmox-existence checks (node / ISO / source-template found on the cluster) are
a deliberate follow-up hardening: the MVP keeps validation pure + testable and
does not run a live ``packer validate`` (too slow). See § I.
"""
from __future__ import annotations

from .installer import installer_filename
from .schemas import (
    AnsibleProvisioner,
    IsoSource,
    PackerEditorModel,
    ShellProvisioner,
)


def semantic_warnings(model: PackerEditorModel) -> list[str]:
    """Return non-blocking warnings for the given model."""
    warnings: list[str] = []
    src = model.source

    has_provisioners = len(model.provisioners) > 0

    if isinstance(src, IsoSource):
        # EC-6: iso source without an installer would hang at the prompt.
        if model.installer is None:
            warnings.append(
                "ISO-Quelle ohne Installer-Datei (preseed/kickstart) — der Build "
                "bleibt am Installer hängen, sofern boot_command/http nicht manuell geregelt ist."
            )
        else:
            # Raw-override hint: form fields are ignored.
            if model.installer.raw_override:
                warnings.append(
                    "Installer im Freitext-Override-Modus — die Formularfelder werden ignoriert, "
                    "der eingegebene Roh-Inhalt ist maßgeblich."
                )
            # boot_command should load the installer. Ubuntu autoinstall points
            # at the http directory (not a filename) via the `autoinstall` kernel
            # arg; the file profiles reference the generated file by name.
            boot = src.boot_command or []
            if model.installer.os_profile == "ubuntu-autoinstall":
                if boot and not any("autoinstall" in line for line in boot):
                    warnings.append(
                        "boot_command enthält kein 'autoinstall' — Ubuntu lädt die "
                        "user-data sonst nicht (NoCloud-Datasource)."
                    )
            else:
                fname = installer_filename(model.installer.os_profile)
                if boot and not any(fname in line for line in boot):
                    warnings.append(
                        f"boot_command referenziert die generierte Installer-Datei '{fname}' nicht "
                        "— prüfe, ob der Installer beim Boot geladen wird."
                    )

        # Provisioners need SSH; without a key the build relies on other means.
        if has_provisioners and not src.ssh_private_key_name:
            warnings.append(
                "Provisioner benötigen einen SSH-Zugang zur Build-VM, aber kein "
                "ssh_private_key_name ist gesetzt."
            )

    # ssh_private_key_name should resolve to a side-file.
    if src.ssh_private_key_name and src.ssh_private_key_name not in model.side_files:
        warnings.append(
            f"ssh_private_key_name '{src.ssh_private_key_name}' ist in den Nebendateien "
            "nicht vorhanden — der Build findet den Schlüssel sonst nicht."
        )

    # EC-7: ansible provisioner with an empty playbook.
    for p in model.provisioners:
        if isinstance(p, AnsibleProvisioner) and not p.playbook_content.strip():
            warnings.append(
                f"Ansible-Provisioner referenziert ein leeres Playbook '{p.playbook_name}'."
            )
        if isinstance(p, ShellProvisioner) and p.mode == "script" and not p.script_content.strip():
            warnings.append(
                f"Shell-Provisioner (Skript) referenziert ein leeres Skript '{p.script_name}'."
            )

    return warnings
