#!/usr/bin/env python3
"""Orphan script detector.

Enumerates scripts/check_*.py files and reports any that are not referenced
in scripts/run_all_checks.py or .github/workflows/*.yml.

A script is considered "wired" if:
  - scripts/run_all_checks.py contains a wildcard glob pattern matching
    check_*.py (e.g., glob("check_*.py")), OR
  - The script's filename appears explicitly in run_all_checks.py or any
    .github/workflows/*.yml file.

Orphans are reported as WARN (not FAIL) — exit code is always 0.

Output: JSON to stdout with fields: status, orphans, summary.
  status   — "PASS" (no orphans) or "WARN" (orphans found)
  orphans  — list of {filename, line_count}
  summary  — human-readable string

Exit codes:
    0 — always (WARN is not a hard failure)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# Matches a glob-pattern string literal that covers all check_*.py files,
# e.g.: glob("check_*.py") or glob('check_*.py') in run_all_checks.py
_WILDCARD_RE = re.compile(r"""["']check_\*\.py["']""")


def _line_count(path: Path) -> int:
    """Return line count of a file, 0 on read error."""
    try:
        return len(path.read_text(encoding="utf-8").splitlines())
    except OSError:
        return 0


def _read_text(path: Path) -> str:
    """Return file text, empty string on read error."""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _has_wildcard_coverage(runner_path: Path) -> bool:
    """Return True if runner contains a glob pattern covering all check_*.py."""
    return bool(_WILDCARD_RE.search(_read_text(runner_path)))


def _mentions_file(text: str, filename: str) -> bool:
    """Return True if filename appears literally in text."""
    return filename in text


def run(root: Path) -> tuple[dict[str, Any], bool]:
    """Detect orphan check_*.py scripts.

    Returns (result_dict, passed) where passed is always True (WARN not FAIL).
    """
    scripts_dir = root / "scripts"
    runner = scripts_dir / "run_all_checks.py"
    workflows_dir = root / ".github" / "workflows"

    # Enumerate check_*.py, excluding this script and run_all_checks.py
    this_name = Path(__file__).name
    if not scripts_dir.is_dir():
        return {
            "status": "PASS",
            "orphans": [],
            "summary": "scripts/ directory not found",
        }, True

    check_scripts: list[Path] = sorted(
        p for p in scripts_dir.glob("check_*.py")
        if p.name not in {"run_all_checks.py", this_name}
    )

    if not check_scripts:
        return {
            "status": "PASS",
            "orphans": [],
            "summary": "no check_*.py scripts found",
        }, True

    # Does run_all_checks.py use a wildcard that covers all check_*.py?
    wildcard_covers_all = runner.exists() and _has_wildcard_coverage(runner)

    # Collect workflow file texts (if dir exists)
    workflow_texts: list[str] = []
    if workflows_dir.is_dir():
        for wf in sorted(workflows_dir.glob("*.yml")):
            workflow_texts.append(_read_text(wf))

    runner_text = _read_text(runner) if runner.exists() else ""

    orphans: list[dict[str, Any]] = []
    for script in check_scripts:
        if wildcard_covers_all:
            continue  # covered by wildcard in runner

        # Explicit mention in runner
        if _mentions_file(runner_text, script.name):
            continue

        # Explicit mention in any CI workflow
        if any(_mentions_file(wt, script.name) for wt in workflow_texts):
            continue

        orphans.append({
            "filename": script.name,
            "line_count": _line_count(script),
        })

    if orphans:
        n = len(orphans)
        names = ", ".join(o["filename"] for o in orphans)
        summary = f"{n} orphan script{'s' if n > 1 else ''} found: {names}"
        status = "WARN"
    else:
        n_checked = len(check_scripts)
        summary = f"{n_checked} script{'s' if n_checked != 1 else ''} checked, all wired"
        status = "PASS"

    return {
        "status": status,
        "orphans": orphans,
        "summary": summary,
    }, True  # always passes — WARN is not a hard failure


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Detect check_*.py scripts not wired into run_all_checks.py or CI."
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root (default: auto-detected from script location)",
    )
    args = parser.parse_args()

    if args.root:
        root = Path(args.root).resolve()
    else:
        root = Path(__file__).resolve().parent.parent

    result, passed = run(root)
    print(json.dumps(result, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
