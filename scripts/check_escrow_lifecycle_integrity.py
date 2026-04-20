#!/usr/bin/env python3
"""Verify escrow lifecycle integrity in ledger/history/*.jsonl."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CHECK_NAME = "escrow_lifecycle_integrity"
TRACKED_CREATE_KINDS = {"escrow_create"}
CREATE_EQUIVALENT_KINDS = {"escrow", "escrow_create"}
CLOSE_KINDS = {"accept", "escrow_return", "payment"}


@dataclass(frozen=True)
class HistoryEvent:
    path: Path
    line_number: int
    event: dict[str, Any]
    kind: str | None
    issue: str | None
    amount: int | float | None
    timestamp: datetime | None


@dataclass
class OpenCreate:
    record: HistoryEvent
    tracked: bool


def _repo_root_from(root: str | None) -> Path:
    if root:
        return Path(root).resolve()
    return Path(__file__).resolve().parent.parent


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _event_timestamp(event: dict[str, Any]) -> datetime | None:
    for key in ("timestamp", "ts", "created_at", "event_at", "started_at"):
        parsed = _parse_timestamp(event.get(key))
        if parsed is not None:
            return parsed
    return None


def _event_kind(event: dict[str, Any]) -> str | None:
    for key in ("event", "op", "type"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _normalize_issue(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return str(int(stripped))
        except ValueError:
            return None
    return None


def _numeric_amount(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _issue_display(issue_key: str | None) -> int | str | None:
    if issue_key is None:
        return None
    try:
        return int(issue_key)
    except ValueError:
        return issue_key


def load_history_events(history_dir: Path) -> tuple[list[HistoryEvent], int]:
    """Load history events sorted by timestamp, then file name and line number."""
    events: list[HistoryEvent] = []
    malformed_lines = 0
    if not history_dir.is_dir():
        return events, malformed_lines

    for path in sorted(history_dir.glob("*.jsonl")):
        for line_number, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                malformed_lines += 1
                continue
            if not isinstance(payload, dict):
                continue
            events.append(
                HistoryEvent(
                    path=path,
                    line_number=line_number,
                    event=payload,
                    kind=_event_kind(payload),
                    issue=_normalize_issue(payload.get("issue")),
                    amount=_numeric_amount(payload.get("amount")),
                    timestamp=_event_timestamp(payload),
                )
            )

    max_dt = datetime.max.replace(tzinfo=timezone.utc)
    events.sort(key=lambda item: (item.timestamp or max_dt, item.path.name, item.line_number))
    return events, malformed_lines


def _report_entry(
    *,
    status: str,
    issue: str | None,
    reason: str | None,
    create_record: HistoryEvent | None = None,
    close_record: HistoryEvent | None = None,
) -> dict[str, Any]:
    entry = {
        "issue": _issue_display(issue),
        "status": status,
        "reason": reason,
        "create_kind": create_record.kind if create_record else None,
        "close_kind": close_record.kind if close_record else None,
        "create_amount": create_record.amount if create_record else None,
        "close_amount": close_record.amount if close_record else None,
        "create_file": create_record.path.name if create_record else None,
        "create_line": create_record.line_number if create_record else None,
        "close_file": close_record.path.name if close_record else None,
        "close_line": close_record.line_number if close_record else None,
    }
    return entry


def run_check(root: Path) -> dict[str, Any]:
    """Replay history and verify escrow-create lifecycle integrity."""
    history_dir = root / "ledger" / "history"
    history_files = sorted(history_dir.glob("*.jsonl")) if history_dir.is_dir() else []
    history_events, malformed_lines = load_history_events(history_dir)

    open_creates: dict[str, list[OpenCreate]] = {}
    issues_with_tracked_create_history: set[str] = set()
    reports: list[dict[str, Any]] = []
    escrow_create_events_scanned = 0
    close_events_scanned = 0

    for record in history_events:
        kind = record.kind

        if kind in CREATE_EQUIVALENT_KINDS:
            tracked = kind in TRACKED_CREATE_KINDS
            if tracked:
                escrow_create_events_scanned += 1
            if record.issue is None or record.amount is None:
                if tracked:
                    reports.append(
                        _report_entry(
                            status="FAIL",
                            issue=record.issue,
                            reason="invalid_escrow_create",
                            create_record=record,
                        )
                    )
                continue
            if tracked:
                issues_with_tracked_create_history.add(record.issue)
            open_creates.setdefault(record.issue, []).append(OpenCreate(record=record, tracked=tracked))
            continue

        if kind not in CLOSE_KINDS:
            continue

        close_events_scanned += 1
        if record.issue is None or record.amount is None:
            if kind != "payment":
                reports.append(
                    _report_entry(
                        status="FAIL",
                        issue=record.issue,
                        reason="invalid_close_event",
                        close_record=record,
                    )
                )
            continue

        pending = open_creates.get(record.issue, [])
        if not pending:
            if kind == "payment" and record.issue not in issues_with_tracked_create_history:
                continue
            reports.append(
                _report_entry(
                    status="FAIL",
                    issue=record.issue,
                    reason="close_without_prior_create",
                    close_record=record,
                )
            )
            continue

        matched_create = pending.pop(0)
        if not pending:
            open_creates.pop(record.issue, None)

        if not matched_create.tracked:
            continue

        reason = None
        status = "PASS"
        if matched_create.record.amount != record.amount:
            status = "FAIL"
            reason = "amount_mismatch"

        reports.append(
            _report_entry(
                status=status,
                issue=record.issue,
                reason=reason,
                create_record=matched_create.record,
                close_record=record,
            )
        )

    for issue, pending in sorted(open_creates.items(), key=lambda item: int(item[0]) if item[0].isdigit() else item[0]):
        for matched_create in pending:
            if not matched_create.tracked:
                continue
            reports.append(
                _report_entry(
                    status="FAIL",
                    issue=issue,
                    reason="no_close_event",
                    create_record=matched_create.record,
                )
            )

    reports.sort(
        key=lambda entry: (
            entry["issue"] if entry["issue"] is not None else -1,
            entry["create_file"] or entry["close_file"] or "",
            entry["create_line"] or entry["close_line"] or 0,
            entry["close_line"] or 0,
        )
    )

    failures = [entry for entry in reports if entry["status"] == "FAIL"]
    passes = [entry for entry in reports if entry["status"] == "PASS"]
    status = "FAIL" if failures else "PASS"
    detail = (
        f"Found {len(failures)} lifecycle violation(s)."
        if failures
        else "All escrow_create events have exactly one later matching close event."
    )

    return {
        "status": status,
        "checks": [
            {
                "name": CHECK_NAME,
                "status": status,
                "detail": detail,
                "issues": reports,
            }
        ],
        "summary": {
            "history_files_scanned": len(history_files),
            "malformed_lines_skipped": malformed_lines,
            "escrow_create_events_scanned": escrow_create_events_scanned,
            "close_events_scanned": close_events_scanned,
            "passes": len(passes),
            "failures": len(failures),
        },
        "issues": reports,
    }


def _print_human(report: dict[str, Any]) -> None:
    summary = report["summary"]
    print(f"{report['status']}: {CHECK_NAME}")
    print(
        "  "
        f"escrow_create_events_scanned={summary['escrow_create_events_scanned']} "
        f"close_events_scanned={summary['close_events_scanned']} "
        f"passes={summary['passes']} "
        f"failures={summary['failures']}"
    )
    for entry in report["issues"]:
        issue = entry["issue"]
        if issue is None:
            issue_text = "<missing>"
        else:
            issue_text = f"#{issue}"
        if entry["status"] == "PASS":
            print(
                f"  PASS issue {issue_text}: "
                f"{entry['create_kind']} -> {entry['close_kind']} "
                f"amount={entry['create_amount']}"
            )
            continue
        print(
            f"  FAIL issue {issue_text}: reason={entry['reason']} "
            f"create_kind={entry['create_kind']} close_kind={entry['close_kind']} "
            f"create_amount={entry['create_amount']} close_amount={entry['close_amount']}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check that escrow_create events have exactly one matching close event"
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Path to repository root (default: auto-detect from script location)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Print JSON instead of the human-readable report",
    )
    args = parser.parse_args(argv)

    report = run_check(_repo_root_from(args.root))
    if args.json_output:
        print(json.dumps(report, indent=2))
    else:
        _print_human(report)
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
