#!/usr/bin/env python3
"""Detect issues that accumulate more than one active escrow in history."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_INVALID_ESCAPE_RE = re.compile(r"\\(?![\"\\/bfnrtu])")
_TIMESTAMP_FIELDS = ("timestamp", "ts", "created_at", "event_at", "started_at", "at")
_OPEN_EVENT_TYPES = frozenset({"escrow_create"})
_CLOSE_EVENT_TYPES = frozenset({"accept", "escrow_return", "payment", "reject"})


@dataclass(frozen=True)
class HistoryEvent:
    path: Path
    line_number: int
    event_type: str | None
    issue: str | None
    timestamp: datetime | None


def _repo_root_from(root: str | None) -> Path:
    if root:
        return Path(root).resolve()
    return Path(__file__).resolve().parent.parent


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None

    raw = value.strip()
    if not raw:
        return None

    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _event_timestamp(event: dict[str, Any]) -> datetime | None:
    for key in _TIMESTAMP_FIELDS:
        parsed = _parse_timestamp(event.get(key))
        if parsed is not None:
            return parsed
    return None


def _event_type(event: dict[str, Any]) -> str | None:
    for key in ("type", "event", "op"):
        value = event.get(key)
        if isinstance(value, str):
            normalized = value.strip()
            if normalized:
                return normalized
    return None


def _normalize_issue(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        try:
            return str(int(normalized))
        except ValueError:
            return None
    return None


def _load_jsonl_line(raw_line: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(raw_line)
    except json.JSONDecodeError:
        repaired = _INVALID_ESCAPE_RE.sub(r"\\\\", raw_line)
        try:
            payload = json.loads(repaired)
        except json.JSONDecodeError:
            return None

    if not isinstance(payload, dict):
        return None
    return payload


def load_history_events(history_dir: Path) -> tuple[list[HistoryEvent], int]:
    events: list[HistoryEvent] = []
    malformed_lines = 0
    if not history_dir.is_dir():
        return events, malformed_lines

    for path in sorted(history_dir.glob("*.jsonl")):
        for line_number, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue

            payload = _load_jsonl_line(line)
            if payload is None:
                malformed_lines += 1
                continue

            events.append(
                HistoryEvent(
                    path=path,
                    line_number=line_number,
                    event_type=_event_type(payload),
                    issue=_normalize_issue(payload.get("issue")),
                    timestamp=_event_timestamp(payload),
                )
            )

    max_dt = datetime.max.replace(tzinfo=timezone.utc)
    events.sort(key=lambda item: (item.timestamp or max_dt, item.path.name, item.line_number))
    return events, malformed_lines


def _issue_display(issue: str) -> int | str:
    try:
        return int(issue)
    except ValueError:
        return issue


def _timestamp_display(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


def run_check(root: Path) -> dict[str, Any]:
    history_dir = root / "ledger" / "history"
    history_files = sorted(history_dir.glob("*.jsonl")) if history_dir.is_dir() else []
    events, malformed_lines = load_history_events(history_dir)

    open_counts: dict[str, int] = {}
    violations_by_issue: dict[str, dict[str, Any]] = {}
    escrow_creates_scanned = 0
    closing_events_scanned = 0

    for record in events:
        issue = record.issue
        event_type = record.event_type
        if issue is None or event_type is None:
            continue

        if event_type in _OPEN_EVENT_TYPES:
            escrow_creates_scanned += 1
            next_count = open_counts.get(issue, 0) + 1
            open_counts[issue] = next_count

            if next_count > 1 and issue not in violations_by_issue:
                violations_by_issue[issue] = {
                    "issue": _issue_display(issue),
                    "open_escrows": next_count,
                    "peak_open_escrows": next_count,
                    "file": record.path.name,
                    "line": record.line_number,
                    "timestamp": _timestamp_display(record.timestamp),
                    "event_type": event_type,
                    "reason": "multiple_active_escrows",
                }
            elif issue in violations_by_issue:
                violations_by_issue[issue]["peak_open_escrows"] = max(
                    violations_by_issue[issue]["peak_open_escrows"],
                    next_count,
                )

            continue

        if event_type not in _CLOSE_EVENT_TYPES:
            continue

        closing_events_scanned += 1
        current_count = open_counts.get(issue, 0)
        if current_count <= 1:
            open_counts.pop(issue, None)
        else:
            open_counts[issue] = current_count - 1

    violations = sorted(
        violations_by_issue.values(),
        key=lambda entry: (
            entry["issue"] if isinstance(entry["issue"], int) else str(entry["issue"]),
            entry["file"],
            entry["line"],
        ),
    )

    status = "FAIL" if violations else "PASS"
    summary = (
        f"Found {len(violations)} issue(s) with more than one active escrow."
        if violations
        else "No issue exceeded one active escrow."
    )

    return {
        "status": status,
        "summary": summary,
        "violations": violations,
        "checks": [
            {
                "name": "single_escrow_per_issue",
                "status": status,
                "detail": summary,
            }
        ],
        "stats": {
            "history_files_scanned": len(history_files),
            "history_events_scanned": len(events),
            "malformed_lines_skipped": malformed_lines,
            "escrow_creates_scanned": escrow_creates_scanned,
            "closing_events_scanned": closing_events_scanned,
            "issues_with_multiple_active_escrows": len(violations),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check that no issue ever has more than one active escrow in history"
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Path to repository root (default: auto-detect from script location)",
    )
    args = parser.parse_args(argv)

    report = run_check(_repo_root_from(args.root))
    print(json.dumps(report, indent=2))
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
