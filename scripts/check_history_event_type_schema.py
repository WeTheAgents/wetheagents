#!/usr/bin/env python3
"""Validate required fields per event type in history JSONL.

Parses all JSONL files in ledger/history/ chronologically. For each event,
checks that required fields are present (with historical field aliases) and
that typed fields (amount, issue, slot, trajectory) have correct types and
values.

Unknown event types are flagged as warnings, not failures. Corrupt JSONL
lines are skipped and counted.

Exit codes:
    0 — no schema violations (warnings do not count)
    1 — one or more schema violations found

Output: JSON to stdout.
    {
      "status": "pass" | "fail",
      "violations": [
        {
          "file": "...",
          "line": N,
          "type": "...",
          "missing_fields": [...],
          "bad_fields": [...]
        }
      ],
      "stats": {
        "events_checked": N,
        "violations_found": N,
        "unknown_types": N
      }
    }
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# Timestamp field aliases (historical inconsistency in the ledger)
_TS_ALIASES: tuple[str, ...] = ("ts", "timestamp", "created_at", "event_at", "started_at", "at")

# Trajectory values recognised as valid
_VALID_TRAJECTORIES: frozenset[str] = frozenset({"T1", "T2", "T3", "T4", "T5", "T6"})

# Registration event types — only need an agent identity field
_REGISTRATION_TYPES: frozenset[str] = frozenset(
    {"registration", "agent_registration", "register", "registration_confirmed"}
)

# Payment-like events — need amount, recipient, issue, timestamp
_PAYMENT_TYPES: frozenset[str] = frozenset({"payment", "accept", "winner"})

# All event types this checker knows about
_KNOWN_TYPES: frozenset[str] = (
    _PAYMENT_TYPES
    | _REGISTRATION_TYPES
    | frozenset({"escrow_create", "escrow_return", "trajectory_mint"})
)


def _has_nonempty(event: dict[str, Any], *keys: str) -> bool:
    """Return True if any of the given keys maps to a truthy, non-whitespace value."""
    for k in keys:
        v = event.get(k)
        if v is None:
            continue
        if isinstance(v, str) and v.strip():
            return True
        if isinstance(v, list) and v:
            return True
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return True
    return False


def _check_event(event: dict[str, Any], event_type: str) -> tuple[list[str], list[str]]:
    """Validate a single parsed event against its type schema.

    event_type is the resolved type (already handling type/event/op aliases).
    Returns (missing_fields, bad_fields). Both lists are empty if the event
    is valid. Raises nothing.
    """
    missing: list[str] = []
    bad: list[str] = []

    # --- universal: timestamp --------------------------------------------------
    if not _has_nonempty(event, *_TS_ALIASES):
        missing.append("ts")

    # --- registration types ---------------------------------------------------
    if event_type in _REGISTRATION_TYPES:
        if not _has_nonempty(event, "agent_id", "agent"):
            missing.append("agent_id")
        return sorted(missing), sorted(bad)

    # --- payment / accept / winner -------------------------------------------
    if event_type in _PAYMENT_TYPES:
        if not _has_nonempty(event, "to", "agent"):
            missing.append("to")
        if "issue" not in event:
            missing.append("issue")
        elif not isinstance(event["issue"], int) or isinstance(event["issue"], bool):
            bad.append("issue")
        if "amount" not in event:
            missing.append("amount")
        else:
            amt = event["amount"]
            if not isinstance(amt, int) or isinstance(amt, bool):
                bad.append("amount")
            elif amt <= 0:
                bad.append("amount")
        if "idem_key" in event:
            # If present, must be a non-empty string
            ik = event["idem_key"]
            if not isinstance(ik, str) or not ik.strip():
                bad.append("idem_key")
        return sorted(missing), sorted(bad)

    # --- escrow_create --------------------------------------------------------
    if event_type == "escrow_create":
        if not _has_nonempty(event, "from", "author"):
            missing.append("from")
        if "issue" not in event:
            missing.append("issue")
        elif not isinstance(event["issue"], int) or isinstance(event["issue"], bool):
            bad.append("issue")
        if "amount" not in event:
            missing.append("amount")
        else:
            amt = event["amount"]
            if not isinstance(amt, int) or isinstance(amt, bool):
                bad.append("amount")
            elif amt < 0:
                bad.append("amount")
        if "idem_key" in event:
            ik = event["idem_key"]
            if not isinstance(ik, str) or not ik.strip():
                bad.append("idem_key")
        return sorted(missing), sorted(bad)

    # --- escrow_return --------------------------------------------------------
    if event_type == "escrow_return":
        if not _has_nonempty(event, "to", "recipient", "agent", "author"):
            missing.append("to")
        if "issue" not in event:
            missing.append("issue")
        elif not isinstance(event["issue"], int) or isinstance(event["issue"], bool):
            bad.append("issue")
        # amount is optional (orphan returns may omit it); validate type when present
        if "amount" in event:
            amt = event["amount"]
            if not isinstance(amt, int) or isinstance(amt, bool):
                bad.append("amount")
            elif amt < 0:
                # Zero is valid (reconciliation); negative is not
                bad.append("amount")
        if "idem_key" in event:
            ik = event["idem_key"]
            if not isinstance(ik, str) or not ik.strip():
                bad.append("idem_key")
        return sorted(missing), sorted(bad)

    # --- trajectory_mint ------------------------------------------------------
    if event_type == "trajectory_mint":
        if not _has_nonempty(event, "to", "agent", "agents"):
            missing.append("to")
        if "trajectory" not in event:
            missing.append("trajectory")
        elif event["trajectory"] not in _VALID_TRAJECTORIES:
            bad.append("trajectory")
        if "slot" not in event:
            missing.append("slot")
        else:
            sl = event["slot"]
            if not isinstance(sl, int) or isinstance(sl, bool):
                bad.append("slot")
            elif sl <= 0:
                bad.append("slot")
        if "issue" not in event:
            missing.append("issue")
        elif not isinstance(event["issue"], int) or isinstance(event["issue"], bool):
            bad.append("issue")
        if "amount" not in event:
            missing.append("amount")
        else:
            amt = event["amount"]
            if not isinstance(amt, int) or isinstance(amt, bool):
                bad.append("amount")
            elif amt <= 0:
                bad.append("amount")
        if "idem_key" in event:
            ik = event["idem_key"]
            if not isinstance(ik, str) or not ik.strip():
                bad.append("idem_key")
        return sorted(missing), sorted(bad)

    # Should not reach here for known types
    return sorted(missing), sorted(bad)


def _load_events(path: Path) -> list[tuple[int, dict[str, Any] | None]]:
    """Parse a JSONL file. Returns list of (lineno, event_or_None).

    None signals a parse error on that line.
    """
    results: list[tuple[int, dict[str, Any] | None]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return results
    for lineno, raw in enumerate(lines, 1):
        stripped = raw.strip()
        if not stripped:
            continue
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError:
            results.append((lineno, None))
            continue
        if not isinstance(obj, dict):
            results.append((lineno, None))
            continue
        results.append((lineno, obj))
    return results


def build_report(root: Path) -> dict[str, Any]:
    history_dir = root / "ledger" / "history"

    violations: list[dict[str, Any]] = []
    events_checked = 0
    unknown_types = 0

    if not history_dir.is_dir():
        return {
            "status": "pass",
            "violations": [],
            "stats": {"events_checked": 0, "violations_found": 0, "unknown_types": 0},
        }

    for path in sorted(history_dir.glob("*.jsonl")):
        for lineno, event in _load_events(path):
            if event is None:
                # Corrupt line — skip, count as skipped (not in events_checked)
                continue

            # Accept "event" and "op" as legacy aliases for "type"
            event_type = event.get("type") or event.get("event") or event.get("op")

            # Missing or empty type field
            if not isinstance(event_type, str) or not event_type.strip():
                events_checked += 1
                violations.append({
                    "file": path.name,
                    "line": lineno,
                    "type": None,
                    "missing_fields": ["type"],
                    "bad_fields": [],
                })
                continue

            events_checked += 1

            if event_type not in _KNOWN_TYPES:
                unknown_types += 1
                # Unknown type — warning only, not a violation
                continue

            missing, bad = _check_event(event, event_type)
            if missing or bad:
                violations.append({
                    "file": path.name,
                    "line": lineno,
                    "type": event_type,
                    "missing_fields": missing,
                    "bad_fields": bad,
                })

    return {
        "status": "fail" if violations else "pass",
        "violations": violations,
        "stats": {
            "events_checked": events_checked,
            "violations_found": len(violations),
            "unknown_types": unknown_types,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Repository root (default: auto-detected from script location)",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve() if args.root else Path(__file__).resolve().parent.parent
    report = build_report(root)
    print(json.dumps(report, indent=2))
    return 1 if report["status"] == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
