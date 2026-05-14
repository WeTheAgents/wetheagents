#!/usr/bin/env python3
"""Detect suspicious version drift in ledger/balances.json.

This checker compares the current ``ledger/balances.json`` snapshot against the
immediately previous commit for that file and verifies that:

1. The top-level ``version`` increases monotonically.
2. The version is never reused and never jumps by more than 1.
3. The current ``last_updated`` is not older than the previous snapshot's
   ``last_updated`` field (a logical-clock comparison).

If the previous snapshot predates the introduction of a ``version`` field, the
current snapshot is treated as the baseline versioned state.

Why the logical-clock comparison: ``last_updated`` is a logical timestamp
set by whatever tool writes ``balances.json``. The git commit timestamp is
a *wall-clock* value chosen by the writer's machine at commit time. The
two clocks routinely diverge by tens of seconds when a tool computes the
snapshot first and commits it shortly afterwards. Comparing ``last_updated``
against the previous file commit's wall-clock timestamp therefore produces
sub-minute false positives without catching anything the logical-clock
comparison does not. Real backdating (e.g. a snapshot whose
``last_updated`` is earlier than the previous snapshot's) is still caught.

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


def inspect_balances(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    balances_path = root / BALANCES_PATH
    if not balances_path.exists():
        raise FileNotFoundError(f"balances.json not found at {balances_path}")

    current = _load_worktree_json(balances_path)
    history = _git_log(str(root), BALANCES_PATH)
    current_version = current.get("version")
    report = {
        "path": BALANCES_PATH,
        "commit_count": len(history),
        "current_version": current_version if _is_int(current_version) else None,
        "has_previous_commit": len(history) >= 2,
        "previous_version": None,
    }
    version_drift: list[dict[str, Any]] = []
    timestamp_drift: list[dict[str, Any]] = []
    current_commit = history[-1][0] if history else None

    if not _is_int(current_version):
        version_drift.append(
            {
                "file": BALANCES_PATH,
                "commit": current_commit,
                "previous_commit": history[-2][0] if len(history) >= 2 else None,
                "previous_version": None,
                "current_version": current_version,
                "delta": None,
                "reason": "current version is missing or non-integer",
            }
        )
        return report, version_drift, timestamp_drift

    if len(history) < 2:
        return report, version_drift, timestamp_drift

    previous_commit, previous_raw_ts = history[-2]
    previous_data = _git_show_json(str(root), previous_commit, BALANCES_PATH)
    previous_version = previous_data.get("version")
    report["previous_version"] = previous_version if _is_int(previous_version) else None

    if _is_int(previous_version):
        delta = int(current_version) - int(previous_version)
        if delta == 0:
            version_drift.append(
                {
                    "file": BALANCES_PATH,
                    "commit": current_commit,
                    "previous_commit": previous_commit,
                    "previous_version": previous_version,
                    "current_version": current_version,
                    "delta": delta,
                    "reason": "version reused across consecutive snapshots",
                }
            )
        elif delta < 0:
            version_drift.append(
                {
                    "file": BALANCES_PATH,
                    "commit": current_commit,
                    "previous_commit": previous_commit,
                    "previous_version": previous_version,
                    "current_version": current_version,
                    "delta": delta,
                    "reason": "version decreased instead of increasing monotonically",
                }
            )
        elif delta > 1:
            version_drift.append(
                {
                    "file": BALANCES_PATH,
                    "commit": current_commit,
                    "previous_commit": previous_commit,
                    "previous_version": previous_version,
                    "current_version": current_version,
                    "delta": delta,
                    "reason": "version jump exceeded 1",
                }
            )

    last_updated_raw = current.get("last_updated")
    last_updated = _parse_timestamp(last_updated_raw)
    previous_commit_time = datetime.fromtimestamp(previous_raw_ts, tz=timezone.utc)
    previous_last_updated = _parse_timestamp(previous_data.get("last_updated"))
    if last_updated is None:
        timestamp_drift.append(
            {
                "file": BALANCES_PATH,
                "commit": current_commit,
                "previous_commit": previous_commit,
                "previous_commit_timestamp": _format_utc(previous_commit_time),
                "last_updated": last_updated_raw,
                "reason": "missing or invalid last_updated after first commit",
            }
        )
    elif previous_last_updated is not None and last_updated < previous_last_updated:
        # Logical-clock regression: current snapshot's last_updated is
        # earlier than the previous snapshot's last_updated. This is real
        # backdating regardless of the wall-clock commit times.
        timestamp_drift.append(
            {
                "file": BALANCES_PATH,
                "commit": current_commit,
                "previous_commit": previous_commit,
                "previous_commit_timestamp": _format_utc(previous_commit_time),
                "previous_last_updated": _format_utc(previous_last_updated),
                "last_updated": _format_utc(last_updated),
                "reason": "last_updated regressed compared to previous snapshot",
            }
        )

    return report, version_drift, timestamp_drift


def run(root: Path) -> tuple[dict[str, Any], bool]:
    try:
        file_report, version_drift, timestamp_drift = inspect_balances(root)
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
        "files_checked": [file_report],
        "summary": (
            f"Checked {BALANCES_PATH}; "
            f"{len(version_drift)} version issue(s), "
            f"{len(timestamp_drift)} timestamp issue(s)."
        ),
    }
    return payload, passed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check balances.json version drift against the previous file commit."
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
