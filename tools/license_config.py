"""Central license configuration for P3 Portal.

All author / copyright constants for SPDX headers live here.
The inject_license_headers.py script imports exclusively from this file.

MANUAL STATIC LOCATIONS – these four files must be updated by hand
when AUTHOR_NAME or AUTHOR_EMAIL changes:
  1. LICENSE                  (§7(b) author-attribution preamble)
  2. LICENSE-PLUS             (copyright line, contact)
  3. COMMERCIAL.md            (contact section)
  4. TRADEMARK.md             (pseudonym + contact)
Run `python tools/inject_license_headers.py` afterwards to refresh all
Plus source file headers automatically.
"""

AUTHOR_NAME: str = "rootq"
AUTHOR_EMAIL: str = "contact@rootq.de"
COPYRIGHT_YEAR: str = "2026"
PROJECT_NAME: str = "P3 Portal"
LICENSE_PLUS_REF: str = "LicenseRef-P3-Plus"
CONTACT_EMAIL: str = "license@p3portal.org"

# TODO: Identitätsmodell (UG / Anwalts-c/o / Postfach) vor erstem Plus-Verkauf
# festlegen — siehe COMMERCIAL.md "Status".  Sobald dieses Feld belegt wird,
# muss LICENSE-PLUS §8 (Gerichtsstand-Platzhalter) und COMMERCIAL.md
# Status-Section nachgepflegt werden.
LEGAL_ENTITY: None = None

# Directories that contain Plus source files (relative to repo root)
PLUS_DIRS: tuple[str, ...] = (
    "backend/plus",
    "frontend/src/plus",
)

# File extensions that receive SPDX headers, mapped to comment style
# "block" = /* ... */ (CSS)
# "line"  = // ... (JS/TS)
# "hash"  = # ... (Python)
COMMENT_STYLE: dict[str, str] = {
    ".py": "hash",
    ".js": "line",
    ".jsx": "line",
    ".ts": "line",
    ".tsx": "line",
    ".css": "block",
}
