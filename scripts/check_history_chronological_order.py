#!/usr/bin/env python3
"""Check that ledger history events appear in non-decreasing timestamp order.

The checker scans every ``ledger/history/*.jsonl`` file in line order and
compares each parsed event's best available timestamp against the previous
checked event in the same file. A violation is emitted whenever a timestamp
moves backwards.

For compatibility with legacy history data, malformed JSON lines, non-object
JSON values, and entries without a parseable timestamp are skipped instead of
failing the run outright.

Output schema:
    {
      "status": "PASS" | "FAIL",
      "violations": [
        {"file": "2026-04-01.jsonl", "index": 2,
         "ts_prev": "2026-04-01T10:00:00Z",
         "ts_curr": "2026-04-01T09:00:00Z"}
      ],
      "stats": {
        "files_scanned": 1,
        "events_checked": 2,
        "violations_found": 1
      }
    }
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_jsonl_line(raw: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        repaired = _INVALID_ESCAPE_RE.sub(r"\\\\", raw)
        try:
            payload = json.loads(repaired)
        except json.JSONDecodeError:
            return None

    if not isinstance(payload, dict):
        return None
    return payload


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


def _scan_file(path: Path) -> tuple[int, list[dict[str, Any]]]:
    events_checked = 0
    violations: list[dict[str, Any]] = []
    previous_timestamp: datetime | None = None

    with path.open(encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            stripped = raw.strip()
            if not stripped:
                continue

            payload = _load_jsonl_line(stripped)
            if payload is None:
                continue

            current_timestamp = _extract_timestamp(payload)
            if current_timestamp is None:
                continue

            events_checked += 1
            if (
                previous_timestamp is not None
                and current_timestamp < previous_timestamp
            ):
                violations.append(
                    {
                        "file": path.name,
                        "index": events_checked,
                        "ts_prev": _format_timestamp(previous_timestamp),
                        "ts_curr": _format_timestamp(current_timestamp),
                    }
                )

            previous_timestamp = current_timestamp

    return events_checked, violations


def run_check(root: Path) -> dict[str, Any]:
    history_dir = root / "ledger" / "history"
    history_files = sorted(history_dir.glob("*.jsonl")) if history_dir.is_dir() else []

    all_violations: list[dict[str, Any]] = []
    events_checked = 0

    for path in history_files:
        file_events_checked, file_violations = _scan_file(path)
        events_checked += file_events_checked
        all_violations.extend(file_violations)

    return {
        "status": "FAIL" if all_violations else "PASS",
        "violations": all_violations,
        "stats": {
            "files_scanned": len(history_files),
            "events_checked": events_checked,
            "violations_found": len(all_violations),
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
