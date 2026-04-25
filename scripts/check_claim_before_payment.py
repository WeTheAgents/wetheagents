#!/usr/bin/env python3
"""Verify every payment is preceded by a same-agent claim for the same issue.

Usage:
    python scripts/check_claim_before_payment.py [--root PATH]

Scans ledger/history/*.jsonl, sorts all events by timestamp, and verifies that
each payment event has a prior claim event for the same issue and agent.

Compatibility note:
    Existing repositories may contain historical payment records from before
    claim events were written to history. To avoid retroactively failing that
    pre-claim era, enforcement begins at the timestamp of the first recorded
    claim event. If no claim events exist in history yet, the report passes with
    all payments marked as historical skips.

Output schema:
    {
      "status": "PASS" | "FAIL",
      "checks": [...],
      "violations": [{"issue", "agent", "payment_ts", "claim_ts"}],
      "summary": "..."
    }
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from bisect import bisect_left
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_INVALID_ESCAPE_RE = re.compile(r"\\(?![\"\\/bfnrtu])")


def parse_iso_utc(value: str) -> datetime:
    """Parse an ISO timestamp and normalize it to UTC."""
    raw = value.strip()
    if not raw:
        raise ValueError("empty timestamp")
    normalized = raw.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _repo_root(script_path: Path) -> Path:
    return script_path.resolve().parent.parent


def _load_jsonl_line(raw: str) -> dict[str, Any]:
    """Load one JSONL line, repairing legacy stray backslash escapes in strings."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        repaired = _INVALID_ESCAPE_RE.sub(r"\\\\", raw)
        return json.loads(repaired)


def _event_timestamp_fields(event: dict[str, Any]) -> tuple[datetime, str]:
    """Return the best available timestamp for ordering legacy history events."""
    for key in ("ts", "timestamp", "created_at", "started_at", "event_at", "at"):
        value = str(event.get(key, "") or "").strip()
        if value:
            return parse_iso_utc(value), value
    raise ValueError("missing timestamp")


def load_history_events(root: Path) -> list[dict[str, Any]]:
    """Load history events with timestamp metadata, sorted chronologically."""
    history_dir = root / "ledger" / "history"
    events: list[dict[str, Any]] = []

    if not history_dir.is_dir():
        return events

    for path in sorted(history_dir.glob("*.jsonl")):
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line_no, raw in enumerate(handle, start=1):
                raw = raw.strip()
                if not raw:
                    continue
                event = _load_jsonl_line(raw)
                try:
                    event_ts, ts_raw = _event_timestamp_fields(event)
                except ValueError as exc:
                    raise ValueError(f"{path.name}:{line_no} {exc}") from exc
                events.append(
                    {
                        "path": path.name,
                        "line": line_no,
                        "timestamp": event_ts,
                        "timestamp_raw": ts_raw,
                        "event": event,
                    }
                )

    events.sort(key=lambda item: (item["timestamp"], item["path"], item["line"]))
    return events


def _event_agent(event: dict[str, Any]) -> str:
    """Return the actor/recipient agent for claim-like or payment events."""
    for key in ("agent", "author"):
        value = str(event.get(key, "") or "").strip()
        if value:
            return value
    return ""


def _event_issue(event: dict[str, Any]) -> int | None:
    issue = event.get("issue")
    if issue is None:
        return None
    try:
        return int(issue)
    except (TypeError, ValueError):
        return None


def build_report(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the claim-before-payment validation report."""
    claim_times: dict[tuple[int, str], list[datetime]] = {}
    first_claim_ts: datetime | None = None
    total_payments = 0
    checked_payments = 0
    skipped_historical_payments = 0
    exempt_trajectory_mints = 0
    violations: list[dict[str, Any]] = []

    for item in events:
        event = item["event"]
        event_type = event.get("type")

        if event_type == "trajectory_mint":
            exempt_trajectory_mints += 1
            continue

        if event_type == "claim":
            issue = _event_issue(event)
            agent = _event_agent(event)
            if issue is None or not agent:
                continue
            key = (issue, agent)
            claim_times.setdefault(key, []).append(item["timestamp"])
            if first_claim_ts is None or item["timestamp"] < first_claim_ts:
                first_claim_ts = item["timestamp"]
            continue

        if event_type != "payment":
            continue

        total_payments += 1
        issue = _event_issue(event)
        agent = _event_agent(event)
        if issue is None or not agent:
            violations.append(
                {
                    "issue": issue,
                    "agent": agent,
                    "payment_ts": item["timestamp_raw"],
                    "claim_ts": None,
                }
            )
            checked_payments += 1
            continue

        if first_claim_ts is None or item["timestamp"] < first_claim_ts:
            skipped_historical_payments += 1
            continue

        checked_payments += 1
        key = (issue, agent)
        prior_claims = claim_times.get(key, [])
        index = bisect_left(prior_claims, item["timestamp"]) - 1
        claim_ts = prior_claims[index].strftime("%Y-%m-%dT%H:%M:%SZ") if index >= 0 else None
        if index < 0:
            violations.append(
                {
                    "issue": issue,
                    "agent": agent,
                    "payment_ts": item["timestamp_raw"],
                    "claim_ts": claim_ts,
                }
            )

    status = "FAIL" if violations else "PASS"
    first_claim_raw = (
        first_claim_ts.strftime("%Y-%m-%dT%H:%M:%SZ") if first_claim_ts is not None else None
    )

    if first_claim_raw is None:
        summary = (
            f"PASS: no claim events found in ledger/history; skipped {total_payments} "
            "historical payment(s) until claim logging begins."
        )
    elif violations:
        summary = (
            f"FAIL: {len(violations)} payment(s) lack a prior same-agent claim "
            f"for the same issue after enforcement began at {first_claim_raw}."
        )
    else:
        summary = (
            f"PASS: all {checked_payments} payment(s) after enforcement began at "
            f"{first_claim_raw} were preceded by a same-agent claim."
        )

    return {
        "status": status,
        "checks": [
            {
                "name": "claim_before_payment",
                "status": status,
                "claim_events": sum(len(times) for times in claim_times.values()),
                "payments_total": total_payments,
                "payments_checked": checked_payments,
                "payments_skipped_historical": skipped_historical_payments,
                "trajectory_mint_exemptions": exempt_trajectory_mints,
                "enforcement_started_at": first_claim_raw,
            }
        ],
        "violations": violations,
        "summary": summary,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify every payment is preceded by a same-agent claim"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=_repo_root(Path(__file__)),
        help="Repository root (default: auto-detect)",
    )
    args = parser.parse_args(argv)

    try:
        report = build_report(load_history_events(args.root.resolve()))
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        report = {
            "status": "FAIL",
            "checks": [
                {
                    "name": "claim_before_payment",
                    "status": "FAIL",
                    "error": str(exc),
                }
            ],
            "violations": [],
            "summary": f"FAIL: {exc}",
        }
        print(json.dumps(report, indent=2))
        return 1

    print(json.dumps(report, indent=2))
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
