// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-92: Editor-Modell-Defaults + Payload-Bau (SoT = strukturiertes Modell).
// Schema gespiegelt aus backend/plus/packer_editor/schemas.py.

// Standard-boot_command pro OS-Profil mit verdrahteter Installer-URL
// (`${var.packer_http_ip}:{{ .HTTPPort }}`) — gespiegelt aus
// installer.default_boot_command (AC-INST-5). Der Backend-Transpiler erwartet
// genau diese Form; sie wird nicht über einen EP ausgeliefert, daher hier als
// kurze, stabile Konstante dupliziert (dokumentiert).
export function defaultBootCommand(osProfile) {
  if (osProfile === 'rhel-kickstart') {
    return [
      '<up><wait>e<wait>',
      '<down><down><end><wait>',
      ' inst.text inst.ks=http://${var.packer_http_ip}:{{ .HTTPPort }}/kickstart.cfg',
      '<wait><leftCtrlOn>x<leftCtrlOff>',
    ]
  }
  // Debian (entspricht packer/debian-13)
  return [
    '<esc><wait>',
    'auto <wait>',
    '/install/vmlinuz noapic ',
    'netcfg/use_autoconfig=true ',
    'preseed/url=http://${var.packer_http_ip}:{{ .HTTPPort }}/preseed.cfg ',
    'initrd=/install/initrd.gz -- <enter>',
    '<enter><wait>',
  ]
}

/** Gemeinsame VM-Settings (beide Source-Typen, _SourceBase). */
function baseSourceFields() {
  return {
    cores: 2,
    memory_mb: 2048,
    disk_size_gb: 20,
    network_bridge: 'vmbr0',
    network_model: 'virtio',
    network_firewall: false,
    scsi_controller: 'virtio-scsi-pci',
    qemu_agent: true,
    cloud_init: true,
    template_description: '',
    ssh_username: 'root',
    ssh_timeout: '20m',
    ssh_private_key_name: '',
  }
}

export function emptyCloneSource() {
  return { type: 'proxmox-clone', ...baseSourceFields(), clone_template: '', full_clone: true }
}

export function emptyIsoSource() {
  return {
    type: 'proxmox-iso',
    ...baseSourceFields(),
    boot_command: defaultBootCommand('debian-preseed'),
    boot_wait: '5s',
    http_port: 8103,
  }
}

export function emptyInstaller() {
  return {
    os_profile: 'debian-preseed',
    language: 'en',
    country: 'US',
    locale: 'en_US.UTF-8',
    keyboard: 'us',
    timezone: 'UTC',
    hostname: '',
    root_password_plain: '',
    root_password_hash: null,
    username: 'sysadm',
    user_uid: 1000,
    user_password_plain: '',
    user_password_hash: null,
    packages: ['sudo', 'openssh-server', 'qemu-guest-agent'],
    ssh_public_key: '',
    optional: {},
    raw_override: false,
    raw_content: '',
  }
}

export function newModel() {
  return {
    schema_version: 1,
    id: '',
    name: '',
    description: '',
    required_role: 'operator',
    source: emptyIsoSource(),
    installer: emptyInstaller(),
    provisioners: [],
    side_files: {},
    hcl_override: false,
    hcl_content: '',
  }
}

// ── OS-Vorlagen (Prefill) ─────────────────────────────────────────────────────
// Schnellstart-Vorlagen für gängige OS: füllen ein sinnvolles, baubares ISO-
// Grundgerüst (Source-Typ proxmox-iso + passendes Installer-Profil + boot_command
// + Standard-Pakete). ISO-Datei, Passwörter und SSH-Key bleiben offen — die füllt
// der Nutzer pro Build bzw. im Installer-Builder.
function isoPreset({ name, description, osProfile, packages }) {
  return {
    schema_version: 1,
    id: deriveId(name),
    name,
    description,
    required_role: 'operator',
    source: {
      ...emptyIsoSource(),
      cores: 2,
      memory_mb: 2048,
      disk_size_gb: 20,
      ssh_username: 'root',
      boot_command: defaultBootCommand(osProfile),
      http_port: 8103,
    },
    installer: {
      ...emptyInstaller(),
      os_profile: osProfile,
      locale: 'en_US.UTF-8',
      keyboard: 'us',
      timezone: 'UTC',
      username: 'sysadm',
      packages,
    },
    provisioners: [],
    side_files: {},
    _idTouched: false,
  }
}

