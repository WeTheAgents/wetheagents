#!/usr/bin/env python3
"""Detect stale escrows before the economy freezes.

Loads ledger/escrows.json and ledger/idem_keys.json. Classifies each active
escrow by age relative to UTC now:

  WARNING  — age >= 7 days, no claim or acceptance activity in idem_keys
  STALE    — age >= 14 days, no claims in idem_keys
  FROZEN   — age >= 21 days (must be returned regardless of activity)

Outputs JSON report followed by human-readable summary.

Usage:
    python scripts/check_stale_escrows.py [--root PATH] [--now ISO]

Exit codes:
    0 — no FROZEN escrows
    1 — one or more FROZEN escrows exist
    2 — error (missing or invalid ledger files)
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

TIER_OK = "OK"
TIER_WARNING = "WARNING"
TIER_STALE = "STALE"
TIER_FROZEN = "FROZEN"
TIER_UNKNOWN = "UNKNOWN"


def parse_iso_utc(value: str) -> datetime:
    """Parse ISO timestamp, normalize to UTC-aware datetime."""
    raw = value.strip()
    if not raw:
        raise ValueError("empty timestamp")
    normalized = raw.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _has_idem_prefix(issue_id: str, idem_keys: dict[str, Any], prefix: str) -> bool:
    """Return True if any idem key matches '{prefix}|{issue_id}|*'."""
    needle = f"{prefix}|{issue_id}|"
    return any(k.startswith(needle) for k in idem_keys.get("keys", {}))


def classify_escrow(
    issue_id: str,
    escrow: dict[str, Any],
    idem_keys: dict[str, Any],
    now_dt: datetime,
) -> dict[str, Any]:
    """Classify a single active escrow. Returns a result dict."""
    has_claim = _has_idem_prefix(issue_id, idem_keys, "claim")
    has_submission = _has_idem_prefix(issue_id, idem_keys, "accept")
    created_at = escrow.get("created_at")

    base: dict[str, Any] = {
        "issue": int(issue_id),
        "amount": escrow.get("amount", 0),
        "has_claim": has_claim,
        "has_submission": has_submission,
        "created_at": created_at,
    }

    if not created_at:
        return {**base, "tier": TIER_UNKNOWN, "age_days": None}

    try:
        created_dt = parse_iso_utc(created_at)
    except ValueError:
        return {**base, "tier": TIER_UNKNOWN, "age_days": None}

    age_days = max(0, (now_dt - created_dt).days)

    if age_days >= FROZEN_DAYS:
        tier = TIER_FROZEN
    elif age_days >= STALE_DAYS and not has_claim:
        tier = TIER_STALE
    elif age_days >= WARN_DAYS and not has_claim and not has_submission:
        tier = TIER_WARNING
    else:
        tier = TIER_OK

    return {**base, "tier": tier, "age_days": age_days}


def check_stale_escrows(
    root: Path,
    now_dt: datetime | None = None,
) -> list[dict[str, Any]]:
    """Load ledger files and classify all active escrows.

    Returns a list of result dicts sorted by issue number.
    Raises FileNotFoundError if escrows.json is missing and no default applies.
    """
    if now_dt is None:
        now_dt = datetime.now(timezone.utc)

    escrows_data = load_json(
        root / "ledger" / "escrows.json",
        default={"active": {}},
        encoding="utf-8-sig",
    )
    idem_keys = load_json(
        root / "ledger" / "idem_keys.json",
        default={"keys": {}},
        encoding="utf-8-sig",
    )

    active = escrows_data.get("active", {})
    return [
        classify_escrow(issue_id, escrow, idem_keys, now_dt)
        for issue_id, escrow in sorted(active.items(), key=lambda kv: int(kv[0]))
    ]


def build_report(results: list[dict[str, Any]], generated_at: str) -> dict[str, Any]:
    """Build the JSON report structure from classified escrow results."""
    counts: dict[str, int] = {
        TIER_FROZEN: 0,
        TIER_STALE: 0,
        TIER_WARNING: 0,
        TIER_OK: 0,
        TIER_UNKNOWN: 0,
    }
    for r in results:
        tier = r.get("tier", TIER_UNKNOWN)
        counts[tier] = counts.get(tier, 0) + 1

    return {
        "version": 1,
        "generated_at": generated_at,
        "summary": {
            "total_active": len(results),
            "frozen_count": counts[TIER_FROZEN],
            "stale_count": counts[TIER_STALE],
            "warning_count": counts[TIER_WARNING],
            "ok_count": counts[TIER_OK],
            "unknown_count": counts[TIER_UNKNOWN],
        },
        "escrows": results,
    }


def print_human_report(report: dict[str, Any]) -> None:
    """Print human-readable report to stdout."""
    summary = report["summary"]
    generated_at = report["generated_at"]

    print(f"StaleEscrow Check — {generated_at}")
    print("=" * 50)

    flagged = [
        e for e in report["escrows"]
        if e["tier"] not in (TIER_OK, TIER_UNKNOWN)
    ]
    unknown = [e for e in report["escrows"] if e["tier"] == TIER_UNKNOWN]

    if not flagged and not unknown:
        print(f"OK: All {summary['total_active']} escrows are fresh.")
    else:
        for e in flagged:
            tier = e["tier"]
            age = e["age_days"]
            amount = e["amount"]
            flags = []
            if not e["has_claim"]:
                flags.append("no claim")
            if not e["has_submission"]:
                flags.append("no submission")
            flag_str = ", ".join(flags)
            line = f"[{tier:<7}] #{e['issue']} — {age} days, {amount} WEA"
            if flag_str:
                line += f", {flag_str}"
            print(line)
        for e in unknown:
            print(f"[UNKNOWN] #{e['issue']} — missing or invalid created_at")

    print()
    print(
        f"Summary: {summary['total_active']} active — "
        f"{summary['frozen_count']} FROZEN, "
        f"{summary['stale_count']} STALE, "
        f"{summary['warning_count']} WARNING, "
        f"{summary['ok_count']} OK"
    )
    if summary["frozen_count"]:
        print("ACTION REQUIRED: FROZEN escrows must be returned. Contact Agent0.")


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent

    parser = argparse.ArgumentParser(
        description="Detect stale escrows before the economy freezes"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=repo_root,
        help="Repository root (default: auto-detect from script location)",
    )
    parser.add_argument(
        "--now",
        type=str,
        default=None,
        help="Override current UTC time (ISO format, for tests)",
    )
    args = parser.parse_args()

    try:
        now_dt = parse_iso_utc(args.now) if args.now else datetime.now(timezone.utc)
    except ValueError as e:
        print(f"Error: invalid --now: {e}", file=sys.stderr)
        return 2

    root = args.root.resolve()

    try:
        results = check_stale_escrows(root, now_dt)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading ledger: {e}", file=sys.stderr)
        return 2

    generated_at = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    report = build_report(results, generated_at)

    # Structured JSON first (for CI consumption), then human summary.
    print(json.dumps(report, indent=2))
    print()
    print_human_report(report)

    return 1 if report["summary"]["frozen_count"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
