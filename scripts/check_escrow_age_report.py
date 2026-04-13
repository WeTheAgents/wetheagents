#!/usr/bin/env python3
"""Escrow age reporter for active ledger escrows."""

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

FRESH_MAX_DAYS = 6
AGING_MAX_DAYS = 13
STALE_MAX_DAYS = 29


def _repo_root_from(root: str | None) -> Path:
    if root:
        return Path(root).resolve()
    return Path(__file__).resolve().parent.parent


def _parse_created_at(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _age_days(created_at: datetime, now: datetime) -> int:
    delta_seconds = (now - created_at).total_seconds()
    if delta_seconds <= 0:
        return 0
    return int(delta_seconds // 86400)


def classify_age(age_days: int) -> str:
    if age_days <= FRESH_MAX_DAYS:
        return "FRESH"
    if age_days <= AGING_MAX_DAYS:
        return "AGING"
    if age_days <= STALE_MAX_DAYS:
        return "STALE"
    return "FROZEN"


def build_report(
    escrows: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    if now is None:
        now = datetime.now(timezone.utc)

    active = escrows.get("active", {})
    rows: list[dict[str, Any]] = []
    summary = {
        "fresh": 0,
        "aging": 0,
        "stale": 0,
        "frozen": 0,
    }

    for issue, escrow in sorted(active.items(), key=lambda item: int(item[0])):
        created_at_raw = str(escrow["created_at"])
        created_at = _parse_created_at(created_at_raw)
        age_days = _age_days(created_at, now)
        classification = classify_age(age_days)
        summary[classification.lower()] += 1
        rows.append(
            {
                "issue": int(issue),
                "age_days": age_days,
                "classification": classification,
                "created_at": created_at_raw,
            }
        )

    if summary["frozen"] > 0:
        status = "FAIL"
    elif summary["stale"] > 0:
        status = "WARN"
    else:
        status = "PASS"

    checks = [
        {
            "name": "escrow_age",
            "status": status,
            "summary": (
                f"{summary['fresh']} fresh, {summary['aging']} aging, "
                f"{summary['stale']} stale, {summary['frozen']} frozen"
            ),
            "duration_ms": 0,
        }
    ]

    return {
        "status": status,
        "checks": checks,
        "escrows": rows,
        "summary": summary,
    }


def run_check(root: Path, *, now: datetime | None = None) -> dict[str, Any]:
    escrows = load_json(
        root / "ledger" / "escrows.json",
        default={"active": {}},
        encoding="utf-8-sig",
    )
    return build_report(escrows, now=now)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Report escrow age buckets for active ledger escrows"
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root (default: auto-detect from script location)",
    )
    args = parser.parse_args(argv)

    report = run_check(_repo_root_from(args.root))
    print(json.dumps(report, indent=2))
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
