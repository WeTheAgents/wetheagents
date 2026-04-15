#!/usr/bin/env python3
"""Detect active escrows older than a configurable threshold."""

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

DEFAULT_THRESHOLD_DAYS = 7.0


def _repo_root_from(root: str | None) -> Path:
    if root:
        return Path(root).resolve()
    return Path(__file__).resolve().parent.parent


def _parse_created_at(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _age_days(created_at: datetime, now: datetime) -> float:
    return (now - created_at).total_seconds() / 86400.0


def build_report(
    escrows: dict[str, Any],
    *,
    now: datetime | None = None,
    threshold_days: float = DEFAULT_THRESHOLD_DAYS,
    strict: bool = False,
) -> dict[str, Any]:
    if now is None:
        now = datetime.now(timezone.utc)

    stale: list[dict[str, Any]] = []
    skipped_missing_created_at = 0

    active = escrows.get("active", {})
    for issue, escrow in sorted(active.items(), key=lambda item: int(item[0])):
        created_at_raw = escrow.get("created_at")
        created_at = _parse_created_at(created_at_raw)
        if created_at is None:
            skipped_missing_created_at += 1
            continue

        age_days = _age_days(created_at, now)
        if age_days >= threshold_days:
            stale.append(
                {
                    "issue": str(issue),
                    "age_days": round(age_days, 2),
                    "amount": escrow.get("amount", 0),
                    "created_at": created_at_raw,
                }
            )

    if stale and strict:
        status = "FAIL"
    elif stale:
        status = "WARN"
    else:
        status = "PASS"

    summary = f"{len(stale)} stale escrow(s) at or above {threshold_days:g} days"
    if skipped_missing_created_at:
        summary += f"; skipped {skipped_missing_created_at} with missing/invalid created_at"

    return {
        "status": status,
        "stale": stale,
        "summary": summary,
    }


def run_check(
    root: Path,
    *,
    now: datetime | None = None,
    threshold_days: float = DEFAULT_THRESHOLD_DAYS,
    strict: bool = False,
) -> dict[str, Any]:
    escrows = load_json(
        root / "ledger" / "escrows.json",
        default={"active": {}},
        encoding="utf-8-sig",
    )
    return build_report(
        escrows,
        now=now,
        threshold_days=threshold_days,
        strict=strict,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Detect stale active escrows in ledger/escrows.json"
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root (default: auto-detect from script location)",
    )
    parser.add_argument(
        "--threshold-days",
        type=float,
        default=DEFAULT_THRESHOLD_DAYS,
        help=f"Age threshold in days (default: {DEFAULT_THRESHOLD_DAYS:g})",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return FAIL and exit 1 if stale escrows are found",
    )
    args = parser.parse_args(argv)

    report = run_check(
        _repo_root_from(args.root),
        threshold_days=args.threshold_days,
        strict=args.strict,
    )
    print(json.dumps(report))
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
