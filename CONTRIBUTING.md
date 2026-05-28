<!-- p3portal.org -->
# Contributing to P3 Portal Plus

Thanks for your interest in P3 Portal Plus. This file describes
how contributions work in practice, so there are no surprises.

## Current status: closed-contribution Source-Available project

P3 Portal Plus is a **Source-Available** (not Free or Open Source)
project licensed under `LICENSE-PLUS` (see file at repo root).
**External pull requests are not accepted** and are automatically
closed by the [`.github/workflows/close-prs.yml`](.github/workflows/close-prs.yml)
workflow.

This is not a comment on contribution quality. The reasons are
specific to the Plus Edition:

1. **`LICENSE-PLUS` restricts modifications** (§ 3.2 + § 4): the Plus
   Code may only be modified within the narrow security-patch and
   own-use exception in § 4. Any such modification automatically
   assigns its IP rights to the Licensor (§ 4.2) and may not be
   redistributed (§ 4.3). Accepting an external PR with substantial
   functional changes would be outside that exception unless the PR
   author has separately negotiated a contribution agreement with
   the Licensor.
2. **Solo-maintainer project.** The Plus Edition is maintained by
   a single person, who is also the sole copyright holder of all
   Plus code in this tree.
3. **No active Plus-Verkauf right now.** `LEGAL_ENTITY = None` in
   `tools/license_config.py` — no new commercial Plus licenses are
   being issued. Without a commercial framework, there is no
   structure to receive paid maintenance or contribution
   relationships.

If the project's structure changes (a legal entity is set up,
Plus-Verkauf becomes active, a Contributor License Agreement /
CLA is introduced), this file will be updated and the contribution
policy may evolve.

## What IS welcome

### Security reports

**Security issues that affect Plus-specific code paths** are
reported via the GitHub Issue template:

→ https://github.com/P3Portal-org/p3portal-plus/issues/new?template=security_report.yml

The template enforces the no-source-code-paste policy. As a fallback
you may e-mail `license@p3portal.org`.

See [SECURITY.md](SECURITY.md) for the full policy and the
information to include in your report.

**Security issues that affect the AGPLv3 Core** of P3 Portal
(everything outside `backend/plus/` and `frontend/src/plus/`)
belong in the public Core repository's security policy:

→ https://github.com/P3Portal-org/p3portal/security/policy

### Bug reports about Plus features

You may open a public issue in this repository describing a
**reproduction recipe for a Plus bug** — input, expected
behaviour, observed behaviour, the Plus image tag under test
(e.g. `ghcr.io/p3portal-org/p3portal-plus:v1.75.1-beta`). Do not
paste source code from this repository in the report; describing
file paths and line numbers is sufficient.

Bug reports are not pull requests and are not auto-closed.

### Source review

You may read the source for the purpose of security review or
audit. You may discuss the source publicly, link to specific
files, and quote short passages in good-faith technical discussion.
You may not redistribute the source in whole or in substantial
part — see `LICENSE-PLUS` for the precise terms.

## What is NOT welcome

- Pull requests (auto-closed)
- Forks intended for redistribution or independent maintenance
- Reverse-engineering of the runtime license-verification mechanism
  (`plus.enc` envelope encryption + `plus.lic` key); see
  `LICENSE-PLUS` §3.2 / §6 for the precise scope
- Issues whose primary intent is to request that the project
  change to a more permissive license (those requests can be
  e-mailed to `license@p3portal.org`, but they are subject to the
  Licensor's discretion and will not be debated in public issues)

## Solo-Owner-Trias

P3 Portal Plus operates under a four-pillar solo-owner posture
to keep the project's legal structure clean for a single
copyright holder:

1. **PROJ-60 Mediator pattern** — Core depends on no Plus symbol
   directly, so Plus can be developed and released independently
2. **`close-prs.yml`** — external PRs auto-closed on both Core
   and Plus repositories
3. **`LEGAL_ENTITY = None`** — Plus-Verkauf inactive, no
   commercial-license obligations
4. **Source-Available, not Free Software** — `LICENSE-PLUS` text
   at repo root, SPDX header `LicenseRef-P3-Plus` on every Plus
   source file, modification prohibited

The fourth pillar evolved from an earlier "Plus-Code not public"
posture (PROJ-72 Phase A/B) into "Source-Available under
LICENSE-PLUS" once the legal protection mechanism was understood
to function independently of repo visibility. Both postures
protect the code; the current one is friendlier for discovery and
external review.

## Trade names and pseudonym

See [TRADEMARK.md](TRADEMARK.md). Briefly: "P3 Portal" and the
domain names `p3portal.org` / `rootq.de` are not licensed by
`LICENSE-PLUS`. "rootq" is the author's pseudonym under §13 UrhG
(not a trade mark). Forks (which are prohibited by `LICENSE-PLUS`
anyway) must not use any of these names in a way that creates
confusion with the original project.

---

*If anything in this file is unclear, e-mail* `license@p3portal.org`.
