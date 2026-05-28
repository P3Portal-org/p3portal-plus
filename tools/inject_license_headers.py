#!/usr/bin/env python3
"""Inject (or refresh) SPDX licence headers in all P3 Plus source files.

Usage:
  python tools/inject_license_headers.py          # inject/refresh headers
  python tools/inject_license_headers.py --check  # check only, exit 1 if missing

Exit codes:
  0  all headers present (or successfully injected)
  1  --check mode: one or more files are missing a valid header
  2  unexpected error

The script is idempotent: running it twice on an unchanged repository
produces no diff.

Header format per file type
────────────────────────────
Python (.py):
  # SPDX-License-Identifier: LicenseRef-P3-Plus
  # SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
  # === P3 PLUS – PROPRIETARY ===
  # Licensed under LICENSE-PLUS (see repo root)
  # Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
  # Contact: license@p3portal.org

JS/JSX/TS/TSX (.js/.jsx/.ts/.tsx):
  // SPDX-License-Identifier: LicenseRef-P3-Plus
  // SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
  // === P3 PLUS – PROPRIETARY ===
  // Licensed under LICENSE-PLUS (see repo root)
  // Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
  // Contact: license@p3portal.org

CSS (.css):
  /* SPDX-License-Identifier: LicenseRef-P3-Plus */
  /* SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de> */
  /* === P3 PLUS – PROPRIETARY === */
  /* Licensed under LICENSE-PLUS (see repo root) */
  /* Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception) */
  /* Contact: license@p3portal.org */
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running from any directory by adding the repo root to sys.path
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from tools.license_config import (  # noqa: E402
    AUTHOR_EMAIL,
    AUTHOR_NAME,
    COMMENT_STYLE,
    CONTACT_EMAIL,
    COPYRIGHT_YEAR,
    LICENSE_PLUS_REF,
    PLUS_DIRS,
)

# The sentinel that uniquely identifies a P3 Plus header block
_SPDX_SENTINEL = f"SPDX-License-Identifier: {LICENSE_PLUS_REF}"

# Number of lines at the top of a file we search for the sentinel
_SEARCH_WINDOW = 15


def _build_header(style: str) -> str:
    """Return the 6-line header string for the given comment style."""
    lines = [
        f"SPDX-License-Identifier: {LICENSE_PLUS_REF}",
        f"SPDX-FileCopyrightText: Copyright (C) {COPYRIGHT_YEAR} {AUTHOR_NAME} <{AUTHOR_EMAIL}>",
        "=== P3 PLUS – PROPRIETARY ===",
        "Licensed under LICENSE-PLUS (see repo root)",
        "Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)",
        f"Contact: {CONTACT_EMAIL}",
    ]
    if style == "hash":
        return "\n".join(f"# {line}" for line in lines) + "\n"
    elif style == "line":
        return "\n".join(f"// {line}" for line in lines) + "\n"
    elif style == "block":
        return "\n".join(f"/* {line} */" for line in lines) + "\n"
    else:
        raise ValueError(f"Unknown comment style: {style!r}")


def _has_header(content: str) -> bool:
    """Return True if the file already contains the SPDX sentinel."""
    for line in content.splitlines()[:_SEARCH_WINDOW]:
        if _SPDX_SENTINEL in line:
            return True
    return False


def _strip_old_header(content: str, style: str) -> str:
    """Remove an existing P3 Plus header block from the top of the file.

    Handles shebang lines (kept as line 0), then strips the contiguous
    comment block that contains the SPDX sentinel.
    """
    lines = content.splitlines(keepends=True)
    start = 0

    # Preserve shebang
    if lines and lines[0].startswith("#!"):
        start = 1

    # Find the first line of the old header block
    header_start: int | None = None
    for i in range(start, min(start + _SEARCH_WINDOW, len(lines))):
        if _SPDX_SENTINEL in lines[i]:
            # Walk backwards to find the actual start of the block
            j = i
            while j > start and _is_comment_line(lines[j - 1], style):
                j -= 1
            header_start = j
            break

    if header_start is None:
        return content  # Nothing to strip

    # Walk forward to find the end of the block
    header_end = header_start
    while header_end < len(lines) and _is_comment_line(lines[header_end], style):
        header_end += 1

    # Skip any blank line immediately after the block
    if header_end < len(lines) and lines[header_end].strip() == "":
        header_end += 1

    return "".join(lines[:start] + lines[header_end:])


def _is_comment_line(line: str, style: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if style == "hash":
        return stripped.startswith("#") and not stripped.startswith("#!")
    elif style == "line":
        return stripped.startswith("//")
    elif style == "block":
        return stripped.startswith("/*") or stripped.startswith("*")
    return False


def _inject_header(content: str, header: str, style: str) -> str:
    """Insert header after shebang (if present), before everything else."""
    lines = content.splitlines(keepends=True)
    insert_at = 0
    if lines and lines[0].startswith("#!"):
        insert_at = 1
    return "".join(lines[:insert_at]) + header + "\n" + "".join(lines[insert_at:])


def _collect_files() -> list[Path]:
    """Return all qualifying source files in the Plus directories."""
    files: list[Path] = []
    for dir_rel in PLUS_DIRS:
        plus_dir = _REPO_ROOT / dir_rel
        if not plus_dir.is_dir():
            continue
        for ext in COMMENT_STYLE:
            files.extend(plus_dir.rglob(f"*{ext}"))
    return sorted(files)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inject or check SPDX headers in P3 Plus source files."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check only; exit 1 if any file is missing a header (no writes).",
    )
    args = parser.parse_args(argv)

    files = _collect_files()
    missing: list[Path] = []
    refreshed: list[Path] = []

    for path in files:
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as exc:
            print(f"ERROR reading {path}: {exc}", file=sys.stderr)
            return 2

        if len(content.strip()) == 0:
            continue  # Skip empty files

        ext = path.suffix.lower()
        style = COMMENT_STYLE.get(ext)
        if style is None:
            continue

        header = _build_header(style)

        if _has_header(content):
            # Check if the header is up-to-date (refresh mode)
            stripped = _strip_old_header(content, style)
            expected = _inject_header(stripped, header, style)
            if expected != content:
                if not args.check:
                    path.write_text(expected, encoding="utf-8")
                    refreshed.append(path)
                else:
                    missing.append(path)
        else:
            missing.append(path)
            if not args.check:
                new_content = _inject_header(content, header, style)
                path.write_text(new_content, encoding="utf-8")

    if args.check:
        if missing:
            print(
                f"\n{len(missing)} file(s) in backend/plus/ or frontend/src/plus/ "
                "are missing the SPDX header.\n"
                "Run `python tools/inject_license_headers.py` to add it automatically.\n",
                file=sys.stderr,
            )
            for f in missing:
                print(f"  MISSING: {f.relative_to(_REPO_ROOT)}", file=sys.stderr)
            return 1
        else:
            print("All Plus files have valid SPDX headers. ✓")
            return 0
    else:
        total = len(missing) + len(refreshed)
        if total:
            for f in missing:
                print(f"  ADDED:     {f.relative_to(_REPO_ROOT)}")
            for f in refreshed:
                print(f"  REFRESHED: {f.relative_to(_REPO_ROOT)}")
            print(f"\n{total} file(s) updated.")
        else:
            print("All Plus files already have valid SPDX headers. Nothing to do. ✓")
        return 0


if __name__ == "__main__":
    sys.exit(main())
