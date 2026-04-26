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
                print(f"WARNING: malformed JSON at {path.name}:{line_number}", file=sys.stderr)
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

    # ── Load active escrows from escrows.json ─────────────────────────────────
    active_escrows: set[str] = set()
    escrows_file = root / "ledger" / "escrows.json"
    if escrows_file.exists():
        try:
            escrows_data = json.loads(escrows_file.read_text(encoding="utf-8"))
            for key in escrows_data.get("active", {}):
                normalized = _normalize_issue(key)
                if normalized:
                    active_escrows.add(normalized)
        except (json.JSONDecodeError, OSError):
            pass

    # ── Original escrow_create tracking ──────────────────────────────────────
    open_creates: dict[str, list[OpenCreate]] = {}
    issues_with_tracked_create_history: set[str] = set()
    issues_with_any_create: set[str] = set()
    reports: list[dict[str, Any]] = []
    escrow_create_events_scanned = 0
    close_events_scanned = 0

    # ── Legacy escrow tracking (for redteam summary fields) ───────────────────
    legacy_escrow_counts: dict[str, int] = {}      # issue → count of "escrow" events
    legacy_resolution_counts: dict[str, int] = {}  # issue → count of resolution events
    trajectory_mint_issues: set[str] = set()       # issues with trajectory_mint

    for record in history_events:
        kind = record.kind

        # ── New legacy tracking (runs for all relevant event types) ───────────
        if kind == "escrow":
            if record.issue is not None:
                legacy_escrow_counts[record.issue] = legacy_escrow_counts.get(record.issue, 0) + 1
        elif kind in ("escrow_return", "payment", "accept"):
            if record.issue is not None:
                legacy_resolution_counts[record.issue] = legacy_resolution_counts.get(record.issue, 0) + 1
        elif kind == "escrow_return_bulk":
            issues_list = record.event.get("issues", [])
            if isinstance(issues_list, list):
                for iss in issues_list:
                    normalized = _normalize_issue(iss)
                    if normalized:
                        legacy_resolution_counts[normalized] = legacy_resolution_counts.get(normalized, 0) + 1
        elif kind == "trajectory_mint":
            if record.issue is not None:
                trajectory_mint_issues.add(record.issue)

        # ── Original escrow_create tracking ───────────────────────────────────
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
            issues_with_any_create.add(record.issue)
            open_creates.setdefault(record.issue, []).append(OpenCreate(record=record, tracked=tracked))
            continue

        if kind not in CLOSE_KINDS:
            continue

        close_events_scanned += 1
        if record.issue is None or record.amount is None:
            # post-mint orphan return: escrow_return with no amount for a minted issue is a valid close
            if kind == "escrow_return" and record.issue is not None and record.issue in trajectory_mint_issues:
                pending = open_creates.get(record.issue, [])
                if pending:
                    pending.pop(0)
                    if not pending:
                        open_creates.pop(record.issue, None)
                continue
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
            # payment and escrow_return are exempt when the issue has no tracked create history
            if kind in ("payment", "escrow_return") and record.issue not in issues_with_tracked_create_history:
                continue
            # legacy era: issue had escrow events (not escrow_create) and all were consumed → WARNING
            if record.issue in issues_with_any_create and record.issue not in issues_with_tracked_create_history:
                reports.append(
                    _report_entry(
                        status="WARNING",
                        issue=record.issue,
                        reason="close_without_prior_create",
                        close_record=record,
                    )
                )
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
            # active escrows haven't been closed yet — not a violation
            if issue in active_escrows:
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

    failures_list = [entry for entry in reports if entry["status"] == "FAIL"]
    passes_list = [entry for entry in reports if entry["status"] == "PASS"]
    legacy_warnings_count = sum(1 for entry in reports if entry["status"] == "WARNING")
    close_without_prior_create_count = sum(
        1 for entry in failures_list if entry["reason"] == "close_without_prior_create"
    )

    # ── Classify legacy escrows ───────────────────────────────────────────────
    total_escrow_events = sum(legacy_escrow_counts.values())
    resolved_count = 0
    pending_count = 0
    orphan_escrows_list: list[dict[str, Any]] = []
    unresolved_count = 0

    for issue in sorted(legacy_escrow_counts.keys()):
        escrow_cnt = legacy_escrow_counts[issue]
        resolution_cnt = legacy_resolution_counts.get(issue, 0)
        resolved_for_issue = min(escrow_cnt, resolution_cnt)
        unresolved_for_issue = max(0, escrow_cnt - resolution_cnt)
        resolved_count += resolved_for_issue
        for _ in range(unresolved_for_issue):
            if issue in active_escrows:
                pending_count += 1
            elif issue in trajectory_mint_issues:
                orphan_escrows_list.append({"issue": _issue_display(issue)})
            else:
                unresolved_count += 1

    # ── Combined status ───────────────────────────────────────────────────────
    has_original_failures = len(failures_list) > 0
    has_orphan_escrows = len(orphan_escrows_list) > 0
    combined_status = "FAIL" if (has_original_failures or has_orphan_escrows) else "PASS"

    detail = (
        f"Found {len(failures_list)} lifecycle violation(s)."
        if has_original_failures
        else "All escrow_create events have exactly one later matching close event."
    )

    return {
        "status": combined_status,
        "checks": [
            {
                "name": CHECK_NAME,
                "status": "FAIL" if has_original_failures else "PASS",
                "detail": detail,
                "issues": reports,
            }
        ],
        "issues": reports,
        "orphan_escrows": orphan_escrows_list,
        "summary": {
            "history_files_scanned": len(history_files),
            "malformed_lines_skipped": malformed_lines,
            "escrow_create_events_scanned": escrow_create_events_scanned,
            "close_events_scanned": close_events_scanned,
            "passes": len(passes_list),
            "failures": len(failures_list),
            "total_checked": len(passes_list) + len(failures_list),
            "close_without_prior_create": close_without_prior_create_count,
            "legacy_warnings": legacy_warnings_count,
            "total_escrow_events": total_escrow_events,
            "resolved": resolved_count,
            "pending": pending_count,
            "orphan_escrows": len(orphan_escrows_list),
            "unresolved_escrows": unresolved_count,
        },
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
    if summary.get("total_escrow_events", 0) > 0 or summary.get("orphan_escrows", 0) > 0:
        print(
            "  "
            f"total_escrow_events={summary['total_escrow_events']} "
            f"resolved={summary['resolved']} "
            f"pending={summary['pending']} "
            f"orphan_escrows={summary['orphan_escrows']} "
            f"unresolved_escrows={summary['unresolved_escrows']}"
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
        if entry["status"] == "WARNING":
            print(
                f"  WARN issue {issue_text}: reason={entry['reason']} "
                f"close_kind={entry['close_kind']} close_amount={entry['close_amount']}"
            )
            continue
        print(
            f"  FAIL issue {issue_text}: reason={entry['reason']} "
            f"create_kind={entry['create_kind']} close_kind={entry['close_kind']} "
            f"create_amount={entry['create_amount']} close_amount={entry['close_amount']}"
        )
    for orphan in report.get("orphan_escrows", []):
        print(f"  ORPHAN issue #{orphan['issue']}: gauntlet mint with no escrow_return")


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