// cloud.cfg aus der bereitgestellten debian-13-Referenz (Proxmox-Cloud-Init-
// Kompatibilität). Wird in der „meine Vorlage"-Variante als file-Provisioner-
// Inhalt nach /etc/cloud/cloud.cfg geschrieben.
const DEBIAN_REF_CLOUD_CFG = `# The top level settings are used as module
# and system configuration.

# If this is set, 'root' will not be able to ssh
disable_root: false

# This will cause the set+update hostname module to not operate (if true)
preserve_hostname: false

# The modules that run in the 'init' stage
cloud_init_modules:
 - migrator
 - seed_random
 - bootcmd
 - write-files
 - growpart
 - resizefs
 - disk_setup
 - mounts
 - set_hostname
 - update_hostname
 - update_etc_hosts
 - ca-certs
 - rsyslog
 - users-groups
 - ssh

# The modules that run in the 'config' stage
cloud_config_modules:
 - emit_upstart
 - ssh-import-id
 - locale
 - set-passwords
 - grub-dpkg
 - apt-pipelining
 - apt-configure
 - ntp
 - timezone
 - disable-ec2-metadata
 - runcmd
 - byobu

# The modules that run in the 'final' stage
cloud_final_modules:
 - scripts-user
 - ssh-authkey-fingerprints
 - keys-to-console

# System and/or distro specific settings
# (not accessible to handlers/transforms)
system_info:
   distro: debian
   default_user:
     name: sysadm
     lock_passwd: True
     groups: [sudo]
     sudo: ["ALL=(ALL) NOPASSWD:ALL"]
     shell: /bin/bash
`

// Provisioner-Sequenz aus der debian-13-Referenz: QEMU-Agent/Cloud-Init
// installieren, cloud.cfg ablegen, Cloud-Init für Proxmox vorbereiten.
function debianRefProvisioners() {
  return [
    {
      type: 'shell', mode: 'inline', inline: [
        'echo set debconf to Noninteractive',
        "echo 'debconf debconf/frontend select Noninteractive' | sudo debconf-set-selections",
        'sudo rm -f /etc/sysctl.d/99-packer-ipv4only.conf',
        'sudo apt update',
        'sudo apt install qemu-guest-agent cloud-init vim cloud-guest-utils -y',
        'sudo systemctl start qemu-guest-agent',
      ],
    },
    { type: 'file', source_name: 'cloud.cfg', source_content: DEBIAN_REF_CLOUD_CFG, destination: '/tmp/cloud.cfg' },
    {
      type: 'shell', mode: 'inline', inline: [
        'echo cloud-init preperations...',
        'sudo rm -f /etc/cloud/cloud.cfg',
        'sudo rm -f /etc/cloud/cloud.cfg.d/*',
        'sudo rm -f /etc/cloud/templates/*sles*',
        'sudo rm -f /etc/cloud/templates/*ubuntu*',
        'sudo rm -f /etc/cloud/templates/*alpine*',
        'sudo rm -f /etc/cloud/templates/*rhel*',
        'sudo rm -f /etc/cloud/templates/*freebsd*',
        'sudo rm -f /etc/cloud/templates/*redhat*',
        'sudo rm -f /etc/cloud/templates/*opensuse*',
        'sudo rm -f /etc/cloud/templates/*suse*',
        'sudo rm -f /etc/cloud/templates/*fedora*',
        'sudo rm -f /etc/cloud/templates/sources.list*',
        'sudo mv /tmp/cloud.cfg /etc/cloud/',
      ],
    },
  ]
}

