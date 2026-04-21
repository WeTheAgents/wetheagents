#!/usr/bin/env python3
"""Verify no accept/payment event follows a reject for the same issue and agent.

Usage:
    python scripts/check_reject_before_payment.py [--root PATH]

Scans ledger/history/*.jsonl, sorts relevant events chronologically, and flags
any accept or payment event that occurs after a reject for the same
``(issue, agent)`` pair.

Robustness notes:
- Malformed JSONL lines are skipped and counted; the check continues.
- Events missing a valid issue or agent field are skipped silently.
- Reject events store the FIRST reject timestamp for each pair; later
  reject events for the same pair do not overwrite it.
- Each (issue, agent) pair produces at most one violation entry per
  distinct payment/accept event after the first reject.

Output schema:
    {
      "status": "PASS" | "FAIL",
      "checks": [{"name": "reject_before_payment", "status": ...,
                  "reject_events": N, "accept_events": N,
                  "payment_events": N, "violations": N}],
      "violations": [{"issue": N, "agent": "...", "event_type": "...",
                      "event_ts": "...", "reject_ts": "...",
                      "reject_file": "...", "reject_line": N,
                      "event_file": "...", "event_line": N}],
      "stats": {"history_files_scanned": N, "history_events_scanned": N,
                "malformed_lines_skipped": N, "reject_events_scanned": N,
                "payment_events_scanned": N,
                "pairs_with_reject_before_payment": N},
      "summary": "..."
    }
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
_RELEVANT_TYPES = frozenset({"reject", "accept", "payment"})


@dataclass(frozen=True)
class TimelineEvent:
    """Relevant ledger history event used by the validator."""

    type: str
    issue: int
    agent: str
    timestamp: datetime
    timestamp_raw: str
    path: str
    line: int


def parse_iso_utc(value: str) -> datetime:
    """Parse an ISO timestamp and normalize it to UTC."""
    raw = value.strip()
    if not raw:
        raise ValueError("empty timestamp")
    normalized = raw.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _repo_root(script_path: Path) -> Path:
    return script_path.resolve().parent.parent


def _load_jsonl_line(raw: str) -> dict[str, Any] | None:
    """Parse one JSONL line, repairing legacy invalid escapes. Returns None on failure."""
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        repaired = _INVALID_ESCAPE_RE.sub(r"\\\\", raw)
        try:
            loaded = json.loads(repaired)
        except json.JSONDecodeError:
            return None
    if not isinstance(loaded, dict):
        return None
    return loaded


def _event_timestamp_fields(event: dict[str, Any]) -> tuple[datetime, str]:
    """Return the best available timestamp for a history event."""
    for key in ("timestamp", "ts", "event_at", "started_at", "created_at", "at"):
        value = str(event.get(key, "") or "").strip()
        if value:
            return parse_iso_utc(value), value
    raise ValueError("missing timestamp")


def _event_agent(event: dict[str, Any]) -> str:
    for key in ("agent", "author"):
        value = str(event.get(key, "") or "").strip().lower()
        if value:
            return value
    return ""


def _event_issue(event: dict[str, Any]) -> int | None:
    raw_issue = event.get("issue")
    if raw_issue is None:
        return None
    try:
        return int(raw_issue)
    except (TypeError, ValueError):
        return None


def load_relevant_events(
    root: Path,
) -> tuple[list[TimelineEvent], int, int, int]:
    """Load reject/accept/payment events sorted by timestamp, then file and line.

    Returns:
        (events, malformed_lines_skipped, total_valid_events, files_scanned)
    """
    history_dir = root / "ledger" / "history"
    if not history_dir.is_dir():
        return [], 0, 0, 0

    events: list[TimelineEvent] = []
    malformed_lines = 0
    total_valid = 0
    files = sorted(history_dir.glob("*.jsonl"))

    for path in files:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line_no, raw in enumerate(handle, start=1):
                stripped = raw.strip()
                if not stripped:
                    continue

                payload = _load_jsonl_line(stripped)
                if payload is None:
                    malformed_lines += 1
                    continue

                total_valid += 1

                if "type" not in payload:
                    malformed_lines += 1
                    total_valid -= 1
                    continue

                event_type = str(payload.get("type") or "").strip().lower()
                if event_type not in _RELEVANT_TYPES:
                    continue

                issue = _event_issue(payload)
                if issue is None:
                    continue  # skip events without a valid issue number

                agent = _event_agent(payload)
                if not agent:
                    continue  # skip events without a valid agent/author

                try:
                    timestamp, timestamp_raw = _event_timestamp_fields(payload)
                except ValueError:
                    malformed_lines += 1
                    total_valid -= 1
                    continue

                events.append(
                    TimelineEvent(
                        type=event_type,
                        issue=issue,
                        agent=agent,
                        timestamp=timestamp,
                        timestamp_raw=timestamp_raw,
                        path=path.name,
                        line=line_no,
                    )
                )

    events.sort(key=lambda item: (item.timestamp, item.path, item.line))
    return events, malformed_lines, total_valid, len(files)


def build_report(events: list[TimelineEvent]) -> dict[str, Any]:
    """Return the reject-before-payment validation report."""
    # Maps (issue, agent) -> first reject event; later rejects do not overwrite.
    rejected_at: dict[tuple[int, str], TimelineEvent] = {}
    reject_count = 0
    accept_count = 0
    payment_count = 0
    violations: list[dict[str, Any]] = []

    for event in events:
        key = (event.issue, event.agent)

        if event.type == "reject":
            if key not in rejected_at:  # preserve the first reject timestamp
                rejected_at[key] = event
            reject_count += 1
            continue

        if event.type == "accept":
            accept_count += 1
        elif event.type == "payment":
            payment_count += 1

        prior_reject = rejected_at.get(key)
        if prior_reject is None:
            continue

        violations.append(
            {
                "issue": event.issue,
                "agent": event.agent,
                "event_type": event.type,
                "event_ts": event.timestamp_raw,
                "reject_ts": prior_reject.timestamp_raw,
                "reject_file": prior_reject.path,
                "reject_line": prior_reject.line,
                "event_file": event.path,
                "event_line": event.line,
            }
        )

    status = "FAIL" if violations else "PASS"
    if violations:
        summary = (
            f"FAIL: found {len(violations)} accept/payment event(s) that follow a reject "
            "for the same issue and agent."
        )
    else:
        summary = (
            "PASS: no accept/payment events follow a reject for the same issue and agent."
        )

    return {
        "status": status,
        "checks": [
            {
                "name": "reject_before_payment",
                "status": status,
                "reject_events": reject_count,
                "accept_events": accept_count,
                "payment_events": payment_count,
                "violations": len(violations),
            }
        ],
        "violations": violations,
        "summary": summary,
    }


def run_check(root: Path) -> dict[str, Any]:
    """Load repo data and return the reject-before-payment report."""
    events, malformed_lines, total_valid, files_scanned = load_relevant_events(root)
    report = build_report(events)

    chk = report["checks"][0]
    report["stats"] = {
        "history_files_scanned": files_scanned,
        "history_events_scanned": total_valid,
        "malformed_lines_skipped": malformed_lines,
        "reject_events_scanned": chk["reject_events"],
        "payment_events_scanned": chk["accept_events"] + chk["payment_events"],
        "pairs_with_reject_before_payment": chk["violations"],
    }

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check that reject events are not followed by accept/payment for the same pair"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=_repo_root(Path(__file__)),
        help="Repository root (default: auto-detect)",
    )
    args = parser.parse_args(argv)

    report = run_check(args.root.resolve())
    print(json.dumps(report, indent=2))
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
