#!/usr/bin/env python3
"""Verify that balances.json last_updated is never stale relative to ledger history.

Rules:
- last_updated field must exist in balances.json (missing or null → FAIL)
- last_updated must be >= the maximum timestamp found in any ledger/history/*.jsonl event
- Event timestamps are read from the ts, timestamp, and event_at fields (max across all)
- If no history events exist, the check passes (no constraint to violate)

Exit code 0 if fresh; exit code 1 if stale or missing field.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _repo_root(override: str | None = None) -> Path:
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parent.parent


def _parse_utc_timestamp(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    stamp = datetime.fromisoformat(text)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def collect_history_max_ts(root: Path) -> datetime | None:
    """Scan all ledger/history/*.jsonl files and return the max event timestamp, or None."""
    history_dir = root / "ledger" / "history"
    if not history_dir.is_dir():
        return None

    max_ts: datetime | None = None
    for jsonl_path in sorted(history_dir.glob("*.jsonl")):
        try:
            text = jsonl_path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            for field in ("ts", "timestamp", "event_at"):
                raw = event.get(field)
                if not isinstance(raw, str) or not raw.strip():
                    continue
                try:
                    ts = _parse_utc_timestamp(raw)
                except ValueError:
                    continue
                if max_ts is None or ts > max_ts:
                    max_ts = ts

    return max_ts


def check_freshness(root: Path) -> dict[str, Any]:
    """Return a report dict with keys: pass, reason, last_updated, max_history_ts, delta_seconds."""
    balances_path = root / "ledger" / "balances.json"
    try:
        balances = json.loads(balances_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {
            "pass": False,
            "reason": f"missing {balances_path}",
            "last_updated": None,
            "max_history_ts": None,
            "delta_seconds": None,
        }
    except json.JSONDecodeError as exc:
        return {
            "pass": False,
            "reason": f"cannot parse balances.json: {exc}",
            "last_updated": None,
            "max_history_ts": None,
            "delta_seconds": None,
        }

    raw_last_updated = balances.get("last_updated")
    if not isinstance(raw_last_updated, str) or not raw_last_updated.strip():
        return {
            "pass": False,
            "reason": "last_updated field is missing or empty in balances.json",
            "last_updated": raw_last_updated,
            "max_history_ts": None,
            "delta_seconds": None,
        }

    try:
        last_updated_dt = _parse_utc_timestamp(raw_last_updated)
    except ValueError:
        return {
            "pass": False,
            "reason": f"last_updated is not valid ISO-8601: {raw_last_updated!r}",
            "last_updated": raw_last_updated,
            "max_history_ts": None,
            "delta_seconds": None,
        }

    max_history_ts = collect_history_max_ts(root)

    if max_history_ts is None:
        return {
            "pass": True,
            "reason": "no history events found — no constraint",
            "last_updated": raw_last_updated,
            "max_history_ts": None,
            "delta_seconds": None,
        }

    delta_seconds = (last_updated_dt - max_history_ts).total_seconds()

    if last_updated_dt >= max_history_ts:
        return {
            "pass": True,
            "reason": "last_updated is current",
            "last_updated": raw_last_updated,
            "max_history_ts": max_history_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "delta_seconds": delta_seconds,
        }

    return {
        "pass": False,
        "reason": (
            f"last_updated is {abs(delta_seconds):.1f}s behind the most recent history event"
        ),
        "last_updated": raw_last_updated,
        "max_history_ts": max_history_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "delta_seconds": delta_seconds,
    }


def print_report(report: dict[str, Any]) -> None:
    status = "PASS" if report["pass"] else "FAIL"
    print(f"Status      : {status}")
    print(f"last_updated: {report['last_updated'] or 'n/a'}")
    print(f"max_history : {report['max_history_ts'] or 'n/a'}")
    if report["delta_seconds"] is not None:
        print(f"delta       : {report['delta_seconds']:.1f}s")
    print(f"Reason      : {report['reason']}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify balances.json last_updated is not stale relative to ledger history."
    )
    parser.add_argument("--root", default=None, help="Repository root (default: auto-detect)")
    args = parser.parse_args()

    root = _repo_root(args.root)
    try:
        report = check_freshness(root)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print_report(report)
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
