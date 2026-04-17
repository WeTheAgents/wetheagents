#!/usr/bin/env python3
"""Validate mandatory safety-script coverage in .githooks/pre-commit."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from pathlib import Path
from typing import Any

MANDATORY_SCRIPTS = (
    "check_idem_keys.py",
    "check_invariant.py",
    "genome_guard.py",
)

_SCRIPT_REF_RE = re.compile(r"scripts/(?P<name>[A-Za-z0-9_]+\.py)\b")


def _read_text(path: Path) -> str:
    """Return file text, or an empty string if the file is unreadable."""
    try:
        return path.read_text(encoding="utf-8-sig")
    except OSError:
        return ""


def _logical_lines(text: str) -> list[str]:
    """Join shell lines that end with a continuation backslash."""
    lines: list[str] = []
    buffer = ""

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if buffer:
            buffer += line.lstrip()
        else:
            buffer = line

        if buffer.endswith("\\"):
            buffer = buffer[:-1] + " "
            continue

        lines.append(buffer)
        buffer = ""

    if buffer:
        lines.append(buffer)

    return lines


def parse_invoked_scripts(hook_text: str) -> list[str]:
    """Return unique script names invoked via python from the hook."""
    invoked: list[str] = []
    seen: set[str] = set()

    for line in _logical_lines(hook_text):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        try:
            tokens = shlex.split(stripped, comments=True, posix=True)
        except ValueError:
            continue

        if not tokens or tokens[0] not in {"python", "python3"}:
            continue

        for token in tokens[1:]:
            match = _SCRIPT_REF_RE.search(token)
            if match is None:
                continue

            name = match.group("name")
            if name in seen:
                continue
            seen.add(name)
            invoked.append(name)

    return invoked


def _summary(
    missing_mandatory: list[str],
    dead_references: list[str],
    hook_exists: bool,
) -> str:
    """Build a short human-readable summary."""
    parts: list[str] = []

    if not hook_exists:
        parts.append("hook file not found")

    if missing_mandatory:
        count = len(missing_mandatory)
        noun = "script" if count == 1 else "scripts"
        names = ", ".join(missing_mandatory)
        parts.append(f"missing {count} mandatory {noun}: {names}")
    else:
        parts.append("all mandatory scripts present")

    if dead_references:
        count = len(dead_references)
        noun = "reference" if count == 1 else "references"
        names = ", ".join(dead_references)
        parts.append(f"{count} dead {noun}: {names}")

    return "; ".join(parts)


def run(root: Path, hook_path: Path | None = None) -> tuple[dict[str, Any], bool]:
    """Check whether the hook covers every mandatory safety script."""
    hook = hook_path or (root / ".githooks" / "pre-commit")
    scripts_dir = root / "scripts"

    hook_text = _read_text(hook)
    invoked = parse_invoked_scripts(hook_text)

    missing_mandatory = sorted(
        name for name in MANDATORY_SCRIPTS
        if name not in invoked
    )
    dead_references = sorted(
        name for name in invoked
        if not (scripts_dir / name).is_file()
    )

    passed = hook.is_file() and not missing_mandatory
    result = {
        "status": "PASS" if passed else "FAIL",
        "missing_mandatory": missing_mandatory,
        "dead_references": dead_references,
        "summary": _summary(missing_mandatory, dead_references, hook.is_file()),
    }
    return result, passed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check whether .githooks/pre-commit invokes mandatory safety scripts."
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root (default: auto-detected from script location)",
    )
    parser.add_argument(
        "--hook",
        default=None,
        help="Hook path relative to --root or as an absolute path",
    )
    args = parser.parse_args()

    if args.root:
        root = Path(args.root).resolve()
    else:
        root = Path(__file__).resolve().parent.parent

    hook_path: Path | None = None
    if args.hook:
        hook_path = Path(args.hook)
        if not hook_path.is_absolute():
            hook_path = root / hook_path

    result, passed = run(root, hook_path)
    print(json.dumps(result, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
