#!/usr/bin/env python3
"""Detect missing daily history files for dates referenced by ledger metadata.

Scans timestamp values in:
- ledger/balances.json
- ledger/escrows.json
- ledger/trajectory_mints.json
- ledger/idem_keys.json

For each unique date referenced by those timestamps, verifies that
ledger/history/YYYY-MM-DD.jsonl exists.

Exit code: 0 on PASS, 1 on FAIL.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from io_helpers import load_json  # noqa: E402

TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T"
    r"\d{2}:\d{2}:\d{2}"
    r"(?:\.\d+)?"
    r"(?:Z|[+-]\d{2}:\d{2})?$"
)

SOURCE_FILES = (
    "ledger/balances.json",
    "ledger/escrows.json",
    "ledger/trajectory_mints.json",
    "ledger/idem_keys.json",
)


def _repo_root_from(root: str | None) -> Path:
    if root:
        return Path(root).resolve()
    return Path(__file__).resolve().parent.parent


def _timestamp_to_date(value: str) -> str | None:
    if not TIMESTAMP_RE.fullmatch(value):
        return None

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None

    return parsed.date().isoformat()


def _collect_timestamp_dates(payload: Any) -> set[str]:
    dates: set[str] = set()

    if isinstance(payload, dict):
        for value in payload.values():
            dates.update(_collect_timestamp_dates(value))
        return dates

    if isinstance(payload, list):
        for item in payload:
            dates.update(_collect_timestamp_dates(item))
        return dates

    if isinstance(payload, str):
        date_value = _timestamp_to_date(payload.strip())
        if date_value:
            dates.add(date_value)

    return dates


def _load_dates_from_file(path: Path) -> set[str]:
    payload = load_json(path, default={}, encoding="utf-8-sig")
    return _collect_timestamp_dates(payload)


def run_check(root: Path) -> dict[str, Any]:
    history_dir = root / "ledger" / "history"
    dates_by_source: dict[str, list[str]] = {}
    all_dates: set[str] = set()

    for relative_path in SOURCE_FILES:
        dates = sorted(_load_dates_from_file(root / relative_path))
        dates_by_source[relative_path] = dates
        all_dates.update(dates)

    checked_dates = sorted(all_dates)
    missing_dates = [
        date_value
        for date_value in checked_dates
        if not (history_dir / f"{date_value}.jsonl").exists()
    ]

    status = "PASS" if not missing_dates else "FAIL"
    summary = (
        f"{len(checked_dates)} date(s) referenced by metadata; "
        f"{len(missing_dates)} missing history file(s)"
    )

    return {
        "status": status,
        "checked_files": list(SOURCE_FILES),
        "dates_by_source": dates_by_source,
        "dates_checked": checked_dates,
        "missing_dates": missing_dates,
        "summary": summary,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root (default: auto-detect from script location)",
    )
    args = parser.parse_args(argv)

    result = run_check(_repo_root_from(args.root))
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
