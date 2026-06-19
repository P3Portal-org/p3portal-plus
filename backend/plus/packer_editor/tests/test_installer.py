# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-92: installer generator tests (pure fn). AC-INST-* / AC-REF-1."""
from __future__ import annotations

import pytest

from backend.plus.packer_editor.installer import (
    default_boot_command,
    installer_filename,
    installer_filenames,
    installer_files,
    render_installer,
)
from backend.plus.packer_editor.schemas import InstallerBlock

pytestmark = pytest.mark.plus_only


def _debian(**overrides) -> InstallerBlock:
    base = dict(
        os_profile="debian-preseed",
        language="de", country="DE", locale="de_DE.UTF-8", keyboard="de",
        timezone="Europe/Berlin",
        root_password_hash="$6$ROOT$hash",
        user_password_hash="$6$USER$hash",
        username="sysadm", user_uid=1000,
        packages=["sudo", "openssh-server", "qemu-guest-agent"],
        ssh_public_key="ssh-ed25519 AAAA svc-sysadm",
    )
    base.update(overrides)
    return InstallerBlock(**base)


def test_filename_per_profile():
    assert installer_filename("debian-preseed") == "preseed.cfg"
    assert installer_filename("rhel-kickstart") == "kickstart.cfg"


def test_debian_preseed_mandatory_fields():
    out = render_installer(_debian())
    assert "d-i debian-installer/locale string de_DE.UTF-8" in out
    assert "d-i keyboard-configuration/xkb-keymap select de" in out
    assert "d-i time/zone string Europe/Berlin" in out
    assert "d-i passwd/root-password-crypted password $6$ROOT$hash" in out
    assert "d-i passwd/user-password-crypted password $6$USER$hash" in out
    assert "d-i passwd/username string sysadm" in out
    assert "d-i pkgsel/include string sudo openssh-server qemu-guest-agent" in out


def test_debian_preseed_inlines_ssh_key_in_late_command():
    out = render_installer(_debian())
    assert 'echo "ssh-ed25519 AAAA svc-sysadm" > /target/root/.ssh/authorized_keys' in out
    # late_command is a single continued string
    assert "d-i preseed/late_command string \\" in out
    # last line has no trailing backslash
    assert out.rstrip().endswith("99-packer-ipv4only.conf")


def test_debian_user_hash_falls_back_to_root():
    out = render_installer(_debian(user_password_hash=None))
    # both crypted lines use the root hash
    assert out.count("$6$ROOT$hash") == 2


def test_debian_optional_apt_mirror_and_ntp():
    out = render_installer(_debian(optional={"apt_mirror": "deb.debian.org", "ntp_server": "pool.ntp.org"}))
    assert "d-i mirror/http/hostname string deb.debian.org" in out
    assert "d-i clock-setup/ntp-server string pool.ntp.org" in out


def test_debian_optional_extra_late_commands_appended():
    out = render_installer(_debian(optional={"extra_late_commands": ["touch /target/root/marker"]}))
    assert "touch /target/root/marker" in out


def test_debian_partition_recipe_override():
    out = render_installer(_debian(optional={"partition_recipe": "home"}))
    assert "d-i partman-auto/choose_recipe select home" in out


def test_raw_override_returns_verbatim():
    inst = _debian(raw_override=True, raw_content="#_preseed\nd-i custom/x boolean true\n")
    out = render_installer(inst)
    assert out == "#_preseed\nd-i custom/x boolean true\n"
    # form fields are NOT rendered in override mode
    assert "Europe/Berlin" not in out


def test_rhel_kickstart_basics():
    inst = InstallerBlock(
        os_profile="rhel-kickstart", locale="en_US.UTF-8", keyboard="us", timezone="UTC",
        root_password_hash="$6$R$h", username="admin", user_uid=1000,
        packages=["openssh-server", "qemu-guest-agent"], ssh_public_key="ssh-ed25519 BBB key",
    )
    out = render_installer(inst)
    assert "rootpw --iscrypted $6$R$h" in out
    assert "user --name=admin" in out
    assert "%packages" in out and "%end" in out
    assert 'echo "ssh-ed25519 BBB key" > /root/.ssh/authorized_keys' in out


def test_default_boot_command_debian_wires_preseed_url():
    cmd = default_boot_command("debian-preseed", 8103)
    assert any("preseed/url=http://${var.packer_http_ip}:{{ .HTTPPort }}/preseed.cfg" in c for c in cmd)


def test_default_boot_command_rhel_wires_ks_url():
    cmd = default_boot_command("rhel-kickstart", 8103)
    assert any("inst.ks=http://${var.packer_http_ip}:{{ .HTTPPort }}/kickstart.cfg" in c for c in cmd)


def test_preseed_no_ssh_key_omits_authorized_keys_block():
    out = render_installer(_debian(ssh_public_key=""))
    assert "/target/root/.ssh/authorized_keys" not in out
    # hardening late_command still present
    assert "in-target systemctl enable qemu-guest-agent" in out


# ── Ubuntu autoinstall ────────────────────────────────────────────────────────


def _ubuntu(**overrides) -> InstallerBlock:
    base = dict(
        os_profile="ubuntu-autoinstall",
        locale="en_US.UTF-8", keyboard="us", timezone="UTC",
        root_password_hash="$6$ROOT$h", user_password_hash="$6$USER$h",
        username="sysadm", user_uid=1000, hostname="tmpl",
        packages=["openssh-server", "qemu-guest-agent", "sudo"],
        ssh_public_key="ssh-ed25519 AAAA svc",
    )
    base.update(overrides)
    return InstallerBlock(**base)


def test_ubuntu_filenames_are_user_and_meta_data():
    assert installer_filenames("ubuntu-autoinstall") == ["user-data", "meta-data"]
    assert installer_filename("ubuntu-autoinstall") == "user-data"


def test_ubuntu_files_two_entries_user_data_is_cloud_config():
    files = installer_files(_ubuntu())
    assert set(files) == {"user-data", "meta-data"}
    assert files["meta-data"] == ""
    ud = files["user-data"]
    assert ud.startswith("#cloud-config")
    assert "autoinstall:" in ud
    assert "version: 1" in ud


def test_ubuntu_user_data_has_identity_packages_ssh_key():
    ud = installer_files(_ubuntu())["user-data"]
    assert "username: sysadm" in ud
    assert 'password: "$6$USER$h"' in ud   # crypt hash, never plaintext
    assert "install-server: true" in ud
    assert "- openssh-server" in ud
    assert 'echo "ssh-ed25519 AAAA svc" > /target/root/.ssh/authorized_keys' in ud


def test_ubuntu_password_falls_back_to_root_hash():
    ud = installer_files(_ubuntu(user_password_hash=None))["user-data"]
    assert 'password: "$6$ROOT$h"' in ud


def test_ubuntu_raw_override_is_user_data_meta_empty():
    files = installer_files(_ubuntu(raw_override=True, raw_content="#cloud-config\nautoinstall: {version: 1}\n"))
    assert files["user-data"] == "#cloud-config\nautoinstall: {version: 1}\n"
    assert files["meta-data"] == ""


def test_default_boot_command_ubuntu_wires_autoinstall_nocloud():
    cmd = default_boot_command("ubuntu-autoinstall", 8103)
    joined = " ".join(cmd)
    assert "autoinstall" in joined
    assert 'ds="nocloud-net;s=http://${var.packer_http_ip}:{{ .HTTPPort }}/"' in joined
