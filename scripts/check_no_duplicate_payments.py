#!/usr/bin/env python3
"""Detect duplicate payment events for the same agent and issue."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


CHECK_NAME = "no_duplicate_payments"


def _repo_root_from(root: str | None) -> Path:
    if root:
        return Path(root).resolve()
    return Path(__file__).resolve().parent.parent


def _normalize_issue(issue: Any) -> str | None:
    if issue is None:
        return None
    return str(issue)


def _normalize_agent(agent: Any) -> str | None:
    if agent is None:
        return None
    return str(agent)


def _event_timestamp(event: dict[str, Any]) -> str | None:
    for key in ("timestamp", "event_at", "started_at"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def run_check(root: Path) -> dict[str, Any]:
    """Return a ledger-health-style report for duplicate payments."""
    history_dir = root / "ledger" / "history"
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    payment_events = 0
    skipped_legacy_payments = 0

    if history_dir.is_dir():
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
                if event.get("type") != "payment":
                    continue
                if event.get("type") == "trajectory_mint":
                    continue

                payment_events += 1
                issue = _normalize_issue(event.get("issue"))
                agent = _normalize_agent(event.get("agent"))
                if issue is None or agent is None:
                    continue

                # The live ledger contains pre-idempotency payment history where
                # the same agent could be paid multiple times for distinct slots
                # or submissions on one issue. Enforce the invariant on modern,
                # idempotent payment records while leaving legacy rows neutral.
                if not event.get("idem_key"):
                    skipped_legacy_payments += 1
                    continue

                grouped.setdefault((agent, issue), []).append(
                    {
                        "timestamp": _event_timestamp(event),
                        "file": path.name,
                        "line": line_number,
                    }
                )

    violations: list[dict[str, Any]] = []
    for (agent, issue), records in sorted(grouped.items()):
        if len(records) < 2:
            continue
        violations.append(
            {
                "agent": agent,
                "issue": issue,
                "count": len(records),
                "timestamps": [record["timestamp"] for record in records],
            }
        )

    status = "FAIL" if violations else "PASS"
    detail = (
        f"Found {len(violations)} duplicate payment group(s)."
        if violations
        else "No duplicate modern payment groups found."
    )
    return {
        "status": status,
        "checks": [
            {
                "name": CHECK_NAME,
                "status": status,
                "detail": detail,
                "violations": violations,
            }
        ],
        "summary": {
            "payment_events_scanned": payment_events,
            "payment_groups_checked": len(grouped),
            "violations": len(violations),
            "skipped_legacy_payments": skipped_legacy_payments,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check for duplicate payments per (agent, issue)")
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
