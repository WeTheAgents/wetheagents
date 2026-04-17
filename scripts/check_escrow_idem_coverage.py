#!/usr/bin/env python3
"""check_escrow_idem_coverage.py

Cross-validate escrow_create history events against ledger/idem_keys.json,
specifically for the `escrow_create_<issue>_*` key format used by the gauntlet.

Two directions:
  1. History → idem_keys: every escrow_create event that carries an explicit
     `idem_key` field (format `escrow_create_<issue>_*`) and whose escrow is
     still ACTIVE (no matching escrow_return in history) must have that exact
     key registered in idem_keys.json.  A missing key on a fully-returned
     escrow is a resolved historical artifact, not an active risk.

  2. idem_keys → history: every key starting with `escrow_create_` in
     idem_keys.json must have a corresponding escrow_create history event
     for the same issue number.

Output JSON:
  {
    "status": "PASS" | "FAIL",
    "missing_idem_keys": [...],   // active escrows with no idem key registered
    "orphaned_idem_keys": [...],  // idem keys with no history event
    "summary": "..."
  }

Exit codes:
  0  PASS
  1  FAIL (missing active-escrow idem keys or orphaned idem keys found)
  2  Required files missing (SKIP)

Usage:
    python scripts/check_escrow_idem_coverage.py [--root PATH] [--since YYYY-MM-DD]

--since YYYY-MM-DD:
    Restrict coverage checking to events on or after the given date.
    Direction 1: only enforce for escrow_create events with created_at/timestamp
      >= since.  Events with no parseable timestamp are skipped (treated as
      pre-date, unknown-history entries).
    Direction 2: only check escrow_create_* idem keys whose registered value
      (timestamp string) is >= since.  Keys with no parseable timestamp are
      included regardless — they cannot be confirmed as pre-date.
    Limitation: idem_keys.json stores one timestamp per key (the registration
      time).  If keys are stored without a timestamp value (non-string or
      empty), the direction-2 date filter cannot be applied and all such keys
      are checked unconditionally.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

_ESCROW_CREATE_PREFIX = "escrow_create_"
_ISSUE_RE = re.compile(r"^escrow_create_(\d+)_")


def _parse_date(s: str) -> date | None:
    """Extract a date from the first 10 characters of an ISO timestamp string.

    Returns None if *s* is empty, None, or the first 10 chars are not a valid
    YYYY-MM-DD date.
    """
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Loader helpers (injectable for tests)
# ---------------------------------------------------------------------------


def load_idem_keys(path: Path) -> dict[str, object]:
    """Return merged dict of all idem keys (nested 'keys' + top-level).

    Returns {} if the file does not exist.
    Exits 2 on parse or IO error.
    """
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        print(f"ERROR: idem_keys.json corrupted: {exc}", file=sys.stderr)
        sys.exit(2)
    except OSError as exc:
        print(f"ERROR: cannot read idem_keys.json: {exc}", file=sys.stderr)
        sys.exit(2)

    if not isinstance(data, dict):
        return {}

    merged: dict[str, object] = {}

    # Primary: nested keys object
    nested = data.get("keys", {})
    if isinstance(nested, dict):
        merged.update(nested)

    # Secondary: top-level entries (don't overwrite nested values)
    for k, v in data.items():
        if k not in ("keys", "version"):
            merged.setdefault(k, v)

    return merged


def load_history_events(history_dir: Path) -> list[dict]:
    """Load all events from history/*.jsonl, sorted by filename."""
    events: list[dict] = []
    if not history_dir.is_dir():
        return events
    for jsonl_file in sorted(history_dir.glob("*.jsonl")):
        try:
            text = jsonl_file.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                events.append(obj)
    return events


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------


def _issue_from_key(key: str) -> str | None:
    """Extract issue number string from 'escrow_create_<issue>_*' key."""
    m = _ISSUE_RE.match(key)
    return m.group(1) if m else None


def run_coverage_check(
    all_idem_keys: dict[str, object],
    events: list[dict],
    *,
    since: date | None = None,
) -> tuple[list[dict], list[dict]]:
    """Return (missing_idem_keys, orphaned_idem_keys).

    missing_idem_keys — escrow_create events with an `idem_key` field
        whose value starts with `escrow_create_` AND the key is absent
        from idem_keys.json AND the escrow has NOT been returned.

    orphaned_idem_keys — `escrow_create_*` entries in idem_keys.json
        for which no escrow_create history event exists for the same issue.

    Parameters
    ----------
    since:
        When provided, only enforce coverage for events / keys on or after
        this date.  The lookup structures (returned_issues,
        history_escrow_issues) are always built from the full event stream so
        that return-exemption logic and direction-2 lookups remain correct
        regardless of the date filter.
    """

    # --- Build lookup structures from ALL history (unfiltered) ---
    # returned_issues must cover all returns so direction-1 can exempt them.
    # history_escrow_issues must cover all creates so direction-2 can find
    # backing events for any idem key, even those registered before --since.

    # Set of escrow_create_ idem_key values seen in history events
    history_idem_values: set[str] = set()
    # Set of issue numbers that appear in escrow_create history events
    history_escrow_issues: set[str] = set()
    # Set of issue numbers that have been returned (escrow_return or
    # escrow_return_bulk)
    returned_issues: set[str] = set()

    for event in events:
        etype = event.get("type", "")

        if etype == "escrow_create":
            issue = str(event.get("issue", ""))
            if issue:
                history_escrow_issues.add(issue)
            idem = event.get("idem_key", "")
            if isinstance(idem, str) and idem.startswith(_ESCROW_CREATE_PREFIX):
                history_idem_values.add(idem)

        elif etype == "escrow_return":
            issue = str(event.get("issue", ""))
            if issue:
                returned_issues.add(issue)

        elif etype == "escrow_return_bulk":
            for n in event.get("issues", []):
                returned_issues.add(str(n))

    # --- Direction 1: history → idem_keys ---
    # For each escrow_create event with an explicit escrow_create_ idem_key:
    # that key must be registered in idem_keys.json, UNLESS the escrow was
    # already returned (resolved historical artifact, no active risk).
    #
    # --since filter: only enforce for events whose created_at / timestamp is
    # on or after the since date.  Events with no parseable timestamp are
    # skipped when --since is active (treated as unknown-age historical data).
    missing_idem_keys: list[dict] = []

    for event in events:
        if event.get("type") != "escrow_create":
            continue
        if since is not None:
            ts = event.get("created_at") or event.get("timestamp") or ""
            event_date = _parse_date(ts)
            if event_date is None or event_date < since:
                continue
        idem = event.get("idem_key", "")
        if not isinstance(idem, str) or not idem.startswith(_ESCROW_CREATE_PREFIX):
            # No escrow_create_-style idem_key on this event; skip.
            continue
        if idem in all_idem_keys:
            # Key is registered — clean.
            continue
        issue = str(event.get("issue", ""))
        if issue in returned_issues:
            # Escrow was returned: missing key is a resolved historical
            # artifact (no active deduplication risk).
            continue
        missing_idem_keys.append({
            "idem_key": idem,
            "issue": issue,
            "event_created_at": event.get("created_at") or event.get("timestamp") or "",
            "detail": (
                f"escrow_create event for issue {issue} has idem_key={idem!r} "
                f"but that key is absent from idem_keys.json and escrow is active"
            ),
        })

    # --- Direction 2: idem_keys → history ---
    # Every escrow_create_<issue>_* key in idem_keys.json must have a
    # corresponding escrow_create history event for the same issue.
    #
    # --since filter: only enforce for keys whose registered value (the
    # timestamp string stored as the key's value) is on or after the since
    # date.  Keys with a non-string or non-parseable value cannot be date-
    # filtered and are always checked (see module docstring for limitation).
    orphaned_idem_keys: list[dict] = []

    for key in all_idem_keys:
        if not key.startswith(_ESCROW_CREATE_PREFIX):
            continue
        issue = _issue_from_key(key)
        if issue is None:
            continue
        if since is not None:
            key_val = all_idem_keys[key]
            if isinstance(key_val, str) and key_val:
                key_date = _parse_date(key_val)
                if key_date is not None and key_date < since:
                    continue
            # Key with non-string / empty value: cannot filter by date;
            # include it in the check unconditionally.
        if issue not in history_escrow_issues:
            orphaned_idem_keys.append({
                "idem_key": key,
                "issue": issue,
                "detail": (
                    f"idem_key {key!r} has no matching escrow_create "
                    f"history event for issue {issue}"
                ),
            })

    return missing_idem_keys, orphaned_idem_keys


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Cross-validate escrow_create history events vs idem_keys.json"
    )
    p.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Repo root (default: two levels up from this script)",
    )
    p.add_argument(
        "--since",
        default=None,
        metavar="YYYY-MM-DD",
        help=(
            "Only enforce coverage for escrow_create events / idem keys on or "
            "after this date (ISO format).  Entries before this date are "
            "skipped (incremental CI mode).  Omit to check all history."
        ),
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = (args.root or Path(__file__).resolve().parent.parent).resolve()

    since: date | None = None
    if args.since is not None:
        try:
            since = date.fromisoformat(args.since)
        except ValueError:
            print(
                f"ERROR: --since value '{args.since}' is not a valid YYYY-MM-DD date.",
                file=sys.stderr,
            )
            return 1

    idem_path = repo_root / "ledger" / "idem_keys.json"
    history_dir = repo_root / "ledger" / "history"

    if not idem_path.exists():
        print(f"SKIP: idem_keys.json not found at {idem_path}", file=sys.stderr)
        return 2

    if not history_dir.is_dir():
        print(f"SKIP: history directory not found at {history_dir}", file=sys.stderr)
        return 2

    all_idem_keys = load_idem_keys(idem_path)
    events = load_history_events(history_dir)

    missing, orphaned = run_coverage_check(all_idem_keys, events, since=since)

    status = "FAIL" if (missing or orphaned) else "PASS"

    # Count only the events / keys actually checked under the active filter.
    n_checked = sum(
        1 for e in events
        if e.get("type") == "escrow_create"
        and isinstance(e.get("idem_key", ""), str)
        and e.get("idem_key", "").startswith(_ESCROW_CREATE_PREFIX)
        and (
            since is None
            or (
                _parse_date(e.get("created_at") or e.get("timestamp") or "")
                is not None
                and _parse_date(e.get("created_at") or e.get("timestamp") or "")
                >= since
            )
        )
    )
    n_idem_keys = sum(
        1 for k in all_idem_keys
        if k.startswith(_ESCROW_CREATE_PREFIX)
        and (
            since is None
            or not (
                isinstance(all_idem_keys[k], str)
                and all_idem_keys[k]
                and _parse_date(all_idem_keys[k]) is not None
                and _parse_date(all_idem_keys[k]) < since
            )
        )
    )

    since_clause = f" (since {since})" if since else ""
    report = {
        "status": status,
        "missing_idem_keys": missing,
        "orphaned_idem_keys": orphaned,
        "summary": (
            f"checked{since_clause} {n_checked} escrow_create events with "
            f"escrow_create_ idem keys and {n_idem_keys} idem_keys.json entries — "
            f"{len(missing)} missing (active), {len(orphaned)} orphaned"
        ),
    }

    print(json.dumps(report, indent=2))
    return 1 if status == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
