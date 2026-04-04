#!/usr/bin/env python3
"""Stale escrow detection.

Loads ledger/escrows.json and ledger/task_index.json, computes age per escrow,
and reports three tiers:

  WARNING  7+ days, no accepted submissions
  STALE    14+ days, no accepted submissions
  FROZEN   21+ days, should be returned

Outputs JSON + human-readable text.
Exits 0 if no FROZEN escrows. Exits 1 if any FROZEN escrow is found.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from io_helpers import load_json  # noqa: E402

WARN_DAYS = 7
STALE_DAYS = 14
FROZEN_DAYS = 21


def _repo_root_from(root: str | None) -> Path:
    if root:
        return Path(root).resolve()
    return Path(__file__).resolve().parent.parent


def _parse_created_at(value: str) -> datetime | None:
    """Parse an ISO 8601 UTC timestamp (e.g. '2026-01-01T12:00:00Z').

    Returns None if the value is missing, None, or malformed.
    """
    if not value:
        return None
    try:
        # Normalise trailing 'Z' to '+00:00' for fromisoformat compatibility
        normalised = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalised)
    except (ValueError, AttributeError):
        return None


def _age_days(created_at: datetime, now: datetime) -> float:
    """Return the age of *created_at* in fractional days relative to *now*."""
    return (now - created_at).total_seconds() / 86400.0


def classify_escrows(
    escrows: dict[str, Any],
    tasks: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Classify active escrows into WARNING / STALE / FROZEN tiers.

    Each item in the returned lists is a dict with keys:
      issue       — issue number (str)
      age_days    — float days since created_at
      created_at  — original timestamp string (or None)
      amount      — WEA amount held in escrow
      tier        — 'WARNING' | 'STALE' | 'FROZEN'

    An escrow with a missing or unparseable created_at is included in a
    separate 'UNKNOWN' tier so it is visible without crashing.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    result: dict[str, list[dict[str, Any]]] = {
        "WARNING": [],
        "STALE": [],
        "FROZEN": [],
        "UNKNOWN": [],
    }

    active = escrows.get("active", {})
    all_tasks = tasks.get("tasks", {})

    for issue, escrow in sorted(active.items(), key=lambda kv: int(kv[0])):
        raw_ts = escrow.get("created_at")
        created_at = _parse_created_at(raw_ts)

        if created_at is None:
            result["UNKNOWN"].append({
                "issue": issue,
                "age_days": None,
                "created_at": raw_ts,
                "amount": escrow.get("amount", 0),
                "tier": "UNKNOWN",
            })
            continue

        age = _age_days(created_at, now)
        task = all_tasks.get(issue, {})
        has_submissions = bool(task.get("accepted_agents"))

        entry = {
            "issue": issue,
            "age_days": round(age, 2),
            "created_at": raw_ts,
            "amount": escrow.get("amount", 0),
        }

        if age >= FROZEN_DAYS:
            entry["tier"] = "FROZEN"
            result["FROZEN"].append(entry)
        elif age >= STALE_DAYS and not has_submissions:
            entry["tier"] = "STALE"
            result["STALE"].append(entry)
        elif age >= WARN_DAYS and not has_submissions:
            entry["tier"] = "WARNING"
            result["WARNING"].append(entry)

    return result


def format_report(classified: dict[str, list[dict[str, Any]]]) -> str:
    """Return a human-readable stale-escrow report string."""
    lines: list[str] = []

    tier_order = ["FROZEN", "STALE", "WARNING", "UNKNOWN"]
    tier_labels = {
        "FROZEN": "FROZEN (21+ days — return recommended)",
        "STALE":  "STALE  (14+ days, no submissions)",
        "WARNING": "WARNING (7+ days, no submissions)",
        "UNKNOWN": "UNKNOWN (missing created_at)",
    }

    any_found = any(classified[t] for t in tier_order)
    if not any_found:
        return "OK: no stale escrows found."

    for tier in tier_order:
        items = classified[tier]
        if not items:
            continue
        lines.append(f"\n{tier_labels[tier]}:")
        for item in items:
            age_str = f"{item['age_days']} days" if item["age_days"] is not None else "age unknown"
            lines.append(f"  #{item['issue']:>5}  {age_str:>12}  {item['amount']:>5} WEA  created: {item['created_at']}")

    return "\n".join(lines).lstrip("\n")


def run_check(
    root: Path,
    *,
    now: datetime | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], bool]:
    """Load ledger files, classify escrows, and return (classified, has_frozen)."""
    escrows = load_json(root / "ledger" / "escrows.json", default={"active": {}}, encoding="utf-8-sig")
    tasks = load_json(root / "ledger" / "task_index.json", default={"tasks": {}}, encoding="utf-8-sig")
    classified = classify_escrows(escrows, tasks, now=now)
    has_frozen = bool(classified["FROZEN"])
    return classified, has_frozen


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Detect stale escrows in the WeTheAgents ledger"
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Path to repository root (default: auto-detect from script location)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output machine-readable JSON instead of human-readable text",
    )
    args = parser.parse_args(argv)

    root = _repo_root_from(args.root)
    classified, has_frozen = run_check(root)

    if args.json_output:
        print(json.dumps(classified, indent=2))
    else:
        print(format_report(classified))

    return 1 if has_frozen else 0


if __name__ == "__main__":
    sys.exit(main())
