#!/usr/bin/env python3
"""
Dead Branch Link Detector.

Scans remote agent branches and reports those whose linked GitHub issue is CLOSED.
A "dead branch" is one that exists on the remote but whose task issue has been closed —
it's orphaned work that clutters the repo.

Output: JSON with status (PASS/FAIL), dead_branches list, cleanup_commands list.
Exit 0 if no dead branches found, exit 1 if any dead branches found.

REPORT-ONLY: does NOT delete any branches.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from typing import Any

# Ensure UTF-8 output on all platforms (Windows may default to cp1252)
if hasattr(sys.stdout, "buffer") and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

REPO = "WeTheAgents/wetheagents"
REMOTE = "origin"
BRANCH_PREFIX = "agent/"


def list_remote_branches(remote: str = REMOTE) -> tuple[list[str], str | None]:
    """Return agent branch names from git ls-remote --heads."""
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--heads", remote],
            capture_output=True,
            check=True,
            text=True,
        )
    except FileNotFoundError:
        return [], "git not found in PATH"
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        return [], detail

    branches: list[str] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 2 or not parts[1].startswith("refs/heads/"):
            continue
        branch = parts[1][len("refs/heads/"):]
        if branch.startswith(BRANCH_PREFIX):
            branches.append(branch)
    return branches, None


def extract_issue_number(branch: str) -> int | None:
    """Return issue number for agent/{name}/{number}-{slug} branches, or None."""
    parts = branch.split("/")
    # Must be exactly: agent / <name> / <number>-<slug>
    if len(parts) != 3 or parts[0] != "agent":
        return None
    issue_part = parts[2].split("-", 1)[0]
    if not issue_part.isdigit():
        return None
    return int(issue_part)


def get_issue_state(issue_number: int, repo: str = REPO) -> str | None:
    """Query GitHub CLI for issue state. Returns 'OPEN', 'CLOSED', or None on error."""
    try:
        result = subprocess.run(
            ["gh", "issue", "view", str(issue_number), "--json", "state", "--repo", repo],
            capture_output=True,
            check=True,
            text=True,
        )
    except FileNotFoundError:
        return None
    except subprocess.CalledProcessError:
        return None

    try:
        data = json.loads(result.stdout)
        return data.get("state")
    except (json.JSONDecodeError, AttributeError):
        return None


def scan_dead_branches(
    remote: str = REMOTE,
    repo: str = REPO,
    _list_fn: Any = None,
    _state_fn: Any = None,
) -> dict[str, Any]:
    """
    Scan remote branches and return a report dict.

    _list_fn / _state_fn allow injection for tests.
    """
    list_fn = _list_fn if _list_fn is not None else list_remote_branches
    state_fn = _state_fn if _state_fn is not None else get_issue_state

    branches, fetch_error = list_fn(remote)

    dead_branches: list[str] = []
    skipped: list[str] = []

    for branch in sorted(branches):
        issue_number = extract_issue_number(branch)
        if issue_number is None:
            skipped.append(branch)
            continue

        state = state_fn(issue_number, repo)
        if state is None:
            # gh call failed — skip, don't falsely flag
            skipped.append(branch)
            continue

        if state == "CLOSED":
            dead_branches.append(branch)

    cleanup_commands = [
        f"git push {remote} --delete {b}" for b in dead_branches
    ]

    if fetch_error:
        status = "ERROR"
    elif dead_branches:
        status = "FAIL"
    else:
        status = "PASS"

    return {
        "status": status,
        "remote": remote,
        "repo": repo,
        "branches_scanned": len(branches),
        "dead_branches": dead_branches,
        "cleanup_commands": cleanup_commands,
        "skipped": skipped,
        "fetch_error": fetch_error,
    }


def main() -> int:
    report = scan_dead_branches()

    print(json.dumps(report, indent=2))

    if report["dead_branches"]:
        print("\n--- Cleanup commands (copy-paste to delete dead branches) ---")
        for cmd in report["cleanup_commands"]:
            print(cmd)

    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
