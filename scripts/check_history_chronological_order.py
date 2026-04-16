#!/usr/bin/env python3
"""Verify ledger history timestamps are chronologically ordered.

This checker enforces two rules:
1. Settlement chronology events inside each ``ledger/history/*.jsonl`` file
   must appear in non-decreasing timestamp order.
2. Each payment must have a same-issue prior escrow event whose timestamp is
   not later than the payment. Both ``escrow_create`` and legacy ``escrow``
   entries count as the escrow side of that relationship.

Legacy history contains malformed string escapes, issues with no recorded
escrow event, and backfilled administrative events appended after newer
entries. The loader repairs the known escape issue, within-file ordering is
limited to the settlement event types whose chronology is expected to be
strict, and cross-file enforcement accepts both escrow spellings while only
judging issues that have an escrow record to compare against.

Usage:
    python scripts/check_history_chronological_order.py [--root PATH]
"""

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
_TIMESTAMP_FIELDS = ("timestamp", "created_at", "started_at", "event_at", "at")
_ORDERED_EVENT_TYPES = frozenset({"payment", "escrow_create"})
_ESCROW_EVENT_TYPES = frozenset({"escrow", "escrow_create"})


@dataclass(frozen=True)
class HistoryRecord:
    path: Path
    line_number: int
    event: dict[str, Any]
    timestamp: datetime
    timestamp_field: str


def _repo_root_from(root: str | None) -> Path:
    if root:
        return Path(root).resolve()
    return Path(__file__).resolve().parent.parent


