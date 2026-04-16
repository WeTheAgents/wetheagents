#!/usr/bin/env python3
"""Detect claimed tasks that have gone stale with no post-claim activity."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from io_helpers import load_json  # noqa: E402

STALE_DAYS = 7


def parse_iso_utc(value: str) -> datetime:
    """Parse an ISO timestamp into a UTC-aware datetime."""
    raw = value.strip()
    if not raw:
        raise ValueError("empty timestamp")
    normalized = raw.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _repo_root_from(root: str | None) -> Path:
    if root:
        return Path(root).resolve()
    return Path(__file__).resolve().parent.parent


def _iter_history(root: Path) -> list[dict[str, Any]]:
    """Load valid JSON object events from ledger/history/*.jsonl."""
    history_dir = root / "ledger" / "history"
    if not history_dir.exists():
        return []

    records: list[dict[str, Any]] = []
    for path in sorted(history_dir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            payload = line.strip()
            if not payload:
                continue
            try:
                event = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                records.append(event)
    return records


def _event_time(event: dict[str, Any]) -> datetime | None:
    """Return event time from the best available history timestamp field."""
    for field in ("event_at", "created_at", "timestamp"):
        value = event.get(field)
        if not isinstance(value, str):
            continue
        try:
            return parse_iso_utc(value)
        except ValueError:
            continue
    return None


def _latest_activity_by_issue(history: list[dict[str, Any]]) -> dict[int, datetime]:
    """Return the latest timestamp seen for each issue in history."""
    latest: dict[int, datetime] = {}
    for event in history:
        try:
            issue = int(event.get("issue"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        event_time = _event_time(event)
        if event_time is None:
            continue
        previous = latest.get(issue)
        if previous is None or event_time > previous:
            latest[issue] = event_time
    return latest


def _task_sort_key(item: tuple[str, Any]) -> tuple[int, str]:
    """Sort numeric issue keys first while tolerating malformed keys."""
    issue_str = item[0]
    try:
        return (0, f"{int(issue_str):012d}")
    except (TypeError, ValueError):
        return (1, str(issue_str))


def find_stale_claims(
    task_index: dict[str, Any],
    history: list[dict[str, Any]],
    *,
    now: datetime | None = None,
    stale_after: timedelta = timedelta(days=STALE_DAYS),
) -> list[dict[str, Any]]:
    """Return claimed tasks older than the threshold with no later activity."""
    if now is None:
        now = datetime.now(timezone.utc)

    latest_activity = _latest_activity_by_issue(history)
    stale_claims: list[dict[str, Any]] = []

    tasks = task_index.get("tasks", {})
    if not isinstance(tasks, dict):
        return stale_claims

    for issue_str, task in sorted(tasks.items(), key=_task_sort_key):
        if not isinstance(task, dict) or task.get("status") != "claimed":
            continue

        claimed_at_raw = task.get("claimed_at")
        if not isinstance(claimed_at_raw, str) or not claimed_at_raw.strip():
            continue

        try:
            issue = int(issue_str)
            claimed_at = parse_iso_utc(claimed_at_raw)
        except (TypeError, ValueError):
            continue

        if now - claimed_at <= stale_after:
            continue

        if latest_activity.get(issue) and latest_activity[issue] > claimed_at:
            continue

        stale_claims.append(
            {
                "issue": issue,
                "agent": str(task.get("agent", "") or "").strip() or "<unknown>",
                "claimed_at": claimed_at_raw,
                "age_days": round((now - claimed_at).total_seconds() / 86400.0, 2),
            }
        )

    return stale_claims


def format_report(stale_claims: list[dict[str, Any]]) -> str:
    """Return a human-readable stale-claim report."""
    if not stale_claims:
        return "OK: No stale claimed tasks found."

    lines = ["FAIL: Stale claimed task(s) with no post-claim activity"]
    for claim in stale_claims:
        lines.append(
            f"  #{claim['issue']} claimed by {claim['agent']} at "
            f"{claim['claimed_at']} ({claim['age_days']} days old)"
        )
    lines.append("  Why it matters: stalled claims block available task slots.")
    lines.append("  Remediation: unclaim, reject, or confirm the worker is still active.")
    return "\n".join(lines)


def run_check(
    root: Path,
    *,
    now: datetime | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Load ledger data and return (stale_claims, has_stale_claims)."""
    task_index = load_json(
        root / "ledger" / "task_index.json",
        default={"tasks": {}},
        encoding="utf-8-sig",
    )
    history = _iter_history(root)
    stale_claims = find_stale_claims(task_index, history, now=now)
    return stale_claims, bool(stale_claims)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Detect claimed tasks older than 7 days with no post-claim activity"
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root (default: auto-detect from script location)",
    )
    parser.add_argument(
        "--now",
        default=None,
        help="Override current UTC time in ISO format (for tests)",
    )
    args = parser.parse_args(argv)

    try:
        now = parse_iso_utc(args.now) if args.now else None
    except ValueError as exc:
        print(f"Error: invalid --now: {exc}", file=sys.stderr)
        return 2

    root = _repo_root_from(args.root)
    stale_claims, has_stale_claims = run_check(root, now=now)
    print(format_report(stale_claims))
    return 1 if has_stale_claims else 0


if __name__ == "__main__":
    sys.exit(main())
