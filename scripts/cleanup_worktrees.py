#!/usr/bin/env python3
"""Summarize git worktree hygiene and optionally run git worktree prune."""

from __future__ import annotations

import argparse
import io
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _stdout_needs_utf8() -> bool:
    encoding = (sys.stdout.encoding or "").lower().replace("-", "")
    return hasattr(sys.stdout, "buffer") and encoding != "utf8"


# Ensure UTF-8 output on all platforms (Windows may default to cp1251/cp1252).
if _stdout_needs_utf8():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


@dataclass
class WorktreeInfo:
    """Parsed worktree metadata from git worktree list --porcelain."""

    path: Path
    branch: str | None
    exists: bool
    age_days: float | None
    temp_dir: bool
    old_temp_dir: bool


def _repo_root_from(root: str | None) -> Path:
    if root:
        return Path(root).resolve()
    return Path(__file__).resolve().parent.parent


def _run(
    args: list[str],
    *,
    cwd: Path,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        check=check,
        text=True,
    )


def _parse_worktree_porcelain(text: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    current: dict[str, str] = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            if current:
                entries.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value

    if current:
        entries.append(current)

    return entries


def _is_temp_dir(path: Path) -> bool:
    temp_root = Path(tempfile.gettempdir()).resolve(strict=False)
    candidate = path.resolve(strict=False)
    try:
        return candidate.is_relative_to(temp_root)
    except AttributeError:
        candidate_str = str(candidate).replace("\\", "/").lower()
        temp_str = str(temp_root).replace("\\", "/").lower()
        return candidate_str == temp_str or candidate_str.startswith(f"{temp_str}/")


def _directory_age_days(path: Path, *, now: datetime) -> float | None:
    if not path.exists():
        return None
    modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return round((now - modified_at).total_seconds() / 86400.0, 1)


def list_worktrees(
    root: Path,
    *,
    temp_days: int,
    now: datetime | None = None,
) -> list[WorktreeInfo]:
    if now is None:
        now = datetime.now(timezone.utc)

    result = _run(["git", "worktree", "list", "--porcelain"], cwd=root)
    entries = _parse_worktree_porcelain(result.stdout)
    threshold = timedelta(days=temp_days)
    worktrees: list[WorktreeInfo] = []

    for entry in entries:
        raw_path = entry.get("worktree")
        if not raw_path:
            continue
        path = Path(raw_path)
        branch_ref = entry.get("branch")
        branch_name = (
            branch_ref[len("refs/heads/") :]
            if branch_ref and branch_ref.startswith("refs/heads/")
            else branch_ref
        )
        exists = path.exists()
        age_days = _directory_age_days(path, now=now)
        temp_dir = _is_temp_dir(path)
        old_temp_dir = bool(
            temp_dir and age_days is not None and timedelta(days=age_days) > threshold
        )
        worktrees.append(
            WorktreeInfo(
                path=path,
                branch=branch_name,
                exists=exists,
                age_days=age_days,
                temp_dir=temp_dir,
                old_temp_dir=old_temp_dir,
            )
        )

    return worktrees


def run_prune(root: Path, *, apply: bool) -> tuple[str, str]:
    args = ["git", "worktree", "prune"]
    if not apply:
        args.append("--dry-run")
    args.append("--verbose")
    result = _run(args, cwd=root, check=False)
    output = (result.stdout or "").strip()
    errors = (result.stderr or "").strip()
    return output, errors


def render_report(
    worktrees: list[WorktreeInfo],
    *,
    prune_output: str,
    prune_errors: str,
    apply: bool,
    temp_days: int,
) -> str:
    old_temp_worktrees = [item for item in worktrees if item.old_temp_dir]
    lines = [
        "WORKTREE CLEANUP",
        f"Mode: {'apply' if apply else 'dry-run'}",
        f"Registered worktrees: {len(worktrees)}",
        f"Temp-dir threshold: {temp_days} days",
        "",
        "Prune output:",
    ]

    if prune_output:
        lines.extend(f"- {line}" for line in prune_output.splitlines())
    else:
        lines.append("- (no prune output)")

    if prune_errors:
        lines.append("")
        lines.append("Prune notes:")
        lines.extend(f"- {line}" for line in prune_errors.splitlines())

    lines.append("")
    lines.append(
        f"Temp-dir worktrees older than {temp_days} days: {len(old_temp_worktrees)}"
    )
    if old_temp_worktrees:
        for worktree in old_temp_worktrees:
            branch = worktree.branch or "<detached>"
            age = (
                f"{worktree.age_days}d"
                if worktree.age_days is not None
                else "unknown"
            )
            lines.append(f"- {worktree.path.as_posix()} | branch={branch} | age={age}")
    else:
        lines.append("- none")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run git worktree prune in dry-run mode by default and "
            "flag old temp worktrees."
        )
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root (default: auto-detect from script location)",
    )
    parser.add_argument(
        "--temp-days",
        type=int,
        default=14,
        help="Age threshold in days for temp-dir worktree warnings (default: 14)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Run git worktree prune without --dry-run",
    )
    args = parser.parse_args(argv)

    root = _repo_root_from(args.root)

    try:
        worktrees = list_worktrees(root, temp_days=args.temp_days)
        prune_output, prune_errors = run_prune(root, apply=args.apply)
    except (subprocess.CalledProcessError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    print(
        render_report(
            worktrees,
            prune_output=prune_output,
            prune_errors=prune_errors,
            apply=args.apply,
            temp_days=args.temp_days,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
