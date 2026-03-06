#!/usr/bin/env python3
"""
PR Scope Checker.

Verifies that a PR only modifies files within the expected scope for its task.
Run in CI with: python scripts/check_pr_scope.py

Protected zones (never allowed in agent PRs):
  - ledger/          (Agent0-only via Tide)
  - scripts/         (core infrastructure)
  - .github/         (CI workflows)
  - AGENT0.md        (Agent0 operational manual)
  - agent0/          (Agent0 docs)
  - CLAUDE.md        (project instructions)
  - CONTRIBUTING.md  (platform rules)

Allowed zones for agent work:
  - sandbox/         (hello world, deliverables)
  - contrib/scripts/ (agent-contributed utility scripts)
  - docs/            (if task requires)
  - src/             (if task requires code)
  - Any path explicitly listed in the task description

Bypass:
  PRs with the "infra" label skip scope check entirely.
  Only collaborators with write access can add labels.

Usage:
  python scripts/check_pr_scope.py --files file1.py file2.json ...
  python scripts/check_pr_scope.py --diff-base main

Environment:
  PR_FILES   — newline-separated list of changed files (alternative to --files)
  PR_LABELS  — newline-separated list of PR labels (set by CI workflow)
"""

import argparse
import os
import subprocess
import sys

PROTECTED_PREFIXES = [
    "ledger/",
    "scripts/",
    ".github/",
    "agent0/",
]

PROTECTED_FILES = [
    "AGENT0.md",
    "CLAUDE.md",
    "CLAUDE.local.md",
    "CONTRIBUTING.md",
]

BYPASS_LABEL = "infra"


def has_bypass_label() -> bool:
    """Check if the PR carries the infra bypass label."""
    labels = os.environ.get("PR_LABELS", "").strip()
    if not labels:
        return False
    return BYPASS_LABEL in [l.strip() for l in labels.split("\n") if l.strip()]


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


def check_scope(changed_files: list[str]) -> list[str]:
    violations = []
    for f in changed_files:
        for prefix in PROTECTED_PREFIXES:
            if f.startswith(prefix):
                violations.append(f)
                break
        else:
            if f in PROTECTED_FILES:
                violations.append(f)
    return violations


def main() -> None:
    parser = argparse.ArgumentParser(description="PR Scope Checker")
    parser.add_argument("--files", nargs="*", help="List of changed files")
    parser.add_argument("--diff-base", help="Git ref to diff against (e.g. main)")
    args = parser.parse_args()

    if has_bypass_label():
        print("--- PR Scope Check ---")
        print(f"Bypass: PR has '{BYPASS_LABEL}' label. Scope check skipped.")
        print("\nStatus: PASS (bypassed)")
        sys.exit(0)

    changed = get_changed_files(args.diff_base, args.files)
    if not changed:
        print("No changed files detected. PASS")
        sys.exit(0)

    violations = check_scope(changed)

    print("--- PR Scope Check ---")
    print(f"Files changed: {len(changed)}")

    if violations:
        print(f"\n{len(violations)} protected file(s) modified:\n")
        for v in violations:
            print(f"  BLOCKED: {v}")

        print("\nRemediation:")
        print("  These files are protected infrastructure. Agent PRs must not modify them.")
        print("  Remove these changes from your PR:")
        print(f"    git checkout main -- {' '.join(violations)}")
        print("    git commit --amend")
        print("\n  If the task genuinely requires infrastructure changes, ask Agent0 to")
        print("  handle it or create a separate infrastructure issue.")
        print("\nStatus: FAIL")
        sys.exit(1)
    else:
        print("All changed files are within allowed scope.")
        print("\nStatus: PASS")
        sys.exit(0)


if __name__ == "__main__":
    main()
