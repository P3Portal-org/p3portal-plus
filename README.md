<!-- p3portal.org -->
# P3 Portal Plus

Source-Available Repository for the P3 Portal Plus Edition. Use, modification, and redistribution are governed by [`LICENSE-PLUS`](LICENSE-PLUS) — see the legal callout below.

> ## ⚠ LICENSE-PLUS — PROPRIETARY, KEY-REQUIRED
>
> All files in this repository are licensed under **`LICENSE-PLUS`**
> (see the file at repo root for the full terms).
>
> Activating Plus features in any environment requires a **valid
> `plus.lic` License Key** issued by the Licensor (§ 3.4 / § 5).
>
> Independent of any key, the licence prohibits:
> - Redistribution of the Plus Code in source or binary form (§ 3.1)
> - Selling, renting, leasing, or sublicensing the Plus Code (§ 3.1)
> - Modification of the Plus Code, except as permitted in § 4 (§ 3.2)
> - Forks or derivatives under the same or a confusingly similar
>   name (§ 3.3)
>
> § 4 grants a narrow security-patch and own-use exception for
> licensed instances. Any modification under § 4 automatically
> assigns its IP rights to the Licensor (§ 4.2) and may not be
> redistributed (§ 4.3).
>
> Plus license sales are currently inactive (`LEGAL_ENTITY = None`
> in `tools/license_config.py`). No commercial licenses are being
> issued at this time.
>
> See also: `TRADEMARK.md`, `SECURITY.md`, `CONTRIBUTING.md`.

For the public **AGPLv3 Core** (which is genuinely free software under
AGPLv3 terms), see: https://github.com/P3Portal-org/p3portal

## Features

Plus adds to Core (non-exhaustive list):

- **Stacks** — declarative VM infrastructure as code: define a stack
  in YAML or a form, version it, and plan / deploy / destroy it via
  the bundled OpenTofu engine, with drift detection
- **VM / LXC config snapshots** — save a VM or container `.conf` as a
  versioned JSON snapshot, diff it, and restore selected keys
- **Auto-snapshots on a schedule** — Proxmox-native and config
  snapshots on a cron schedule with keep-last / GFS retention
- **Scheduled Jobs** — cron-based execution of Ansible playbooks, SSH
  commands, and VM power actions
- **Resource Pools with quotas** — own portal pools with CPU / RAM /
  disk limits per user or group
- **Approval workflow** — four-eyes principle for playbook runs,
  packer builds, template deletions, owner-change requests
- **Multi-node / multi-cluster dashboard** — independent Proxmox
  installations side by side
- **Playbook permission whitelists** — per user or group control over
  which playbooks may be executed
- **Alert presets, SMTP delivery, webhook delivery** — beyond Core's
  banner-only alerts
- **Theme editor with colour picker** — visual UI theming
- **Git-Sync for playbooks and Packer templates** — automatic sync of
  `/ansible` and `/packer` from an external Git repository
- **Owner auto-assignment on deploy** — deployer becomes the VM owner
  via the resolver pipeline
- **Higher Core limits removed** — Plus instances have unlimited
  users, groups, role presets, ownerships, scheduled jobs per user
  (Core caps these — see the "Core vs. Plus" table in the Core README)

## Deploy

A ready-to-use [`docker-compose.yml`](docker-compose.yml) and
[`.env.example`](.env.example) are in this repository.

```bash
# Docker
docker compose up -d

# Podman
podman-compose up -d
```

Portal serves on `https://<host>:8443`. The Setup Wizard runs on
first visit and walks you through admin account, Proxmox connection,
API tokens, and licence file upload.

## What this repo contains

A rolling snapshot of the Plus paths from the maintainer's private working copy:

| Path | Origin |
|---|---|
| `backend/plus/` | Mediator-based Plus hook system |
| `frontend/src/plus/` | Plus React components (Pools, Approvals, GitSync, etc.) |
| `tools/inject_license_headers.py` | SPDX header injection tool |
| `tools/license_config.py` | Author + LEGAL_ENTITY config |
| `LICENSE-PLUS` | Source-available license text |
| `.githooks/pre-commit` | License header check |
| `.core-version` | Pinned Core repo tag (Plus is built against this Core version) |
| `.github/workflows/` | Plus image build + capability drift test |

This repo is **never edited directly**. Source of truth is the maintainer's `my-code/` working copy + `my-code/plus-publish/` for Plus-Repo-specific build infrastructure. A rolling snapshot is produced by `tools/sync.sh` in the maintainer's environment.

## How the Plus image is built

The Plus image at `ghcr.io/p3portal-org/p3portal-plus` is produced by combining:

1. **Core source** — cloned from `github.com/P3Portal-org/p3portal` at the tag pinned in `.core-version`
2. **Plus paths** — overlaid on top of the Core worktree from this repo
3. **Standard Docker build** — using the Core `Dockerfile` with `EDITION=plus` build arg

Build workflow: `.github/workflows/build-plus.yml`

## `.core-version` policy

Plain text file, one line, content is an **existing tag** in the Core repo (no branches, no commit SHAs — only tags for reproducibility).

Bumping the pin is a deliberate, manual decision (or via automated PR when the Core-Tag-Push webhook is wired up):

1. Confirm that Plus hook implementations match the Core `CAPABILITY_KEYS` of the new tag (capability drift test must pass)
2. Update `.core-version` in the maintainer's `my-code/plus-publish/.core-version`
3. Sync + push → CI rebuilds Plus image against new Core base

## Security

Bug reports for Plus-specific issues: contact the maintainer privately. See `SECURITY.md` in the public Core repo for the general reporting policy.

## Image registry

- Plus image: `ghcr.io/p3portal-org/p3portal-plus:{latest, vX.Y.Z}`
- Provenance label on each image: `p3portal.core_version=<pinned-core-tag>`

The old `ghcr.io/p3portal-org/p3portal:plus` image stream (combined Core+Plus before the repo split) is deprecated and no longer rebuilt.

## Built with AI assistance

Significant portions of this codebase were written with the help of
AI coding assistants (primarily Anthropic Claude). The maintainer
designs the architecture, drives every feature, reviews each change
and is responsible for the resulting code and its licensing.

This disclosure is made in the interest of transparency. It does not
affect the licence terms: this repository's source is covered by
`LICENSE-PLUS` as specified at the repo root.

---

Solo-maintainer project. External PRs are not accepted and are auto-closed by `.github/workflows/close-prs.yml`. The four Solo-Owner pillars are: the Mediator pattern + close-prs.yml + LEGAL_ENTITY=None + Source-Available under LICENSE-PLUS (modification/redistribution prohibited).
