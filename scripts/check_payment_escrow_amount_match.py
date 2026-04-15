#!/usr/bin/env python3
"""Detect payments that exceed their available escrow amount."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CHECK_NAME = "payment_escrow_amount_match"


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


def _normalize_issue(issue: Any) -> str | None:
    if issue is None:
        return None
    return str(issue)


def _numeric_amount(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def load_history_events(history_dir: Path) -> list[HistoryEvent]:
    """Load history events sorted by timestamp, then file name and line."""
    events: list[HistoryEvent] = []
    if not history_dir.is_dir():
        return events

    for path in sorted(history_dir.glob("*.jsonl")):
        for line_number, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
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


def _detail(
    record: HistoryEvent,
    reason: str,
    *,
    amount: int | float | None = None,
    available_before: int | float | None = None,
) -> dict[str, Any]:
    event = record.event
    return {
        "issue": _normalize_issue(event.get("issue")),
        "agent": event.get("agent"),
        "amount": amount,
        "available_before": available_before,
        "timestamp": record.timestamp.isoformat().replace("+00:00", "Z") if record.timestamp else None,
        "file": record.path.name,
        "line": record.line_number,
        "reason": reason,
    }


def run_check(root: Path) -> dict[str, Any]:
    """Return a ledger-health-style report for payment/escrow mismatches."""
    history_dir = root / "ledger" / "history"
    history_files = sorted(history_dir.glob("*.jsonl")) if history_dir.is_dir() else []
    history_events = load_history_events(history_dir)

    available_by_issue: dict[str, int | float] = {}
    explicit_escrow_issues: set[str] = set()
    batch_issues: set[str] = set()
    violations: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    payment_events_scanned = 0
    explicit_escrow_events_scanned = 0
    skipped_legacy_batch_only_payments = 0
    skipped_malformed_payments = 0

    for record in history_events:
        event = record.event
        event_type = event.get("type")

        if event_type == "escrow_batch":
            issues = event.get("issues", [])
            if isinstance(issues, list):
                for raw_issue in issues:
                    issue = _normalize_issue(raw_issue)
                    if issue is not None:
                        batch_issues.add(issue)
            continue

        issue = _normalize_issue(event.get("issue"))
        amount = _numeric_amount(event.get("amount"))

        if event_type in {"escrow", "escrow_create"}:
            if issue is None or amount is None or amount < 0:
                continue
            explicit_escrow_events_scanned += 1
            explicit_escrow_issues.add(issue)
            available_by_issue[issue] = available_by_issue.get(issue, 0) + amount
            continue

        if event_type == "escrow_return":
            if issue is None or amount is None or amount < 0:
                continue
            available_by_issue[issue] = available_by_issue.get(issue, 0) - amount
            continue

        if event_type == "reversal":
            if issue is None or amount is None:
                continue
            available_by_issue[issue] = available_by_issue.get(issue, 0) - amount
            continue

        if event_type != "payment":
            continue

        payment_events_scanned += 1

        if issue is None or amount is None or amount <= 0:
            skipped_malformed_payments += 1
            warnings.append(_detail(record, "skipped_malformed_payment", amount=amount))
            continue

        if issue not in explicit_escrow_issues and issue in batch_issues:
            skipped_legacy_batch_only_payments += 1
            warnings.append(_detail(record, "skipped_legacy_batch_without_per_issue_amount", amount=amount))
            continue

        available_before = available_by_issue.get(issue, 0)
        if amount > available_before:
            violations.append(
                _detail(
                    record,
                    "payment_exceeds_available_escrow",
                    amount=amount,
                    available_before=available_before,
                )
            )

        available_by_issue[issue] = available_before - amount

    status = "FAIL" if violations else "PASS"
    detail = (
        f"Found {len(violations)} payment(s) that exceed available escrow."
        if violations
        else "No payments exceed available escrow."
    )

    return {
        "status": status,
        "checks": [
            {
                "name": CHECK_NAME,
                "status": status,
                "detail": detail,
                "violations": violations,
                "warnings": warnings,
            }
        ],
        "summary": {
            "history_files_scanned": len(history_files),
            "payment_events_scanned": payment_events_scanned,
            "explicit_escrow_events_scanned": explicit_escrow_events_scanned,
            "issues_with_explicit_escrow": len(explicit_escrow_issues),
            "violations": len(violations),
            "skipped_legacy_batch_only_payments": skipped_legacy_batch_only_payments,
            "skipped_malformed_payments": skipped_malformed_payments,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check that payments do not exceed available escrow")
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
