<!-- p3portal.org -->
# Security Policy — P3 Portal Plus

This repository is the **Source-Available source repository** for the P3 Portal Plus Edition under `LICENSE-PLUS`. The source is readable for security review and audit purposes, but use, modification, and redistribution are restricted by that license. Public-disclosure conventions used for OSS projects do not apply here in the same way — security reports go through a private contact path, see below.

## Scope

Security issues that affect Plus-specific code paths (`backend/plus/`, `frontend/src/plus/`, the Plus license tooling, or the `build-plus.yml` build pipeline) belong here.

For security issues that affect the public **AGPLv3 Core** of P3 Portal (`backend/core/`, `backend/routers/` Core-Endpunkte, `frontend/src/` non-Plus paths), please follow the public Core security policy:

→ https://github.com/P3Portal-org/p3portal/security/policy

## How to report a Plus-specific security issue

Use the **Security report** Issue template in this repository:

→ https://github.com/P3Portal-org/p3portal-plus/issues/new?template=security_report.yml

The template enforces the no-source-code-paste policy and asks for the information that helps triage (impact, reproducer in prose, affected Plus image tag).

**Fallback:** if you cannot or do not want to use the public template, you may e-mail the maintainer at `license@p3portal.org`.

Information to include either way:

- Affected Plus feature or code path
- Reproduction steps (in prose, no exploit code)
- Impact assessment (data, integrity, availability)
- The Plus image tag/version under test (e.g. `ghcr.io/p3portal-org/p3portal-plus:v1.75.1-beta`)

Do not include any source code copied from this repository in the report. Source distribution is prohibited under `LICENSE-PLUS` even though the repository is Source-Available. Describing the affected code path by file name and line number is sufficient.

## Response

Solo-maintainer project — response times are best-effort, not bound by SLA. Critical issues affecting license-enforcement or data integrity are typically addressed within days.

A fix may be released as a coordinated update across the Core and Plus images. Plus-image fixes appear at `ghcr.io/p3portal-org/p3portal-plus:vX.Y.Z` after a `.core-version` bump and Plus-CI rebuild.

## What is NOT in scope

- Public-disclosure expectations (CVE assignment, public advisory, bug bounty) — none of these apply to this Source-Available, commercially-restricted project
- External PRs or collaboration on patches — by design, patches are written by the maintainer
- Vulnerability research on the running Plus image — permitted as a private exercise but reports follow the rules above

## License

Use of any information in this repository is governed by `LICENSE-PLUS`. Reporting a security issue does not grant any rights to use, modify, or redistribute the source code referenced in the report.

---

*Last updated: 2026. Maintainer contact: license@p3portal.org*
