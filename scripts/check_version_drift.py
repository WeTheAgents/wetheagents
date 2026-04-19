#!/usr/bin/env python3
"""Detect suspicious version drift in versioned ledger JSON files.

For every top-level ``ledger/*.json`` file that currently contains a top-level
``version`` field, this checker compares the current snapshot against the
immediately previous commit for that file and verifies that:

1. Versions increase monotonically once versioning begins.
2. A version is never reused and never jumps by more than 1 between snapshots.
3. The current ``ledger/balances.json:last_updated`` is not older than the
   second-most-recent commit timestamp for that file.

If the previous snapshot predates the introduction of a ``version`` field, the
current snapshot is treated as that file's baseline versioned state.

Output: JSON with keys ``status``, ``version_drift``, ``timestamp_drift``,
``files_checked``, and ``summary``.
Exit codes: 0 on PASS, 1 on FAIL.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any


BALANCES_PATH = "ledger/balances.json"


def _repo_root(root: str | None = None) -> Path:
    if root:
        return Path(root).resolve()
    return Path(__file__).resolve().parent.parent


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _format_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _git_error(exc: subprocess.CalledProcessError) -> str:
    return (exc.stderr or exc.stdout or str(exc)).strip()


def _load_worktree_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8-sig") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path.as_posix()} must contain a top-level JSON object")
    return data


@lru_cache(maxsize=None)
def _git_log(root: str, rel_path: str) -> tuple[tuple[str, int], ...]:
    try:
        result = subprocess.run(
            ["git", "log", "--reverse", "--format=%H%x00%ct", "--", rel_path],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"git is not available: {exc}") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"git log failed for {rel_path}: {_git_error(exc)}") from exc

    entries: list[tuple[str, int]] = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        commit, _, raw_ts = line.partition("\0")
        if not commit or not raw_ts:
            continue
        entries.append((commit, int(raw_ts)))
    return tuple(entries)


@lru_cache(maxsize=None)
def _git_show_json(root: str, commit: str, rel_path: str) -> dict[str, Any]:
    spec = f"{commit}:{rel_path}"
    try:
        result = subprocess.run(
            ["git", "show", spec],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"git is not available: {exc}") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"git show failed for {spec}: {_git_error(exc)}") from exc

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{rel_path}@{commit[:8]} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{rel_path}@{commit[:8]} must contain a top-level JSON object")
    return data


def list_versioned_ledger_files(root: Path) -> list[str]:
    ledger_dir = root / "ledger"
    if not ledger_dir.is_dir():
        raise FileNotFoundError(f"ledger directory not found at {ledger_dir}")

    versioned: list[str] = []
    for path in sorted(ledger_dir.glob("*.json")):
        data = _load_worktree_json(path)
        if "version" in data:
            versioned.append(path.relative_to(root).as_posix())
    return versioned


def inspect_version_history(root: Path, rel_path: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    history = _git_log(str(root), rel_path)
    current = _load_worktree_json(root / rel_path)
    current_version = current.get("version")
    report = {
        "path": rel_path,
        "commit_count": len(history),
        "current_version": current_version if _is_int(current_version) else None,
        "has_previous_commit": len(history) >= 2,
        "previous_version": None,
    }
    issues: list[dict[str, Any]] = []
    current_commit = history[-1][0] if history else None

    if not _is_int(current_version):
        issues.append(
            {
                "file": rel_path,
                "commit": current_commit,
                "previous_commit": history[-2][0] if len(history) >= 2 else None,
                "previous_version": None,
                "current_version": current_version,
                "delta": None,
                "reason": "current version is missing or non-integer",
            }
        )
        return report, issues

    if len(history) < 2:
        return report, issues

    previous_commit = history[-2][0]
    previous_data = _git_show_json(str(root), previous_commit, rel_path)
    previous_version = previous_data.get("version")
    report["previous_version"] = previous_version if _is_int(previous_version) else None

    if not _is_int(previous_version):
        return report, issues

    delta = int(current_version) - int(previous_version)
    if delta == 0:
        issues.append(
            {
                "file": rel_path,
                "commit": current_commit,
                "previous_commit": previous_commit,
                "previous_version": previous_version,
                "current_version": current_version,
                "delta": delta,
                "reason": "version reused across consecutive snapshots",
            }
        )
    elif delta < 0:
        issues.append(
            {
                "file": rel_path,
                "commit": current_commit,
                "previous_commit": previous_commit,
                "previous_version": previous_version,
                "current_version": current_version,
                "delta": delta,
                "reason": "version decreased instead of increasing monotonically",
            }
        )
    elif delta > 1:
        issues.append(
            {
                "file": rel_path,
                "commit": current_commit,
                "previous_commit": previous_commit,
                "previous_version": previous_version,
                "current_version": current_version,
                "delta": delta,
                "reason": "version jump exceeded 1",
            }
        )

    return report, issues


def inspect_balances_timestamps(root: Path) -> list[dict[str, Any]]:
    balances_path = root / BALANCES_PATH
    if not balances_path.exists():
        return []

    history = _git_log(str(root), BALANCES_PATH)
    if len(history) < 2:
        return []

    current = _load_worktree_json(balances_path)
    last_updated_raw = current.get("last_updated")
    last_updated = _parse_timestamp(last_updated_raw)
    current_commit = history[-1][0]
    previous_commit = history[-2][0]
    previous_commit_time = datetime.fromtimestamp(history[-2][1], tz=timezone.utc)
    issues: list[dict[str, Any]] = []

    if last_updated is None:
        issues.append(
            {
                "file": BALANCES_PATH,
                "commit": current_commit,
                "previous_commit": previous_commit,
                "previous_commit_timestamp": _format_utc(previous_commit_time),
                "last_updated": last_updated_raw,
                "reason": "missing or invalid last_updated after first commit",
            }
        )
        return issues

    if last_updated < previous_commit_time:
        issues.append(
            {
                "file": BALANCES_PATH,
                "commit": current_commit,
                "previous_commit": previous_commit,
                "previous_commit_timestamp": _format_utc(previous_commit_time),
                "last_updated": _format_utc(last_updated),
                "reason": "last_updated is older than the second-most-recent commit timestamp",
            }
        )

    return issues


def run(root: Path) -> tuple[dict[str, Any], bool]:
    try:
        files = list_versioned_ledger_files(root)
        files_checked: list[dict[str, Any]] = []
        version_drift: list[dict[str, Any]] = []

        for rel_path in files:
            file_report, issues = inspect_version_history(root, rel_path)
            files_checked.append(file_report)
            version_drift.extend(issues)

        timestamp_drift = inspect_balances_timestamps(root)
    except (FileNotFoundError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        payload = {
            "status": "FAIL",
            "version_drift": [],
            "timestamp_drift": [],
            "files_checked": [],
            "summary": str(exc),
            "error": str(exc),
        }
        return payload, False

    passed = not version_drift and not timestamp_drift
    payload = {
        "status": "PASS" if passed else "FAIL",
        "version_drift": version_drift,
        "timestamp_drift": timestamp_drift,
        "files_checked": files_checked,
        "summary": (
            f"Checked {len(files_checked)} versioned ledger file(s); "
            f"{len(version_drift)} version issue(s), "
            f"{len(timestamp_drift)} timestamp issue(s)."
        ),
    }
    return payload, passed


def run_check(root: Path) -> dict[str, Any]:
    payload, _ = run(root)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check ledger JSON version drift against the previous file commit."
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root (default: auto-detected from script location)",
    )
    args = parser.parse_args(argv)

    payload, passed = run(_repo_root(args.root))
    print(json.dumps(payload, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
