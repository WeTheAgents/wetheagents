#!/usr/bin/env python3
"""Ensure payment events have a prior escrow event for the same issue.

This checker scans ledger/history/*.jsonl, orders events by timestamp, and
verifies that each payment is preceded by an escrow for the same issue.

Legacy exceptions:
- payments without idem_key are warned, not failed, when no prior escrow exists
- payments that predate the first escrow event in history are warned, not failed
- payments with no parseable timestamp are warned, not failed

Usage:
    python scripts/check_payment_has_prior_escrow.py [--root PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class HistoryEvent:
    path: Path
    line_number: int
    event: dict[str, Any]
    timestamp: datetime | None


def _repo_root_from(root: str | None) -> Path:
    if root:
        return Path(root).resolve()
    return Path(__file__).resolve().parent.parent


def _parse_timestamp(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _event_timestamp(event: dict[str, Any]) -> datetime | None:
    for key in ("timestamp", "event_at", "started_at"):
        parsed = _parse_timestamp(event.get(key))
        if parsed is not None:
            return parsed
    return None


def load_history_events(history_dir: Path) -> list[HistoryEvent]:
    """Load history events and sort them by timestamp, then file/line."""
    events: list[HistoryEvent] = []
    if not history_dir.is_dir():
        return events

    for path in sorted(history_dir.glob("*.jsonl")):
        for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            events.append(
                HistoryEvent(
                    path=path,
                    line_number=line_number,
                    event=event,
                    timestamp=_event_timestamp(event),
                )
            )

    max_dt = datetime.max.replace(tzinfo=timezone.utc)
    events.sort(key=lambda item: (item.timestamp or max_dt, item.path.name, item.line_number))
    return events


def _detail(record: HistoryEvent, reason: str) -> dict[str, Any]:
    event = record.event
    return {
        "issue": event.get("issue"),
        "agent": event.get("agent"),
        "timestamp": record.timestamp.isoformat().replace("+00:00", "Z") if record.timestamp else None,
        "file": record.path.name,
        "line": record.line_number,
        "reason": reason,
    }


def _mechanic_for(event: dict[str, Any]) -> str | None:
    mechanic = event.get("mechanic") or event.get("subtype") or event.get("reward_type")
    if not mechanic or not isinstance(mechanic, str):
        return None
    if mechanic == "ranking":
        return "best_x"
    return mechanic


def _iter_escrow_issues(event: dict[str, Any]) -> list[str]:
    event_type = event.get("type")
    if event_type in {"escrow", "escrow_create"}:
        issue = event.get("issue")
        return [str(issue)] if issue is not None else []
    if event_type == "escrow_batch":
        issues = event.get("issues", [])
        if isinstance(issues, list):
            return [str(issue) for issue in issues]
    return []


def run_check(root: Path) -> dict[str, Any]:
    """Return the payment-prior-escrow report."""
    history_events = load_history_events(root / "ledger" / "history")
    first_escrow_ts = min(
        (record.timestamp for record in history_events if _iter_escrow_issues(record.event) and record.timestamp),
        default=None,
    )
    first_escrow_ts_by_mechanic: dict[str, datetime] = {}
    for record in history_events:
        if not _iter_escrow_issues(record.event) or record.timestamp is None:
            continue
        mechanic = _mechanic_for(record.event)
        if mechanic is None:
            continue
        first_escrow_ts_by_mechanic.setdefault(mechanic, record.timestamp)

    prior_escrows: set[str] = set()
    violations: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    checked = 0

    for record in history_events:
        event = record.event
        event_type = event.get("type")
        issue = event.get("issue")

        escrow_issues = _iter_escrow_issues(event)
        if escrow_issues:
            prior_escrows.update(escrow_issues)
            continue

        if event_type != "payment":
            continue

        checked += 1
        issue_key = str(issue) if issue is not None else ""
        if issue_key in prior_escrows:
            continue

        if record.timestamp is None:
            warnings.append(_detail(record, "payment_missing_timestamp_no_prior_escrow"))
            continue

        if first_escrow_ts is None or record.timestamp < first_escrow_ts:
            warnings.append(_detail(record, "payment_predates_first_escrow_event"))
            continue

        mechanic = _mechanic_for(event)
        mechanic_first_escrow_ts = (
            first_escrow_ts_by_mechanic.get(mechanic) if mechanic is not None else None
        )
        if mechanic_first_escrow_ts is not None and record.timestamp < mechanic_first_escrow_ts:
            warnings.append(_detail(record, "payment_predates_first_escrow_for_mechanic"))
            continue

        if not event.get("idem_key"):
            warnings.append(_detail(record, "keyless_payment_without_prior_escrow"))
            continue

        violations.append(_detail(record, "payment_without_prior_escrow"))

    return {
        "status": "FAIL" if violations else "PASS",
        "checked": checked,
        "violations": violations,
        "warnings": warnings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check that each payment has a prior escrow event for the same issue"
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
