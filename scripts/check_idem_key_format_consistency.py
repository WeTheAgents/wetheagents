#!/usr/bin/env python3
"""Consistency check: idem_key prefix matches expected format for event type.

Scans ledger/history/*.jsonl and validates that each event's idem_key
starts with the expected prefix for its event_type.

Event type is read from the first non-empty field among ``event``, ``op``,
and ``type``.  This covers the three historical formats:
  - {"type": "payment", ...}           — standard format
  - {"event": "escrow_create", ...}    — event+mechanic-subtype format
  - {"op": "escrow_return", ...}       — op-keyed format

Prefix schemas per event type:

  accept              — starts with "accept|"
  escrow_create       — starts with "escrow_create" or "escrow-create-"
  escrow_return       — starts with "escrow-return-" or "escrow_return"
  trajectory_mint     — starts with "trajectory_mint|"
  payment             — starts with "payment|", "pay-", or "accept|" (legacy)
  registration_confirmed — any format (no constraint)

VIOLATION: idem_key does not match any allowed prefix for the event_type.
WARNING:   event_type has no defined prefix schema (forward compat).

Only events that carry an idem_key field are checked; events without one
are silently skipped.

Exit codes
----------
0 — PASS (no violations)
1 — FAIL (one or more violations, or fatal error reading ledger files)

Output: JSON to stdout with fields: status, violations, warnings, summary.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Allowed idem_key prefix patterns per event type.
# None  = any format accepted (no constraint).
# list  = idem_key must start with at least one of the given strings.
_SCHEMAS: dict[str, list[str] | None] = {
    "accept": ["accept|"],
    "escrow_create": ["escrow_create", "escrow-create-"],
    "escrow_return": ["escrow-return-", "escrow_return"],
    "trajectory_mint": ["trajectory_mint|"],
    "payment": ["payment|", "pay-", "accept|"],  # accept| is a legacy payment prefix
    "registration_confirmed": None,
}


def _repo_root(override: str | None = None) -> Path:
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parent.parent


def _iter_events(history_dir: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if not history_dir.is_dir():
        return events
    for path in sorted(history_dir.glob("*.jsonl")):
        for raw in path.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict):
                events.append(entry)
    return events


def _event_type(e: dict[str, Any]) -> str:
    # Prefer 'event' (semantic type) over 'op' over 'type' (which may hold
    # a mechanic subtype like "standard" when 'event' is also present).
    return e.get("event") or e.get("op") or e.get("type", "")


def check_format_consistency(
    events: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], str]:
    """Validate idem_key prefix for each event that carries one.

    Returns (status, violations, warnings, summary).
    """
    violations: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    checked = 0

    for e in events:
        raw_idem = e.get("idem_key", "")
        if not raw_idem:
            continue
        idem_key = str(raw_idem)

        event_type = _event_type(e)
        checked += 1

        if not event_type:
            warnings.append(
                {
                    "idem_key": idem_key,
                    "event_type": "",
                    "note": "event has no type field — cannot validate prefix",
                }
            )
            continue

        if event_type not in _SCHEMAS:
            warnings.append(
                {
                    "idem_key": idem_key,
                    "event_type": event_type,
                    "note": "no prefix schema defined for this event_type",
                }
            )
            continue

        allowed = _SCHEMAS[event_type]
        if allowed is None:
            # No constraint; any idem_key format is accepted.
            continue

        if not any(idem_key.startswith(p) for p in allowed):
            violations.append(
                {
                    "idem_key": idem_key,
                    "event_type": event_type,
                    "allowed_prefixes": allowed,
                    "note": "idem_key prefix does not match expected pattern for event_type",
                }
            )

    n_viol = len(violations)
    n_warn = len(warnings)
    status = "PASS" if n_viol == 0 else "FAIL"
    summary = (
        f"Checked {checked} event(s) with idem_key; "
        f"{n_viol} VIOLATION(s), {n_warn} WARNING(s)."
    )
    return status, violations, warnings, summary


def run(root: Path) -> tuple[dict[str, Any], bool]:
    """Execute the full check and return (result_dict, passed)."""
    history_dir = root / "ledger" / "history"

    if not history_dir.is_dir():
        result: dict[str, Any] = {
            "status": "FAIL",
            "violations": [],
            "warnings": [],
            "summary": f"history directory not found at {history_dir}",
        }
        return result, False

    try:
        events = _iter_events(history_dir)
    except OSError as exc:
        result = {
            "status": "FAIL",
            "violations": [],
            "warnings": [],
            "summary": f"error reading history directory: {exc}",
        }
        return result, False

    status, violations, warnings, summary = check_format_consistency(events)
    result = {
        "status": status,
        "violations": violations,
        "warnings": warnings,
        "summary": summary,
    }
    return result, status == "PASS"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify idem_key prefixes match the expected format for each event type."
        )
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root (default: auto-detected from script location)",
    )
    args = parser.parse_args()

    root = _repo_root(args.root)
    result, passed = run(root)

    print(json.dumps(result, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
