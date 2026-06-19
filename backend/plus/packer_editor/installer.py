# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-92: OS-profile installer generator (pure fn).

Turns a typed :class:`InstallerBlock` into a finished preseed/kickstart text.
The SSH key + password hashes are already substituted (no templatefile()), so
the transpiler can wire the file with ``file()`` instead of ``templatefile()``
— this is what solves the roundtrip/escaping problem (Tech-Design § D/E).

When ``raw_override`` is set, the user's free-text content is returned verbatim
(one-way Form→Text; no reverse parse). The profile registry is extensible —
MVP ships Debian-preseed (the AC-REF-1 anchor) and RHEL-kickstart.
"""
from __future__ import annotations

from typing import Any, Callable

from .schemas import InstallerBlock

# ── Profile registry ──────────────────────────────────────────────────────────

# os_profile → (output filename under http/, generator fn)
_PRESEED_FILENAME = "preseed.cfg"
_KICKSTART_FILENAME = "kickstart.cfg"
# Ubuntu autoinstall serves a cloud-init NoCloud datasource: user-data (the
# autoinstall config) + an (empty) meta-data, both under http/.
_UBUNTU_USERDATA = "user-data"
_UBUNTU_METADATA = "meta-data"


def installer_filenames(os_profile: str) -> list[str]:
    """All output filenames under ``http/`` for a given OS profile.

    Most profiles produce one file; Ubuntu autoinstall needs two (user-data +
    meta-data, NoCloud datasource).
    """
    if os_profile == "ubuntu-autoinstall":
        return [_UBUNTU_USERDATA, _UBUNTU_METADATA]
    if os_profile == "rhel-kickstart":
        return [_KICKSTART_FILENAME]
    return [_PRESEED_FILENAME]


def installer_filename(os_profile: str) -> str:
    """Primary output filename under ``http/`` (back-compat single-file API)."""
    return installer_filenames(os_profile)[0]


def installer_files(installer: InstallerBlock) -> dict[str, str]:
    """All ``http/`` files for this installer as ``{filename: content}``.

    Honors ``raw_override`` (the free-text is the primary file's content; for
    Ubuntu the secondary meta-data stays empty).
    """
    profile = installer.os_profile
    if profile == "ubuntu-autoinstall":
        ud = installer.raw_content if installer.raw_override else _gen_ubuntu_autoinstall(installer)
        return {_UBUNTU_USERDATA: ud, _UBUNTU_METADATA: ""}
    fname = installer_filename(profile)
    if installer.raw_override:
        return {fname: installer.raw_content}
    gen = _GENERATORS.get(profile)
    if gen is None:  # pragma: no cover - schema Literal prevents this
        raise ValueError(f"unknown os_profile: {profile}")
    return {fname: gen(installer)}


def render_installer(installer: InstallerBlock) -> str:
    """Render the primary installer file content (back-compat single-file API).

    Honors ``raw_override`` (returns the free-text verbatim for single-file
    profiles). For Ubuntu this returns the user-data.
    """
    return installer_files(installer)[installer_filename(installer.os_profile)]


def _opt(installer: InstallerBlock, key: str, default: Any = None) -> Any:
    """Read an optional field from the add/remove kit."""
    return installer.optional.get(key, default)


# ── Debian preseed (AC-REF-1 anchor) ──────────────────────────────────────────


def _gen_debian_preseed(inst: InstallerBlock) -> str:
    """Generate a finished Debian preseed.cfg from typed fields.

    Functionally equivalent to packer/debian-13/http/preseed.cfg.tpl with the
    SSH key already inlined (no ${...} template arg). Includes the same
    IPv4-only/sshd hardening late_command so the build connects reliably.
    """
    root_hash = inst.root_password_hash or ""
    user_hash = inst.user_password_hash or root_hash
    include_pkgs = " ".join(inst.packages) if inst.packages else "sudo openssh-server qemu-guest-agent"
    apt_mirror = _opt(inst, "apt_mirror")
    ntp_server = _opt(inst, "ntp_server")
    partition_recipe = _opt(inst, "partition_recipe", "atomic")
    extra_late = _opt(inst, "extra_late_commands", []) or []

    lines: list[str] = []
    a = lines.append

    a("#_preseed_V1")
    a("")
    a("# Automatic installation")
    a("d-i auto-install/enable boolean true")
    a("d-i debconf/priority select critical")
    a("")
    a("# Base system installation")
    a("d-i base-installer/kernel/override-image string linux-server")
    a("")
    a("# Locale / language")
    a(f"d-i debian-installer/language string {inst.language}")
    a(f"d-i debian-installer/country string {inst.country}")
    a(f"d-i debian-installer/locale string {inst.locale}")
    a("")
    a("# Keyboard")
    a(f"d-i keyboard-configuration/xkb-keymap select {inst.keyboard}")
    a("")
    a("# Clock / timezone")
    a("d-i clock-setup/utc boolean true")
    a(f"d-i time/zone string {inst.timezone}")
    a("d-i clock-setup/ntp boolean true")
    if ntp_server:
        a(f"d-i clock-setup/ntp-server string {ntp_server}")
    a("")
    a("# Networking (DHCP, IPv4)")
    a("d-i netcfg/use_autoconfig boolean true")
    a("d-i netcfg/use_dhcp string true")
    a("d-i netcfg/choose_interface select auto")
    a("d-i netcfg/disable_dhcp boolean false")
    a("")
    a("# Mirror")
    a("apt-mirror-setup apt-setup/use_mirror boolean true")
    if apt_mirror:
        a(f"d-i mirror/http/hostname string {apt_mirror}")
    a("")
    a("# Partitioning")
    a("d-i partman-auto/method string lvm")
    a("d-i partman-lvm/device_remove_lvm boolean true")
    a("d-i partman-lvm/confirm boolean true")
    a("d-i partman-lvm/confirm_nooverwrite boolean true")
    a(f"d-i partman-auto/choose_recipe select {partition_recipe}")
    a("d-i partman-auto-lvm/guided_size string max")
    a("d-i partman-partitioning/confirm_write_new_label boolean true")
    a("d-i partman/choose_partition select finish")
    a("d-i partman/confirm boolean true")
    a("d-i partman/confirm_nooverwrite boolean true")
    a("")
    a("# Root account")
    a("d-i passwd/root-login boolean true")
    a(f"d-i passwd/root-password-crypted password {root_hash}")
    a("")
    a("# Primary user")
    a(f"d-i passwd/user-fullname string {inst.username}")
    a(f"d-i passwd/user-uid string {inst.user_uid}")
    a(f"d-i passwd/user-password-crypted password {user_hash}")
    a(f"d-i passwd/username string {inst.username}")
    a("d-i user-setup/allow-password-weak boolean true")
    a("d-i user-setup/encrypt-home boolean false")
    a("")
    a("# Packages")
    a("tasksel tasksel/first multiselect standard, ssh-server")
    a("d-i pkgsel/upgrade select full-upgrade")
    a("popularity-contest popularity-contest/participate boolean false")
    a(f"d-i pkgsel/include string {include_pkgs}")
    a("d-i pkgsel/update-policy select none")
    a("d-i pkgsel/install-language-support boolean false")
    a("")
    a("# Boot loader")
    a("d-i grub-installer/only_debian boolean true")
    a("d-i grub-installer/with_other_os boolean true")
    a("d-i grub-installer/bootdev string default")
    a("")
    a("# Finishing up")
    a("d-i finish-install/reboot_in_progress note")
    a("d-i cdrom-detect/eject boolean true")
    a("")
    a("# Late command: install SSH key, harden sshd, IPv4-only during build")
    late: list[str] = []
    if inst.ssh_public_key:
        late += [
            "mkdir -p /target/root/.ssh",
            f'echo "{inst.ssh_public_key}" > /target/root/.ssh/authorized_keys',
            "chmod 700 /target/root/.ssh",
            "chmod 600 /target/root/.ssh/authorized_keys",
        ]
    late += [
        "mkdir -p /target/etc/ssh/sshd_config.d",
        'echo "PermitRootLogin prohibit-password" > /target/etc/ssh/sshd_config.d/packer.conf',
        'echo "PubkeyAuthentication yes" >> /target/etc/ssh/sshd_config.d/packer.conf',
        "in-target systemctl enable qemu-guest-agent",
        'echo "net.ipv6.conf.all.disable_ipv6=1" >> /target/etc/sysctl.d/99-packer-ipv4only.conf',
        'echo "net.ipv6.conf.default.disable_ipv6=1" >> /target/etc/sysctl.d/99-packer-ipv4only.conf',
    ]
    late += [str(x) for x in extra_late]
    a("d-i preseed/late_command string \\")
    n = len(late)
    for i, cmd in enumerate(late):
        # All commands but the last are joined with "; \" (preseed continuation).
        a(f"  {cmd}; \\" if i < n - 1 else f"  {cmd}")
    return "\n".join(lines) + "\n"


# ── RHEL kickstart ────────────────────────────────────────────────────────────


def _gen_rhel_kickstart(inst: InstallerBlock) -> str:
    """Generate a finished RHEL/Rocky kickstart from typed fields (MVP, leaner)."""
    root_hash = inst.root_password_hash or ""
    user_hash = inst.user_password_hash or root_hash
    extra_post = _opt(inst, "extra_post_commands", []) or []
    pkgs = inst.packages or ["openssh-server", "qemu-guest-agent", "sudo"]

    lines: list[str] = []
    a = lines.append
    a("# kickstart (generated by P3 Packer Visual Editor)")
    a("text")
    a(f"lang {inst.locale}")
    a(f"keyboard {inst.keyboard}")
    a(f"timezone {inst.timezone} --utc")
    a("network --bootproto=dhcp --activate")
    a("firewall --enabled --service=ssh")
    a("selinux --enforcing")
    a("bootloader --location=mbr")
    a("clearpart --all --initlabel")
    a("autopart --type=lvm")
    a("reboot")
    a("")
    a(f'rootpw --iscrypted {root_hash}')
    a(f"user --name={inst.username} --uid={inst.user_uid} --groups=wheel --iscrypted --password={user_hash}")
    a("")
    a("%packages")
    a("@^minimal-environment")
    for p in pkgs:
        a(p)
    a("%end")
    a("")
    a("%post --log=/root/ks-post.log")
    if inst.ssh_public_key:
        a("mkdir -p /root/.ssh")
        a(f'echo "{inst.ssh_public_key}" > /root/.ssh/authorized_keys')
        a("chmod 700 /root/.ssh")
        a("chmod 600 /root/.ssh/authorized_keys")
    a("systemctl enable qemu-guest-agent")
    for cmd in extra_post:
        a(str(cmd))
    a("%end")
    return "\n".join(lines) + "\n"


# ── Ubuntu autoinstall (subiquity / cloud-init user-data) ─────────────────────


def _gen_ubuntu_autoinstall(inst: InstallerBlock) -> str:
    """Generate a finished Ubuntu autoinstall ``user-data`` (cloud-init).

    Modern Ubuntu Server (20.04+) uses the subiquity autoinstall mechanism, NOT
    the Debian-installer preseed. The installer fetches this user-data + an empty
    meta-data from the Packer HTTP server (NoCloud datasource), wired by the
    boot_command. The password is the server-side $6$ crypt hash.
    """
    user_hash = inst.user_password_hash or inst.root_password_hash or ""
    pkgs = inst.packages or ["openssh-server", "qemu-guest-agent", "sudo"]
    hostname = inst.hostname or "ubuntu-template"
    extra_late = _opt(inst, "extra_late_commands", []) or []

    lines: list[str] = []
    a = lines.append
    a("#cloud-config")
    a("autoinstall:")
    a("  version: 1")
    a(f"  locale: {inst.locale}")
    a("  keyboard:")
    a(f"    layout: {inst.keyboard}")
    a("  identity:")
    a(f"    hostname: {hostname}")
    a(f"    username: {inst.username}")
    a(f'    password: "{user_hash}"')
    a("  ssh:")
    a("    install-server: true")
    a("    allow-pw: true")
    a("  packages:")
    for p in pkgs:
        a(f"    - {p}")
    a("  storage:")
    a("    layout:")
    a("      name: lvm")
    a("  user-data:")
    a(f"    timezone: {inst.timezone}")
    # late-commands run with /target as the installed system.
    late: list[str] = []
    if inst.ssh_public_key:
        late += [
            "mkdir -p /target/root/.ssh",
            f'echo "{inst.ssh_public_key}" > /target/root/.ssh/authorized_keys',
            "chmod 700 /target/root/.ssh",
            "chmod 600 /target/root/.ssh/authorized_keys",
        ]
    late.append("curtin in-target --target=/target -- systemctl enable qemu-guest-agent")
    late += [str(x) for x in extra_late]
    if late:
        a("  late-commands:")
        for cmd in late:
            a(f"    - '{cmd}'")
    return "\n".join(lines) + "\n"


_GENERATORS: dict[str, Callable[[InstallerBlock], str]] = {
    "debian-preseed": _gen_debian_preseed,
    "rhel-kickstart": _gen_rhel_kickstart,
    "ubuntu-autoinstall": _gen_ubuntu_autoinstall,
}


def default_boot_command(os_profile: str, http_port: int) -> list[str]:
    """Typed standard boot_command per profile, with the installer URL wired
    to ``${var.packer_http_ip}:{{ .HTTPPort }}`` (Tech-Design § E, AC-INST-5)."""
    if os_profile == "ubuntu-autoinstall":
        # Ubuntu Server 20.04+ live-server (subiquity). GRUB command line:
        # boot the casper kernel with autoinstall + NoCloud datasource pointing
        # at the Packer HTTP server (serves user-data + meta-data).
        return [
            "c<wait>",
            'linux /casper/vmlinuz autoinstall ds="nocloud-net;s=http://${var.packer_http_ip}:{{ .HTTPPort }}/"<enter><wait>',
            "initrd /casper/initrd<enter><wait>",
            "boot<enter>",
        ]
    if os_profile == "rhel-kickstart":
        return [
            "<up><wait>e<wait>",
            "<down><down><end><wait>",
            " inst.text inst.ks=http://${var.packer_http_ip}:{{ .HTTPPort }}/kickstart.cfg",
            "<wait><leftCtrlOn>x<leftCtrlOff>",
        ]
    # Debian (matches packer/debian-13)
    return [
        "<esc><wait>",
        "auto <wait>",
        "/install/vmlinuz noapic ",
        "netcfg/use_autoconfig=true ",
        "preseed/url=http://${var.packer_http_ip}:{{ .HTTPPort }}/preseed.cfg ",
        "initrd=/install/initrd.gz -- <enter>",
        "<enter><wait>",
    ]
