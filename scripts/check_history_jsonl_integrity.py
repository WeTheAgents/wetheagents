#!/usr/bin/env python3
"""Verify that all ledger/history/*.jsonl lines are valid JSON with required fields.

Scans every JSONL file in ledger/history/, checking each non-empty line for:
  - Valid JSON syntax
  - Presence of an event type field (type, event, event_type, or op)
  - Presence of a timestamp field (timestamp, ts, created_at, event_at, or at)
  - Numeric type for `amount` when present
  - int-or-null type for `issue` when present
  - Known event_type value (warning only for forward compatibility)

Exit code 0 if no violations (warnings allowed), 1 on any violation.
"""

from __future__ import annotations

import glob
import json
import os
import sys
from typing import Any

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY_DIR = os.path.join(BASE_DIR, "ledger", "history")

# Fields that can carry the event type (schema evolved over time).
_EVENT_TYPE_FIELDS = ("type", "event", "event_type", "op")

# Fields that can carry a timestamp (schema evolved over time).
_TIMESTAMP_FIELDS = ("timestamp", "ts", "created_at", "event_at", "at")

KNOWN_EVENT_TYPES = frozenset({
    "escrow_create",
    "escrow_return",
    "accept",
    "payment",
    "trajectory_mint",
    "registration_confirmed",
    "economy_reset",
    "reject",
})

VIOLATIONS: list[str] = []
WARNINGS: list[str] = []


def violation(location: str, msg: str) -> None:
    VIOLATIONS.append(f"  VIOLATION [{location}]: {msg}")


def warn(location: str, msg: str) -> None:
    WARNINGS.append(f"  WARNING [{location}]: {msg}")


def _event_type(event: dict[str, Any]) -> str | None:
    for field in _EVENT_TYPE_FIELDS:
        if field in event:
            return str(event[field])
    return None


def _has_timestamp(event: dict[str, Any]) -> bool:
    return any(f in event for f in _TIMESTAMP_FIELDS)


def check_event(event: dict[str, Any], location: str) -> None:
    """Validate a single parsed event object."""
    # Required: some event type field
    et = _event_type(event)
    if et is None:
        violation(location, f"missing event type field (none of {_EVENT_TYPE_FIELDS})")
        return  # can't check event type validity without the field

    # Required: some timestamp field
    if not _has_timestamp(event):
        violation(location, f"missing timestamp field (none of {_TIMESTAMP_FIELDS})")

    # Type check: amount must be numeric if present
    if "amount" in event:
        amt = event["amount"]
        if isinstance(amt, bool) or not isinstance(amt, (int, float)):
            violation(location, f"'amount' must be numeric, got {type(amt).__name__}: {amt!r}")

    # Type check: issue must be int or null if present
    if "issue" in event:
        iss = event["issue"]
        if iss is not None and (isinstance(iss, bool) or not isinstance(iss, int)):
            violation(location, f"'issue' must be int or null, got {type(iss).__name__}: {iss!r}")

    # Warning: unknown event type (forward compatibility)
    if et not in KNOWN_EVENT_TYPES:
        warn(location, f"unknown event_type '{et}' (not in known set)")


def check_file(path: str) -> None:
    """Validate all lines in a single JSONL file."""
    filename = os.path.basename(path)
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError as exc:
        violation(filename, f"cannot read file: {exc}")
        return

    for lineno, raw in enumerate(lines, 1):
        line = raw.rstrip("\n")
        if not line.strip():
            continue  # empty/whitespace lines are allowed

        location = f"{filename}:{lineno}"

        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            violation(location, f"invalid JSON: {exc}")
            continue

        if not isinstance(event, dict):
            violation(location, f"expected JSON object, got {type(event).__name__}")
            continue

        check_event(event, location)


def main(history_dir: str | None = None) -> int:
    VIOLATIONS.clear()
    WARNINGS.clear()

    scan_dir = history_dir or HISTORY_DIR

    print("--- History JSONL Integrity Check ---")

    if not os.path.isdir(scan_dir):
        violation(scan_dir, "history directory not found")
    else:
        pattern = os.path.join(scan_dir, "*.jsonl")
        files = sorted(glob.glob(pattern))
        for path in files:
            check_file(path)

    if WARNINGS:
        print(f"\n{len(WARNINGS)} warning(s):\n")
        for w in WARNINGS:
            print(w)

    if VIOLATIONS:
        print(f"\n{len(VIOLATIONS)} violation(s) found:\n")
        for v in VIOLATIONS:
            print(v)
        print("\nStatus: FAIL")
        return 1

    print(f"\nAll history JSONL lines pass integrity check ({len(WARNINGS)} warning(s)).")
    print("\nStatus: PASS")
    return 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Verify ledger/history/ JSONL integrity.")
    parser.add_argument("--history-dir", default=None, help="Path to history directory (default: ledger/history/ under repo root)")
    args = parser.parse_args()
    sys.exit(main(args.history_dir))