def _parse_iso_utc(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp is missing or not a string")
    raw = value.strip()
    if not raw:
        raise ValueError("timestamp is empty")
    normalized = raw.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _load_jsonl_line(raw: str) -> dict[str, Any]:
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        repaired = _INVALID_ESCAPE_RE.sub(r"\\\\", raw)
        loaded = json.loads(repaired)

    if not isinstance(loaded, dict):
        raise ValueError(f"expected JSON object, got {type(loaded).__name__}")
    return loaded


def _extract_timestamp(event: dict[str, Any]) -> tuple[datetime, str]:
    for field in _TIMESTAMP_FIELDS:
        value = event.get(field)
        if value in (None, ""):
            continue
        return _parse_iso_utc(value), field
    raise ValueError("missing timestamp field")


def load_history_records(history_dir: Path) -> tuple[list[HistoryRecord], list[dict[str, Any]]]:
    """Load all history events plus fatal parse/shape/timestamp errors."""
    records: list[HistoryRecord] = []
    violations: list[dict[str, Any]] = []

    if not history_dir.is_dir():
        return records, violations

    for path in sorted(history_dir.glob("*.jsonl")):
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line_number, raw in enumerate(handle, start=1):
                stripped = raw.strip()
                if not stripped:
                    continue
                try:
                    event = _load_jsonl_line(stripped)
                    timestamp, timestamp_field = _extract_timestamp(event)
                except (json.JSONDecodeError, ValueError) as exc:
                    violations.append(
                        {
                            "check": "history_parseability",
                            "status": "FAIL",
                            "file": path.name,
                            "line": line_number,
                            "detail": str(exc),
                        }
                    )
                    continue

                records.append(
                    HistoryRecord(
                        path=path,
                        line_number=line_number,
                        event=event,
                        timestamp=timestamp,
                        timestamp_field=timestamp_field,
                    )
                )

    return records, violations


def _format_timestamp(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _issue_key(event: dict[str, Any]) -> str | None:
    issue = event.get("issue")
    if issue is None:
        return None
    return str(issue)


def check_within_file_order(records: list[HistoryRecord]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Return within-file chronological violations and a compact summary."""
    violations: list[dict[str, Any]] = []
    files_checked = 0
    events_checked = 0

    records_by_file: dict[str, list[HistoryRecord]] = {}
    for record in records:
        if record.event.get("type") not in _ORDERED_EVENT_TYPES:
            continue
        records_by_file.setdefault(record.path.name, []).append(record)

    for filename in sorted(records_by_file):
        file_records = sorted(records_by_file[filename], key=lambda item: item.line_number)
        files_checked += 1
        events_checked += len(file_records)
        previous: HistoryRecord | None = None
        for record in file_records:
            if previous is not None and record.timestamp < previous.timestamp:
                violations.append(
                    {
                        "check": "within_file_non_decreasing_timestamps",
                        "status": "FAIL",
                        "file": filename,
                        "line": record.line_number,
                        "timestamp": _format_timestamp(record.timestamp),
                        "previous_line": previous.line_number,
                        "previous_timestamp": _format_timestamp(previous.timestamp),
                        "detail": (
                            f"timestamp moved backwards from line {previous.line_number} "
                            f"to line {record.line_number}"
                        ),
                    }
                )
            previous = record

    return violations, {"files_checked": files_checked, "events_checked": events_checked}


def check_escrow_create_before_payment(
    records: list[HistoryRecord],
) -> tuple[list[dict[str, Any]], dict[str, int | str | None]]:
    """Return payment-vs-escrow_create violations and summary data."""
    earliest_escrow_by_issue: dict[str, HistoryRecord] = {}
    payments_total = 0
    payments_checked = 0
    payments_skipped_without_escrow = 0
    violations: list[dict[str, Any]] = []

    for record in records:
        if record.event.get("type") not in _ESCROW_EVENT_TYPES:
            continue
        issue_key = _issue_key(record.event)
        if issue_key is None:
            continue
        existing = earliest_escrow_by_issue.get(issue_key)
        if existing is None or record.timestamp < existing.timestamp:
            earliest_escrow_by_issue[issue_key] = record

    for record in sorted(records, key=lambda item: (item.timestamp, item.path.name, item.line_number)):
        if record.event.get("type") != "payment":
            continue

        payments_total += 1
        issue_key = _issue_key(record.event)
        if issue_key is None:
            payments_checked += 1
            violations.append(
                {
                    "check": "escrow_create_precedes_payment",
                    "status": "FAIL",
                    "file": record.path.name,
                    "line": record.line_number,
                    "issue": None,
                    "timestamp": _format_timestamp(record.timestamp),
                    "reason": "payment_missing_issue",
                }
            )
            continue

        escrow_record = earliest_escrow_by_issue.get(issue_key)
        if escrow_record is None:
            payments_skipped_without_escrow += 1
            continue

        payments_checked += 1
        if escrow_record.timestamp > record.timestamp:
            violations.append(
                {
                    "check": "escrow_create_precedes_payment",
                    "status": "FAIL",
                    "file": record.path.name,
                    "line": record.line_number,
                    "issue": record.event.get("issue"),
                    "timestamp": _format_timestamp(record.timestamp),
                    "escrow_file": escrow_record.path.name,
                    "escrow_line": escrow_record.line_number,
                    "escrow_timestamp": _format_timestamp(escrow_record.timestamp),
                    "escrow_type": escrow_record.event.get("type"),
                    "reason": "escrow_after_payment",
                }
            )

    return violations, {
        "payments_total": payments_total,
        "payments_checked": payments_checked,
        "payments_skipped_without_escrow": payments_skipped_without_escrow,
    }


def run_check(root: Path) -> dict[str, Any]:
    """Return the chronological integrity report for ledger/history."""
    history_dir = root / "ledger" / "history"
    if not history_dir.is_dir():
        return {
            "status": "FAIL",
            "checks": [
                {
                    "name": "history_directory",
                    "status": "FAIL",
                    "detail": f"history directory not found: {history_dir}",
                }
            ],
            "violations": [],
            "summary": f"FAIL: history directory not found: {history_dir}",
        }

    records, load_violations = load_history_records(history_dir)
    file_order_violations, order_summary = check_within_file_order(records)
    escrow_payment_violations, cross_summary = check_escrow_create_before_payment(records)

    violations = load_violations + file_order_violations + escrow_payment_violations
    status = "FAIL" if violations else "PASS"

    checks = [
        {
            "name": "history_parseability",
            "status": "FAIL" if load_violations else "PASS",
            "violations": len(load_violations),
        },
        {
            "name": "within_file_non_decreasing_timestamps",
            "status": "FAIL" if file_order_violations else "PASS",
            **order_summary,
            "violations": len(file_order_violations),
        },
        {
            "name": "escrow_create_precedes_payment",
            "status": "FAIL" if escrow_payment_violations else "PASS",
            **cross_summary,
            "violations": len(escrow_payment_violations),
        },
    ]

    if violations:
        summary = (
            f"FAIL: {len(violations)} violation(s) across {order_summary['files_checked']} "
            f"history file(s)."
        )
    else:
        summary = (
            f"PASS: {order_summary['events_checked']} event(s) across "
            f"{order_summary['files_checked']} history file(s) are in non-decreasing "
            "timestamp order, and all checked payments have a same-issue escrow "
            "event at or before payment time."
        )

    return {
        "status": status,
        "checks": checks,
        "violations": violations,
        "summary": summary,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check ledger history timestamp ordering and escrow_create precedence"
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
