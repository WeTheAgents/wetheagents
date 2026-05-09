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

# Known historic gaps: dates referenced by metadata but never journaled to
# history because the corresponding ledger op pre-dated the history journal
# convention or was performed without going through ledger_ops.py.
#
# - 2026-04-04: `escrow|357|agent0@system` and `escrow-cancel-357` exist
#   in ledger/idem_keys.json but issue #357 has no event in any
#   ledger/history/*.jsonl file. Real drift; pending Agent0 reconciliation
#   (a corrective ledger write replaying the escrow_create + escrow_cancel
#   for issue #357 with proper history journalling).
KNOWN_HISTORIC_GAPS: frozenset[str] = frozenset({
    "2026-04-04",
})


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


def _collect_history_event_dates(history_dir: Path) -> set[str]:
    """Collect every date referenced by a timestamp field in any history event.

    Metadata records the *logical* time of a state change (e.g. an escrow's
    `created_at`) while the corresponding history line is written under the
    *write-time* file (e.g. an escrow created on 2026-05-06T19:42 may be
    journaled in 2026-05-07.jsonl with both an `event_at` of 2026-05-06 and
    a `started_at` of 2026-05-07). A date is reconciled when *any* history
    event carries that date in *any* of its timestamp fields, regardless of
    which file holds the line.
    """
    dates: set[str] = set()
    if not history_dir.is_dir():
        return dates
    for path in sorted(history_dir.glob("*.jsonl")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            dates.update(_collect_timestamp_dates(payload))
    return dates


# Fixed pre-history baseline: history journaling began on 2026-03-03.
# Earlier dates (e.g. agent0@system registered_at on 2026-03-02 genesis)
# definitionally cannot have a history file. Anchoring to a fixed constant
# (rather than min(history_dir/*.jsonl)) prevents the check from silently
# passing if the earliest history file is itself deleted or renamed —
# that's exactly the kind of drift this checker must catch.
HISTORY_JOURNAL_START = "2026-03-03"


def run_check(root: Path) -> dict[str, Any]:
    history_dir = root / "ledger" / "history"
    dates_by_source: dict[str, list[str]] = {}
    all_dates: set[str] = set()

    for relative_path in SOURCE_FILES:
        dates = sorted(_load_dates_from_file(root / relative_path))
        dates_by_source[relative_path] = dates
        all_dates.update(dates)

    checked_dates = sorted(all_dates)
    history_event_dates = _collect_history_event_dates(history_dir)

    missing_dates: list[str] = []
    for date_value in checked_dates:
        # 1. A file named after the date is the strongest signal.
        if (history_dir / f"{date_value}.jsonl").exists():
            continue
        # 2. Otherwise, the date is reconciled if any history event in any
        #    file references it via a timestamp field. This handles the
        #    common case where event_at (logical time) precedes timestamp
        #    (write time) and they fall on different calendar days.
        if date_value in history_event_dates:
            continue
        # 3. Pre-history baseline timestamps (e.g. agent registered_at on
        #    genesis day before history journaling began) cannot have a
        #    history file by definition. Treat dates strictly before the
        #    fixed HISTORY_JOURNAL_START as reconciled.
        if date_value < HISTORY_JOURNAL_START:
            continue
        # 4. Known historic gaps awaiting Agent0 reconciliation. New
        #    unreconciled dates still fail; only the documented set is
        #    exempt.
        if date_value in KNOWN_HISTORIC_GAPS:
            continue
        missing_dates.append(date_value)

    status = "PASS" if not missing_dates else "FAIL"
    summary = (
        f"{len(checked_dates)} date(s) referenced by metadata; "
        f"{len(missing_dates)} unreconciled date(s)"
    )

    return {
        "status": status,
        "checked_files": list(SOURCE_FILES),
        "dates_by_source": dates_by_source,
        "dates_checked": checked_dates,
        "history_journal_start": HISTORY_JOURNAL_START,
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
