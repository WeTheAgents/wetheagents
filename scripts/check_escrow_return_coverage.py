#!/usr/bin/env python3
"""Verify every `trajectory_mint` issue has a matching `escrow_return` event."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable


def _repo_root(root: str | None) -> Path:
    if root:
        return Path(root).resolve()
    return Path(__file__).resolve().parent.parent


def _normalise_issue(value: Any) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return str(int(text))
        except ValueError:
            return None
    return None


def _iter_json_values(raw: str) -> Iterable[dict[str, Any]]:
    """Yield JSON objects, tolerating concatenated objects on one line."""
    if not raw.strip():
        return
    decoder = json.JSONDecoder()
    pos = 0
    text = raw.strip()
    n = len(text)
    while pos < n:
        while pos < n and text[pos].isspace():
            pos += 1
        if pos >= n:
            break
        try:
            obj, consumed = decoder.raw_decode(text, pos)
        except json.JSONDecodeError:
            break
        if isinstance(obj, dict):
            yield obj
        pos = consumed


def load_history_events(history_dir: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if not history_dir.is_dir():
        return events
    for path in sorted(history_dir.glob("*.jsonl")):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            events.extend(_iter_json_values(line))
    return events


def _event_type(event: dict[str, Any]) -> str:
    # History entries use "type", "event", or "op" depending on the writer era.
    return event.get("type") or event.get("event") or event.get("op") or ""


def _collect_coverage(events: list[dict[str, Any]]) -> tuple[set[str], set[str], set[str]]:
    minted: set[str] = set()
    escrowed: set[str] = set()
    returned: set[str] = set()
    for event in events:
        issue = _normalise_issue(event.get("issue"))
        if issue is None:
            continue
        etype = _event_type(event)
        if etype == "trajectory_mint":
            minted.add(issue)
        elif etype == "escrow_create":
            escrowed.add(issue)
        elif etype == "escrow_return":
            returned.add(issue)
    return minted, escrowed, returned


def _load_active_escrows(path: Path) -> dict[str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    active = data.get("active", {})
    return active if isinstance(active, dict) else {}


def _sorted_issues(values: set[str]) -> list[str]:
    return sorted(values, key=lambda value: int(value))


def run_check(
    root: Path,
    *,
    events: list[dict[str, Any]] | None = None,
    active_escrows: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    history_dir = root / "ledger" / "history"
    escrows_path = root / "ledger" / "escrows.json"

    if events is None:
        events = load_history_events(history_dir)

    minted_issues, escrowed_issues, returned_issues = _collect_coverage(events)
    # Only minted issues that also have an escrow_create are subject to return checks.
    # Pre-escrow-era mints (no escrow_create in history) are exempt.
    escrowed_mints = minted_issues & escrowed_issues
    with_return = sorted(minted_issues & returned_issues, key=lambda value: int(value))
    missing_return = sorted(escrowed_mints - returned_issues, key=lambda value: int(value))

    if active_escrows is None:
        if escrows_path.exists():
            active_escrows = _load_active_escrows(escrows_path)
        else:
            active_escrows = {}

    live_orphans: list[dict[str, Any]] = []
    for raw_issue, payload in active_escrows.items():
        issue = _normalise_issue(raw_issue)
        if issue is None or issue not in missing_return:
            continue
        if not isinstance(payload, dict):
            payload = {}
        live_orphans.append({
            "issue": issue,
            "amount": payload.get("amount", 0),
            "author": payload.get("author", ""),
            "state": "active",
        })

    live_orphans = sorted(live_orphans, key=lambda item: int(item["issue"]))

    status = "PASS" if not missing_return else "FAIL"

    return {
        "status": status,
        "minted_total": len(minted_issues),
        "with_return": with_return,
        "missing_return": missing_return,
        "live_orphans": live_orphans,
        "summary": (
            f"minted_total={len(minted_issues)} "
            f"with_return={len(with_return)} "
            f"missing_return={len(missing_return)} "
            f"live_orphans={len(live_orphans)}"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify minted gauntlet issues have matching escrow_return events"
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root (default: auto-detected)",
    )
    args = parser.parse_args(argv)

    result = run_check(_repo_root(args.root))
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
