#!/usr/bin/env python3
"""Verify gauntlet mint amounts follow the 19 + slot formula.

In `ledger/trajectory_mints.json` and in `ledger/history/*.jsonl`, each
trajectory mint must have:

  amount == 19 + slot

This helper prints a JSON payload containing `status` (PASS/FAIL), all
formula violations, and a small summary. Exit code is 0 for PASS and 1 for
FAIL.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


WEA_BASE = 19


def _coerce_non_negative_int(
    value: Any, *, field_name: str
) -> tuple[int | None, str | None]:
    """Return a non-negative integer value and optional validation detail."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None, f"{field_name} is not an integer: {value!r}"
    if value < 0:
        return None, f"{field_name} is negative: {value}"
    return value, None


def _format_violation(
    *,
    source: str,
    trajectory: str,
    slot: Any,
    amount: Any,
    expected_amount: int | None,
    detail: str,
) -> dict[str, Any]:
    """Build a stable violation record."""
    return {
        "source": source,
        "trajectory": trajectory,
        "slot": slot,
        "amount": amount,
        "expected_amount": expected_amount,
        "detail": detail,
    }


def _check_formula(
    records: list[dict[str, Any]], source: str
) -> list[dict[str, Any]]:
    """Return formula violations for any iterable of trajectory mint-like records."""
    violations: list[dict[str, Any]] = []

    for record in records:
        trajectory = record.get("trajectory")
        if trajectory is None:
            trajectory = ""
        else:
            trajectory = str(trajectory)

        slot_raw = record.get("slot")
        amount_raw = record.get("amount")

        slot, slot_err = _coerce_non_negative_int(slot_raw, field_name="slot")
        if slot_err is not None:
            violations.append(
                _format_violation(
                    source=source,
                    trajectory=trajectory,
                    slot=slot_raw,
                    amount=amount_raw,
                    expected_amount=None,
                    detail=slot_err,
                )
            )
            continue

        amount, amount_err = _coerce_non_negative_int(
            amount_raw, field_name="amount"
        )
        if amount_err is not None:
            violations.append(
                _format_violation(
                    source=source,
                    trajectory=trajectory,
                    slot=slot,
                    amount=amount_raw,
                    expected_amount=WEA_BASE + slot,
                    detail=amount_err,
                )
            )
            continue

        expected = WEA_BASE + slot
        if amount != expected:
            violations.append(
                _format_violation(
                    source=source,
                    trajectory=trajectory,
                    slot=slot,
                    amount=amount,
                    expected_amount=expected,
                    detail=(
                        f"amount mismatch: expected {expected} for slot {slot} "
                        f"(19 + slot)"
                    ),
                )
            )

    return violations


def _load_trajectory_mints(root: Path) -> dict[str, Any]:
    """Load parsed ledger/trajectory_mints.json."""
    path = root / "ledger" / "trajectory_mints.json"
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _load_history_mint_events(root: Path) -> list[dict[str, Any]]:
    """Load all trajectory_mint events from ledger/history/*.jsonl."""
    events: list[dict[str, Any]] = []
    history_dir = root / "ledger" / "history"

    for path in sorted(history_dir.glob("*.jsonl")):
        with path.open(encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict) and event.get("type") == "trajectory_mint":
                    events.append(event)

    return events


def run_check(root: Path) -> dict[str, Any]:
    """Run the formula check and return a machine-readable payload."""
    data = _load_trajectory_mints(root)
    if not isinstance(data, dict):
        raise ValueError("trajectory_mints.json is not a JSON object")

    mints: list[dict[str, Any]] = data.get("mints", [])
    if not isinstance(mints, list):
        raise ValueError("trajectory_mints.json.mints is not a list")

    history_events = _load_history_mint_events(root)

    mint_violations = _check_formula(mints, source="trajectory_mints.json")
    history_violations = _check_formula(history_events, source="history")

    all_violations = mint_violations + history_violations

    return {
        "status": "PASS" if not all_violations else "FAIL",
        "mint_violations": mint_violations,
        "history_violations": history_violations,
        "summary": {
            "mint_events": len(mints),
            "history_events": len(history_events),
            "mint_violation_count": len(mint_violations),
            "history_violation_count": len(history_violations),
            "total_violations": len(all_violations),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify trajectory mint amounts are 19 + slot."
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Repository root (default: current directory)",
    )
    args = parser.parse_args(argv)

    try:
        result = run_check(Path(args.root).resolve())
    except (FileNotFoundError, json.JSONDecodeError, ValueError, TypeError) as exc:
        result = {
            "status": "FAIL",
            "mint_violations": [],
            "history_violations": [],
            "summary": {
                "mint_events": 0,
                "history_events": 0,
                "mint_violation_count": 0,
                "history_violation_count": 0,
                "total_violations": 1,
                "error": str(exc),
            },
        }

    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
