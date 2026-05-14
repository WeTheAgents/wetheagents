#!/usr/bin/env python3
"""Check that payment amounts do not exceed their explicit escrow amount.

This checker scans ``ledger/history/*.jsonl`` and compares payment totals
against explicit per-issue escrow records.

Rules
-----
- ``escrow_create`` and legacy ``escrow`` events contribute explicit escrow
  amounts for their issue.
- ``escrow_batch`` events are tracked as legacy batch-only issues, but skipped
  from validation because they do not carry per-issue amounts.
- A payment issue with no explicit escrow is a violation unless it appears only
  in legacy batch history.
- If any single payment is larger than the issue escrow amount, that issue is a
  violation.
- Otherwise, if split payments total more than the issue escrow amount, that
  issue is a violation.

Output format
-------------
JSON to stdout with shape:
``{"status": "...", "violations": [...], "stats": {...}}``

Each violation entry contains:
``{issue, escrow_amount, payment_amount, delta}``

- ``payment_amount`` is the offending single payment when one payment exceeds
  escrow directly.
- ``payment_amount`` is the total paid amount when split payments overshoot
  escrow.
- ``delta`` is always ``payment_amount - escrow_amount``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _repo_root_from(root: str | None) -> Path:
    if root:
        return Path(root).resolve()
    return Path(__file__).resolve().parent.parent


def _normalize_issue(issue: Any) -> str | None:
    if issue is None:
        return None
    return str(issue)


def _numeric_amount(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _event_type(event: dict[str, Any]) -> str | None:
    for key in ("event", "op", "type"):
        raw = event.get(key)
        if isinstance(raw, str) and raw:
            return raw
    return None


def _payment_identity(event: dict[str, Any]) -> tuple[Any, ...] | None:
    """Return a duplicate-detection key for replayed payment rows.

    A repeated payment row with the same post-payment balance is a historical
    replay artifact, not a second spend. Rows without balance_after remain
    fully counted so real double payments are still detected.
    """
    if "balance_after" not in event:
        return None
    return (
        _normalize_issue(event.get("issue")),
        event.get("agent"),
        _numeric_amount(event.get("amount")),
        event.get("balance_after"),
        event.get("mechanic"),
        event.get("rank"),
    )


def _explicit_escrow_kind(event: dict[str, Any]) -> str | None:
    event_type = _event_type(event)
    if event_type == "escrow_create":
        return "escrow_create"
    if event_type == "escrow":
        return "legacy_escrow"
    return None


def _issue_sort_key(issue: str) -> tuple[int, Any]:
    return (0, int(issue)) if issue.isdigit() else (1, issue)


def run_check(root: Path) -> dict[str, Any]:
    """Return the payment-vs-escrow report for a repository root."""
    history_dir = root / "ledger" / "history"
    history_files = sorted(history_dir.glob("*.jsonl")) if history_dir.is_dir() else []

    escrow_amount_by_issue: dict[str, int | float] = {}
    batch_only_issues: set[str] = set()
    payment_totals_by_issue: dict[str, int | float] = {}
    max_payment_by_issue: dict[str, int | float] = {}
    seen_payment_identities: set[tuple[Any, ...]] = set()

    stats = {
        "history_files_scanned": len(history_files),
        "escrow_create_events_scanned": 0,
        "legacy_escrow_events_scanned": 0,
        "escrow_batch_events_scanned": 0,
        "payment_events_scanned": 0,
        "issues_with_explicit_escrow": 0,
        "issues_with_payments": 0,
        "skipped_batch_only_issues": 0,
        "skipped_invalid_json_lines": 0,
        "skipped_non_object_events": 0,
        "skipped_malformed_escrows": 0,
        "skipped_malformed_payments": 0,
        "deduped_duplicate_payments": 0,
        "violations": 0,
    }

    for path in history_files:
        for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line:
                continue

            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                stats["skipped_invalid_json_lines"] += 1
                continue

            if not isinstance(event, dict):
                stats["skipped_non_object_events"] += 1
                continue

            event_type = _event_type(event)

            if event_type == "escrow_batch":
                stats["escrow_batch_events_scanned"] += 1
                issues = event.get("issues", [])
                if isinstance(issues, list):
                    for raw_issue in issues:
                        issue = _normalize_issue(raw_issue)
                        if issue is not None:
                            batch_only_issues.add(issue)
                continue

            escrow_kind = _explicit_escrow_kind(event)
            if escrow_kind is not None:
                if escrow_kind == "escrow_create":
                    stats["escrow_create_events_scanned"] += 1
                else:
                    stats["legacy_escrow_events_scanned"] += 1

                issue = _normalize_issue(event.get("issue"))
                amount = _numeric_amount(event.get("amount"))
                if issue is None or amount is None or amount < 0:
                    stats["skipped_malformed_escrows"] += 1
                    continue

                escrow_amount_by_issue[issue] = escrow_amount_by_issue.get(issue, 0) + amount
                continue

            if event_type != "payment":
                continue

            stats["payment_events_scanned"] += 1

            issue = _normalize_issue(event.get("issue"))
            amount = _numeric_amount(event.get("amount"))
            if issue is None or amount is None or amount <= 0:
                stats["skipped_malformed_payments"] += 1
                continue

            payment_identity = _payment_identity(event)
            if payment_identity is not None:
                if payment_identity in seen_payment_identities:
                    stats["deduped_duplicate_payments"] += 1
                    continue
                seen_payment_identities.add(payment_identity)

            payment_totals_by_issue[issue] = payment_totals_by_issue.get(issue, 0) + amount
            max_payment_by_issue[issue] = max(max_payment_by_issue.get(issue, 0), amount)

    stats["issues_with_explicit_escrow"] = len(escrow_amount_by_issue)
    stats["issues_with_payments"] = len(payment_totals_by_issue)

    violations: list[dict[str, Any]] = []
    for issue in sorted(payment_totals_by_issue, key=_issue_sort_key):
        total_paid = payment_totals_by_issue[issue]
        max_payment = max_payment_by_issue[issue]
        escrow_amount = escrow_amount_by_issue.get(issue)

        if escrow_amount is None:
            if issue in batch_only_issues:
                stats["skipped_batch_only_issues"] += 1
                continue
            violations.append(
                {
                    "issue": issue,
                    "escrow_amount": 0,
                    "payment_amount": total_paid,
                    "delta": total_paid,
                }
            )
            continue

        if max_payment > escrow_amount:
            violations.append(
                {
                    "issue": issue,
                    "escrow_amount": escrow_amount,
                    "payment_amount": max_payment,
                    "delta": max_payment - escrow_amount,
                }
            )
            continue

        if total_paid > escrow_amount:
            violations.append(
                {
                    "issue": issue,
                    "escrow_amount": escrow_amount,
                    "payment_amount": total_paid,
                    "delta": total_paid - escrow_amount,
                }
            )

    stats["violations"] = len(violations)
    return {
        "status": "FAIL" if violations else "PASS",
        "violations": violations,
        "stats": stats,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check that payment amounts match explicit escrow totals")
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