/** Geordnete Liste der Prefill-Vorlagen (Anzeige + build()).
 * Standard-Vorlagen sind generisch (en). Zusätzlich „Debian 13 (meine Vorlage)"
 * = originalgetreue Reproduktion der bereitgestellten debian-13-Referenz
 * (de_DE, sysadm, Provisioner + cloud.cfg). Der private SSH-Key (files/sysadm)
 * ist ein Secret und wird NICHT mitgeliefert — nur referenziert. */
export const OS_PRESETS = [
  {
    key: 'debian',
    label: 'Debian 13',
    build: () => isoPreset({
      name: 'Debian 13',
      description: 'Debian 13 (Trixie) Server-Template (von ISO, preseed).',
      osProfile: 'debian-preseed',
      packages: ['sudo', 'openssh-server', 'qemu-guest-agent'],
    }),
  },
  {
    key: 'debian-ref',
    label: 'Debian 13 (meine Vorlage)',
    build: () => {
      const m = isoPreset({
        name: 'Debian 13 (Trixie) Template',
        description: 'Debian 13 (Trixie) Server-Template auf Proxmox mit Cloud-Init und QEMU-Guest-Agent (an der debian-13-Referenz ausgerichtet, de_DE).',
        osProfile: 'debian-preseed',
        packages: ['sudo', 'openssh-server', 'qemu-guest-agent'],
      })
      return {
        ...m,
        source: { ...m.source, ssh_private_key_name: 'sysadm' },
        installer: {
          ...m.installer,
          language: 'de', country: 'DE', locale: 'de_DE.UTF-8',
          keyboard: 'de', timezone: 'Europe/Berlin',
        },
        provisioners: debianRefProvisioners(),
      }
    },
  },
  {
    key: 'ubuntu',
    label: 'Ubuntu 24.04',
    build: () => isoPreset({
      name: 'Ubuntu 24.04',
      description: 'Ubuntu 24.04 LTS Server-Template (von ISO, autoinstall/cloud-init).',
      osProfile: 'ubuntu-autoinstall',
      packages: ['openssh-server', 'qemu-guest-agent', 'sudo'],
    }),
  },
  {
    key: 'rocky',
    label: 'Rocky / Alma (RHEL 9)',
    build: () => isoPreset({
      name: 'Rocky Linux 9',
      description: 'Rocky-/AlmaLinux-9 Server-Template (von ISO, kickstart).',
      osProfile: 'rhel-kickstart',
      packages: ['openssh-server', 'qemu-guest-agent', 'sudo'],
    }),
  },
]

/** Leite eine gültige id aus dem Anzeigenamen ab (^[a-z0-9][a-z0-9_-]{0,63}$). */
export function deriveId(name) {
  const slug = String(name || '')
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '-')
    .replace(/^-+/, '')
    .replace(/-+$/, '')
    .slice(0, 64)
  return slug
}

/**
 * Baue die API-Payload aus dem UI-Modell. Schlüssel-Regeln:
 *  - installer wird nur bei proxmox-iso mitgesendet (Backend lehnt es bei clone
 *    mit 422 ab) → bei clone hart null.
 *  - leere Passwort-Felder werden nicht überschrieben (write-only, Merge im
 *    Backend; das Sidecar hält ohnehin nur den Hash).
 */
export function buildPayload(model) {
  const isIso = model.source?.type === 'proxmox-iso'
  const payload = {
    schema_version: model.schema_version ?? 1,
    id: model.id,
    name: model.name,
    description: model.description ?? '',
    required_role: model.required_role ?? 'operator',
    source: { ...model.source },
    provisioners: model.provisioners ?? [],
    side_files: model.side_files ?? {},
    hcl_override: model.hcl_override ?? false,
    hcl_content: model.hcl_content ?? '',
  }
  if (isIso && model.installer) {
    const inst = { ...model.installer }
    // Leere Plain-Passwörter weglassen (Backend behält gespeicherten Hash).
    if (!inst.root_password_plain) delete inst.root_password_plain
    if (!inst.user_password_plain) delete inst.user_password_plain
    payload.installer = inst
  } else {
    payload.installer = null
  }
  return payload
}
