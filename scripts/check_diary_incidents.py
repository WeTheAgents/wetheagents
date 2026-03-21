#!/usr/bin/env python3
"""
Diary Incident Report Checker.

Verifies that every diary entry in agent0_diary/ has a corresponding
.incidents.md file. Enforces the antifragility loop: every session
must document what went wrong (or confirm nothing did).

Run in CI with: python scripts/check_diary_incidents.py --diff-base origin/main

Diary entries are files matching: agent0_diary/YYYY-MM-DD.md or YYYY-MM-DD-N.md
Excluded from matching:
  - AGENTS.md (guidelines, not a diary entry)
  - *.incidents.md (incident reports themselves)
  - next_session_briefing_*.md (briefing files)
  - NNN_*.md (legacy numbered entries, e.g. 001_first_day.md)

Usage:
  python scripts/check_diary_incidents.py --files file1.md file2.md ...
  python scripts/check_diary_incidents.py --diff-base main

Environment:
  PR_FILES  — newline-separated list of changed files (alternative to --files)
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

# Matches YYYY-MM-DD.md or YYYY-MM-DD-N.md (where N is a session number)
DIARY_ENTRY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(-\d+)?\.md$")

DIARY_DIR = "agent0_diary/"


def get_changed_files(diff_base: str | None, files: list[str] | None) -> list[str]:
    if files:
        return files

    env_files = os.environ.get("PR_FILES", "").strip()
    if env_files:
        return [f for f in env_files.split("\n") if f.strip()]

    if diff_base:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{diff_base}...HEAD"],
            capture_output=True, text=True, check=True,
        )
        return [f for f in result.stdout.strip().split("\n") if f.strip()]

    print("Error: provide --files, --diff-base, or set PR_FILES env var.")
    print("  Fix: run with --diff-base main to compare against main branch")
    sys.exit(2)


def find_diary_entries(changed_files: list[str]) -> list[str]:
    """Find diary entries among changed files (not incident reports, not metadata)."""
    entries = []
    for f in changed_files:
        if not f.startswith(DIARY_DIR):
            continue
        basename = f[len(DIARY_DIR):]
        if "/" in basename:
            continue
        if basename.endswith(".incidents.md"):
            continue
        if DIARY_ENTRY_RE.match(basename):
            entries.append(f)
    return entries


def expected_incident_path(diary_path: str) -> str:
    """Given agent0_diary/YYYY-MM-DD.md, return agent0_diary/YYYY-MM-DD.incidents.md."""
    assert diary_path.endswith(".md")
    return diary_path[:-3] + ".incidents.md"


def check_incidents(
    diary_entries: list[str], changed_files: list[str],
) -> list[tuple[str, str]]:
    """Return (diary_path, expected_incident_path) for missing reports."""
    changed_set = set(changed_files)
    missing = []
    for entry in diary_entries:
        incident = expected_incident_path(entry)
        if incident not in changed_set:
            missing.append((entry, incident))
    return missing


def main() -> None:
    parser = argparse.ArgumentParser(description="Diary Incident Report Checker")
    parser.add_argument("--files", nargs="*", help="List of changed files")
    parser.add_argument("--diff-base", help="Git ref to diff against (e.g. main)")
    args = parser.parse_args()

    changed = get_changed_files(args.diff_base, args.files)
    if not changed:
        print("No changed files detected. PASS")
        sys.exit(0)

    diary_entries = find_diary_entries(changed)

    print("--- Diary Incident Report Check ---")
    print(f"Files changed: {len(changed)}")
    print(f"Diary entries found: {len(diary_entries)}")

    if not diary_entries:
        print("No diary entries in this PR.")
        print("\nStatus: PASS")
        sys.exit(0)

    missing = check_incidents(diary_entries, changed)

    if missing:
        print(f"\n{len(missing)} diary entry/entries missing incident reports:\n")
        for diary, incident in missing:
            print(f"  MISSING: {diary}")
            print(f"           expected: {incident}")

        print("\nRemediation:")
        print("  Every diary entry must have a corresponding .incidents.md file.")
        print("  Create the missing file(s):")
        for _, incident in missing:
            print(f"    touch {incident}")
        print("")
        print("  If no issues occurred, use the 'all clear' template:")
        print("    # Incident Report — YYYY-MM-DD")
        print("    ## All Clear")
        print("    No first-seen errors or incidents this session.")
        print("")
        print("  See agent0_diary/AGENTS.md for the full incident report format.")
        print("\nStatus: FAIL")
        sys.exit(1)
    else:
        print("All diary entries have corresponding incident reports.")
        print("\nStatus: PASS")
        sys.exit(0)


if __name__ == "__main__":
    main()
