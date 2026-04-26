#!/usr/bin/env python3
"""Validate that ledger/history/ files are named and dated consistently.

Four checks are performed:

1. Every file in ledger/history/ must match the ``YYYY-MM-DD.jsonl`` pattern.
2. The date embedded in each filename must be a valid calendar date.
3. Every event's UTC timestamp date must be within ±1 calendar day of the
   filename date.  More than 1 day off is a VIOLATION.
4. Events within each file must appear in non-decreasing timestamp order.
   A timestamp that moves backward is a VIOLATION.

Output schema::

    {
      "status": "PASS" | "FAIL",
      "violations": [
        {
          "violation_type": "invalid_filename" | "invalid_date"
                            | "date_mismatch" | "out_of_order",
          "file": "2026-04-01.jsonl",
          ...  (type-specific fields)
        }
      ],
      "stats": {
        "files_scanned": 3,
        "events_checked": 42,
        "violations_found": 1
      }
    }
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

_FILENAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.jsonl$")
_INVALID_ESCAPE_RE = re.compile(r"\\(?![\"\\/bfnrtu])")
_TIMESTAMP_FIELDS = ("ts", "timestamp", "created_at", "started_at", "event_at", "at")


def _repo_root_from(root: str | None) -> Path:
    if root:
        return Path(root).resolve()
    return Path(__file__).resolve().parent.parent


def _parse_iso_utc(raw: str) -> datetime:
    parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_jsonl_line(raw: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        repaired = _INVALID_ESCAPE_RE.sub(r"\\\\", raw)
        try:
            payload = json.loads(repaired)
        except json.JSONDecodeError:
            return None
    return payload if isinstance(payload, dict) else None


def _extract_timestamp(event: dict[str, Any]) -> datetime | None:
    for field in _TIMESTAMP_FIELDS:
        value = event.get(field)
        if not isinstance(value, str) or not value.strip():
            continue
        try:
            return _parse_iso_utc(value)
        except ValueError:
            continue
    return None


def _scan_file(
    path: Path, file_date: date
) -> tuple[int, list[dict[str, Any]]]:
    events_checked = 0
    violations: list[dict[str, Any]] = []
    previous_ts: datetime | None = None

    with path.open(encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            stripped = raw.strip()
            if not stripped:
                continue

            event = _load_jsonl_line(stripped)
            if event is None:
                continue

            current_ts = _extract_timestamp(event)
            if current_ts is None:
                continue

            events_checked += 1
            event_date = current_ts.date()
            delta = abs((event_date - file_date).days)

            if delta > 1:
                violations.append(
                    {
                        "violation_type": "date_mismatch",
                        "file": path.name,
                        "index": events_checked,
                        "file_date": file_date.isoformat(),
                        "event_ts": _format_ts(current_ts),
                        "days_off": delta,
                    }
                )

            if previous_ts is not None and current_ts < previous_ts:
                violations.append(
                    {
                        "violation_type": "out_of_order",
                        "file": path.name,
                        "index": events_checked,
                        "ts_prev": _format_ts(previous_ts),
                        "ts_curr": _format_ts(current_ts),
                    }
                )

            previous_ts = current_ts

    return events_checked, violations


def run_check(root: Path) -> dict[str, Any]:
    history_dir = root / "ledger" / "history"
    if not history_dir.is_dir():
        return {
            "status": "PASS",
            "violations": [],
            "stats": {
                "files_scanned": 0,
                "events_checked": 0,
                "violations_found": 0,
            },
        }

    all_paths = sorted(p for p in history_dir.iterdir() if not p.name.startswith("."))
    violations: list[dict[str, Any]] = []
    files_scanned = 0
    events_checked = 0

    for path in all_paths:
        if not _FILENAME_RE.match(path.name):
            violations.append(
                {
                    "violation_type": "invalid_filename",
                    "file": path.name,
                    "reason": "does not match YYYY-MM-DD.jsonl pattern",
                }
            )
            continue

        date_str = path.stem
        try:
            file_date = date.fromisoformat(date_str)
        except ValueError:
            violations.append(
                {
                    "violation_type": "invalid_date",
                    "file": path.name,
                    "reason": f"{date_str!r} is not a valid calendar date",
                }
            )
            continue

        files_scanned += 1
        file_events, file_violations = _scan_file(path, file_date)
        events_checked += file_events
        violations.extend(file_violations)

    return {
        "status": "FAIL" if violations else "PASS",
        "violations": violations,
        "stats": {
            "files_scanned": files_scanned,
            "events_checked": events_checked,
            "violations_found": len(violations),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        default=None,
        help="Path to the repository root (default: auto-detect from script location)",
    )
    args = parser.parse_args(argv)

    report = run_check(_repo_root_from(args.root))
    print(json.dumps(report, indent=2))
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
