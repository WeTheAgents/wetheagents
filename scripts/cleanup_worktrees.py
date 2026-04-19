#!/usr/bin/env python3
"""Prune stale git worktrees.

Two categories are flagged:
  prunable   — git marks these as prunable (checked-out path no longer exists).
  temp-stale — worktrees in temp/scratch locations older than 14 days.

Usage
-----
  python scripts/cleanup_worktrees.py           # dry-run
  python scripts/cleanup_worktrees.py --apply   # prune prunable worktrees

Note: temp-stale worktrees are always reported but never auto-deleted.
Remove them manually with: git worktree remove <path>
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STALE_DAYS = 14

# Patterns that identify temp/scratch worktree locations.
_TEMP_SUBSTRINGS = (
    "/Temp/",
    "\\Temp\\",
    "AppData/Local/Temp",
    "AppData\\Local\\Temp",
    ".codex_tmp",
    ".claude/worktrees",
    ".claude\\worktrees",
)


# ── Subprocess helper ─────────────────────────────────────────────────────────

def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)


# ── Worktree parsing ──────────────────────────────────────────────────────────

def _parse_worktrees() -> list[dict]:
    """Parse `git worktree list --porcelain` into structured records."""
    r = _run(["git", "worktree", "list", "--porcelain"])
    worktrees: list[dict] = []
    current: dict = {}

    for line in r.stdout.splitlines():
        if line.startswith("worktree "):
            if current:
                worktrees.append(current)
            current = {
                "path": line[9:],
                "sha": None,
                "branch": None,
                "detached": False,
                "prunable": False,
                "prunable_reason": "",
            }
        elif line.startswith("HEAD "):
            current["sha"] = line[5:].strip()
        elif line.startswith("branch "):
            b = line[7:].strip()
            current["branch"] = b[len("refs/heads/"):] if b.startswith("refs/heads/") else b
        elif line.strip() == "detached":
            current["detached"] = True
        elif line.startswith("prunable "):
            current["prunable"] = True
            current["prunable_reason"] = line[9:].strip()
        elif line.startswith("locked "):
            current["locked"] = True

    if current:
        worktrees.append(current)

    return worktrees


def _is_temp_path(path: str) -> bool:
    return any(s in path for s in _TEMP_SUBSTRINGS)


def _path_age_days(path: str) -> float | None:
    """Return age in days based on directory mtime, or None if path is missing."""
    try:
        mtime = os.path.getmtime(path)
        age_seconds = datetime.now(timezone.utc).timestamp() - mtime
        return age_seconds / 86400.0
    except OSError:
        return None


# ── Main ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Prune prunable worktrees (runs git worktree prune)",
    )
    args = parser.parse_args(argv)

    worktrees = _parse_worktrees()

    # ── Category 1: prunable (git already knows about these) ─────────────────
    prunable = [w for w in worktrees if w.get("prunable")]

    # ── Category 2: temp-stale ────────────────────────────────────────────────
    temp_stale: list[dict] = []
    for w in worktrees:
        if not _is_temp_path(w["path"]):
            continue
        age_days = _path_age_days(w["path"])
        if age_days is None or age_days > STALE_DAYS:
            temp_stale.append({**w, "age_days": round(age_days, 1) if age_days is not None else None})

    # ── Report ────────────────────────────────────────────────────────────────
    print("=== Worktree Cleanup Report ===")

    print(f"\n[prunable] {len(prunable)} worktrees marked prunable by git:")
    for w in prunable:
        label = w["branch"] or ("(detached)" if w["detached"] else "(unknown)")
        print(f"  {w['path']}  [{label}]  — {w['prunable_reason']}")

    print(f"\n[temp-stale] {len(temp_stale)} temp worktrees older than {STALE_DAYS}d (report only):")
    for w in temp_stale:
        label = w["branch"] or ("(detached)" if w["detached"] else "(unknown)")
        age_str = f"{w['age_days']}d" if w["age_days"] is not None else "path missing"
        print(f"  {w['path']}  [{label}]  — {age_str}")

    print(
        f"\nSUMMARY: prunable={len(prunable)} temp_stale={len(temp_stale)}"
    )

    if not args.apply:
        print("\n[dry-run] No changes made. Use --apply to prune.")
        return 0

    # ── Apply ─────────────────────────────────────────────────────────────────
    print("\n[apply] Running git worktree prune…")
    r = _run(["git", "worktree", "prune"])
    if r.returncode == 0:
        print("[done] git worktree prune complete.")
        if r.stdout.strip():
            print(r.stdout.strip())
    else:
        print(f"[error] git worktree prune failed (exit {r.returncode}):")
        print(r.stderr.strip())
        return 1

    if temp_stale:
        print(
            f"\n[note] {len(temp_stale)} temp-stale worktree(s) were NOT auto-pruned.\n"
            "  Remove manually: git worktree remove <path>"
        )
        for w in temp_stale:
            print(f"    {w['path']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
