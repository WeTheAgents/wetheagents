#!/usr/bin/env python3
"""
Escrow Schema Validator.

Validates every active entry in ledger/escrows.json against the required schema.
Cross-checks `author` against registered agents in ledger/balances.json.

Output: JSON to stdout with keys: status, checks, violations, summary.
Exit codes:
    0 — all active escrows pass schema validation (PASS)
    1 — one or more violations found (FAIL)
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER_DIR = os.path.join(BASE_DIR, "ledger")

VALID_TYPES = {"pod", "progressive", "winner_take_all", "x_best", "duel", "linear"}


def _is_iso8601(value: str) -> bool:
    """Return True if value is a valid ISO 8601 *datetime* string (date + time required).

    Bare date strings like "2026-04-13" are rejected — created_at must include time.
    """
    if not isinstance(value, str):
        return False
    # Require the 'T' separator — date-only strings are not valid for a timestamp field
    if "T" not in value:
        return False
    # Accept formats like 2026-04-13T03:49:25Z or 2026-04-13T03:49:25+00:00
    for fmt in (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S+00:00",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%S.%f+00:00",
        "%Y-%m-%dT%H:%M:%S%z",
    ):
        try:
            datetime.strptime(value, fmt)
            return True
        except ValueError:
            continue
    # Last attempt using fromisoformat (Python 3.7+)
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def validate_entry(issue: str, entry: object, known_agents: set[str]) -> list[dict]:
    """Validate a single escrow entry. Returns a list of violation dicts."""
    violations: list[dict] = []

    if not isinstance(entry, dict):
        violations.append({
            "issue": issue,
            "field": "(entry)",
            "reason": "escrow entry must be a JSON object",
        })
        return violations

    # author: required, non-empty string, must be a known agent
    if "author" not in entry:
        violations.append({"issue": issue, "field": "author", "reason": "missing required field"})
    elif not isinstance(entry["author"], str) or not entry["author"].strip():
        violations.append({"issue": issue, "field": "author", "reason": "must be a non-empty string"})
    elif known_agents and entry["author"] not in known_agents:
        violations.append({
            "issue": issue,
            "field": "author",
            "reason": f"'{entry['author']}' not found in balances.json agents",
        })

    # amount: required, int or float, > 0
    if "amount" not in entry:
        violations.append({"issue": issue, "field": "amount", "reason": "missing required field"})
    else:
        amt = entry["amount"]
        if not isinstance(amt, (int, float)) or isinstance(amt, bool):
            violations.append({"issue": issue, "field": "amount", "reason": "must be a number (int or float)"})
        elif amt <= 0:
            violations.append({
                "issue": issue,
                "field": "amount",
                "reason": f"must be > 0, got {amt}",
            })

    # type: required, one of VALID_TYPES
    if "type" not in entry:
        violations.append({
            "issue": issue,
            "field": "type",
            "reason": f"missing required field; must be one of {sorted(VALID_TYPES)}",
        })
    elif entry["type"] not in VALID_TYPES:
        violations.append({
            "issue": issue,
            "field": "type",
            "reason": f"invalid value '{entry['type']}'; must be one of {sorted(VALID_TYPES)}",
        })

    # created_at: required, ISO 8601 string
    if "created_at" not in entry:
        violations.append({"issue": issue, "field": "created_at", "reason": "missing required field"})
    elif not _is_iso8601(entry["created_at"]):
        violations.append({
            "issue": issue,
            "field": "created_at",
            "reason": f"'{entry['created_at']}' is not a valid ISO 8601 datetime",
        })

    # Optional: slots — int, > 0
    if "slots" in entry:
        slots = entry["slots"]
        if not isinstance(slots, int) or isinstance(slots, bool):
            violations.append({"issue": issue, "field": "slots", "reason": "must be an int"})
        elif slots <= 0:
            violations.append({"issue": issue, "field": "slots", "reason": f"must be > 0, got {slots}"})

    # Optional: paid_count — int, >= 0, <= slots (if slots present)
    if "paid_count" in entry:
        pc = entry["paid_count"]
        if not isinstance(pc, int) or isinstance(pc, bool):
            violations.append({"issue": issue, "field": "paid_count", "reason": "must be an int"})
        elif pc < 0:
            violations.append({"issue": issue, "field": "paid_count", "reason": f"must be >= 0, got {pc}"})
        elif "slots" in entry and isinstance(entry["slots"], int) and not isinstance(entry["slots"], bool):
            if pc > entry["slots"]:
                violations.append({
                    "issue": issue,
                    "field": "paid_count",
                    "reason": f"paid_count ({pc}) > slots ({entry['slots']})",
                })

    # Optional: winners — int, > 0
    if "winners" in entry:
        w = entry["winners"]
        if not isinstance(w, int) or isinstance(w, bool):
            violations.append({"issue": issue, "field": "winners", "reason": "must be an int"})
        elif w <= 0:
            violations.append({"issue": issue, "field": "winners", "reason": f"must be > 0, got {w}"})

    return violations


def run(escrows_data: dict, balances_data: dict | None = None) -> dict:
    """Validate escrows_data and return a result dict.

    Args:
        escrows_data: parsed escrows.json content.
        balances_data: parsed balances.json content (optional). When provided,
            author values are checked against registered agents.
    """
    all_violations: list[dict] = []
    checks: list[dict] = []

    # Top-level structure checks
    if "version" not in escrows_data:
        all_violations.append({
            "issue": "(top-level)",
            "field": "version",
            "reason": "missing required top-level key",
        })

    if "active" not in escrows_data:
        all_violations.append({
            "issue": "(top-level)",
            "field": "active",
            "reason": "missing required top-level key",
        })
        status = "FAIL"
        return {
            "status": status,
            "checks": checks,
            "violations": all_violations,
            "summary": f"Cannot validate entries: top-level 'active' key missing.",
        }

    active = escrows_data["active"]
    if not isinstance(active, dict):
        all_violations.append({
            "issue": "(top-level)",
            "field": "active",
            "reason": "'active' must be a JSON object",
        })
        status = "FAIL"
        return {
            "status": status,
            "checks": checks,
            "violations": all_violations,
            "summary": "'active' is not an object.",
        }

    known_agents: set[str] = set()
    if balances_data and isinstance(balances_data.get("agents"), dict):
        known_agents = set(balances_data["agents"].keys())

    for issue, entry in active.items():
        entry_violations = validate_entry(issue, entry, known_agents)
        all_violations.extend(entry_violations)
        checks.append({
            "issue": issue,
            "status": "FAIL" if entry_violations else "PASS",
            "violations": entry_violations,
        })

    status = "FAIL" if all_violations else "PASS"
    total = len(active)
    failed = sum(1 for c in checks if c["status"] == "FAIL")
    summary = (
        f"{total} escrow(s) checked: {total - failed} passed, {failed} failed, "
        f"{len(all_violations)} violation(s) total."
    )
    return {
        "status": status,
        "checks": checks,
        "violations": all_violations,
        "summary": summary,
    }


def main() -> None:
    escrows_path = os.path.join(LEDGER_DIR, "escrows.json")
    balances_path = os.path.join(LEDGER_DIR, "balances.json")

    if not os.path.exists(escrows_path):
        result = {
            "status": "FAIL",
            "checks": [],
            "violations": [{"issue": "(file)", "field": "escrows.json", "reason": "file not found"}],
            "summary": "escrows.json not found.",
        }
        print(json.dumps(result, indent=2))
        sys.exit(1)

    try:
        with open(escrows_path, encoding="utf-8") as f:
            escrows_data = json.load(f)
    except json.JSONDecodeError as e:
        result = {
            "status": "FAIL",
            "checks": [],
            "violations": [{"issue": "(file)", "field": "escrows.json", "reason": f"invalid JSON: {e}"}],
            "summary": "escrows.json contains invalid JSON.",
        }
        print(json.dumps(result, indent=2))
        sys.exit(1)

    balances_data = None
    if os.path.exists(balances_path):
        try:
            with open(balances_path, encoding="utf-8") as f:
                balances_data = json.load(f)
        except json.JSONDecodeError:
            pass  # balances unavailable; skip author cross-check

    result = run(escrows_data, balances_data)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
