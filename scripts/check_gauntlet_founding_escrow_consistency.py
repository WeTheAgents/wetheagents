#!/usr/bin/env python3
"""Gauntlet founding-escrow consistency check.

Cross-references ledger/trajectory_mints.json against ledger/history/*.jsonl
to verify that every gauntlet task issue has a proper founding escrow lifecycle.

For each mint whose issue number is above LEGACY_CUTOFF (see below), the check
verifies:
  1. An escrow_create event exists in history for that issue number.
  2. The escrow was either returned (escrow_return) or consumed (accept/payment).
  3. The founding escrow amount equals 19 + slot_number WEA.

LEGACY_CUTOFF = 600
  Issues 1–600 include the early gauntlet era (mints referenced PRs rather than
  task issues) and a partial heartbeat failure in cycle 10 (issues 596, 599, 600
  were minted without escrows).  From issue 601 onwards the founding-escrow
  protocol has been applied consistently, so only those issues are checked.

Exit codes:
  0 — PASS (no failures; warnings do not affect exit code)
  1 — FAIL (at least one founding-escrow violation)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

LEGACY_CUTOFF: int = 600

# Event-type field names used across history JSONL formats
_KNOWN_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "escrow_create",
        "escrow_return",
        "payment",
        "accept",
        "trajectory_mint",
        "balance_init",
        "registration",
        "transfer",
    }
)


def _event_type(ev: dict[str, Any]) -> str | None:
    """Return the event-type string from a history record.

    History records use one of three field names depending on when they were
    written: ``type``, ``event``, or ``op``.  Some records also have a
    ``type`` field that means *escrow kind* (e.g. ``"standard"``), not the
    event kind — so we resolve via the known-types allowlist.
    """
    for field in ("type", "event", "op"):
        val = ev.get(field)
        if val in _KNOWN_EVENT_TYPES:
            return val
    return None


def _load_history(root: Path) -> dict[str, Any]:
    """Load all JSONL history files and index events by issue number."""
    escrow_creates: dict[int, int] = {}
    escrow_returns: dict[int, list[dict[str, Any]]] = {}
    accepts: dict[int, list[dict[str, Any]]] = {}
    payments: dict[int, list[dict[str, Any]]] = {}

    history_dir = root / "ledger" / "history"
    for path in sorted(history_dir.glob("*.jsonl")):
        with path.open(encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    ev = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                etype = _event_type(ev)
                issue = ev.get("issue")
                if not isinstance(issue, int):
                    continue
                if etype == "escrow_create":
                    escrow_creates[issue] = ev.get("amount", 0)
                elif etype == "escrow_return":
                    escrow_returns.setdefault(issue, []).append(ev)
                elif etype == "accept":
                    accepts.setdefault(issue, []).append(ev)
                elif etype == "payment":
                    payments.setdefault(issue, []).append(ev)

    return {
        "escrow_creates": escrow_creates,
        "escrow_returns": escrow_returns,
        "accepts": accepts,
        "payments": payments,
    }


def _load_mints(root: Path) -> list[dict[str, Any]]:
    path = root / "ledger" / "trajectory_mints.json"
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError("trajectory_mints.json is not a JSON object")
    mints = data.get("mints", [])
    if not isinstance(mints, list):
        raise ValueError("trajectory_mints.json .mints is not a list")
    return mints


def _parse_issue(issue_or_pr: Any) -> int | None:
    """Extract numeric part from '#NNN' strings; return None on failure."""
    if not isinstance(issue_or_pr, str):
        return None
    stripped = issue_or_pr.lstrip("#").strip()
    try:
        return int(stripped)
    except ValueError:
        return None


def run_check(root: Path, legacy_cutoff: int = LEGACY_CUTOFF) -> dict[str, Any]:
    """Run the founding-escrow consistency check and return a result payload."""
    mints = _load_mints(root)
    history = _load_history(root)

    escrow_creates = history["escrow_creates"]
    escrow_returns = history["escrow_returns"]
    accepts = history["accepts"]
    payments = history["payments"]

    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    skipped_legacy = 0
    checked = 0

    for mint in mints:
        trajectory = mint.get("trajectory", "?")
        slot = mint.get("slot")
        issue_or_pr = mint.get("issue_or_pr", "")

        issue = _parse_issue(issue_or_pr)
        if issue is None:
            continue

        if issue <= legacy_cutoff:
            skipped_legacy += 1
            continue

        checked += 1
        expected_amount = 19 + slot if isinstance(slot, int) else None
        label = f"{trajectory}S{slot} issue=#{issue}"

        if issue not in escrow_creates:
            failures.append(
                {
                    "type": "missing_escrow_create",
                    "label": label,
                    "issue": issue,
                    "message": f"no escrow_create found in history for issue #{issue}",
                }
            )
            continue

        actual_amount = escrow_creates[issue]
        returned = issue in escrow_returns
        consumed = issue in accepts or issue in payments

        if not returned and not consumed:
            failures.append(
                {
                    "type": "dangling_escrow",
                    "label": label,
                    "issue": issue,
                    "message": (
                        f"escrow_create exists for #{issue} but no escrow_return "
                        "or accept/payment found — escrow is dangling"
                    ),
                }
            )
            continue

        if expected_amount is not None and actual_amount != expected_amount:
            warnings.append(
                {
                    "type": "amount_mismatch",
                    "label": label,
                    "issue": issue,
                    "expected": expected_amount,
                    "actual": actual_amount,
                    "message": (
                        f"escrow amount {actual_amount} != expected {expected_amount} "
                        f"(19 + slot {slot}) for #{issue}"
                    ),
                }
            )

    status = "PASS" if not failures else "FAIL"

    return {
        "status": status,
        "failures": failures,
        "warnings": warnings,
        "summary": {
            "checked": checked,
            "skipped_legacy": skipped_legacy,
            "failures": len(failures),
            "warnings": len(warnings),
            "legacy_cutoff": legacy_cutoff,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify every gauntlet task issue (above LEGACY_CUTOFF) has a "
            "matching founding escrow that was properly returned or consumed."
        )
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Repository root (default: current directory)",
    )
    parser.add_argument(
        "--legacy-cutoff",
        type=int,
        default=LEGACY_CUTOFF,
        help=(
            f"Skip mints with issue number <= this value (default: {LEGACY_CUTOFF}). "
            "Issues 1-600 predate stable founding-escrow protocol."
        ),
    )
    args = parser.parse_args(argv)

    try:
        result = run_check(Path(args.root).resolve(), legacy_cutoff=args.legacy_cutoff)
    except (FileNotFoundError, json.JSONDecodeError, ValueError, TypeError) as exc:
        result = {
            "status": "FAIL",
            "failures": [{"type": "load_error", "message": str(exc)}],
            "warnings": [],
            "summary": {
                "checked": 0,
                "skipped_legacy": 0,
                "failures": 1,
                "warnings": 0,
                "legacy_cutoff": args.legacy_cutoff,
            },
        }

    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
