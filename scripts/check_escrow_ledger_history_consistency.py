#!/usr/bin/env python3
"""Check active escrows are consistent with ledger history events."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _repo_root(root: str | None) -> Path:
    if root:
        return Path(root).resolve()
    return Path(__file__).resolve().parent.parent


def _load_json(path: Path, *, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _normalize_issue(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return None
    if isinstance(value, str):
        stripped = value.strip().lstrip("#")
        if stripped.isdigit():
            return stripped
    return None


def _event_kind(event: dict[str, Any]) -> str | None:
    for key in ("event", "op", "type"):
        kind = event.get(key)
        if isinstance(kind, str):
            return kind.strip().lower()
    return None


def _issue_sort_key(issue: str) -> tuple[int, str]:
    try:
        return (int(issue), issue)
    except ValueError:
        return (10**12, issue)


def _load_active_issues(escrows: dict[str, Any]) -> list[str]:
    active = escrows.get("active", {})
    if not isinstance(active, dict):
        return []

    issues: set[str] = set()
    for raw_issue in active.keys():
        issue = _normalize_issue(raw_issue)
        if issue is not None:
            issues.add(issue)
    return sorted(issues, key=_issue_sort_key)


def _load_active_types(escrows: dict[str, Any]) -> dict[str, str]:
    active = escrows.get("active", {})
    if not isinstance(active, dict):
        return {}

    types: dict[str, str] = {}
    for raw_issue, entry in active.items():
        issue = _normalize_issue(raw_issue)
        if issue is None or not isinstance(entry, dict):
            continue
        raw_type = entry.get("type") or entry.get("reward_type") or entry.get("mechanic")
        if isinstance(raw_type, str):
            types[issue] = raw_type
    return types


def _index_history_events(history_dir: Path) -> tuple[set[str], set[str], set[str]]:
    creates: set[str] = set()
    terminal_closes: set[str] = set()
    payment_closes: set[str] = set()

    if not history_dir.is_dir():
        return creates, terminal_closes, payment_closes

    for path in sorted(history_dir.glob("*.jsonl")):
        try:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except OSError:
            continue

        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            if not isinstance(event, dict):
                continue

            issue = _normalize_issue(event.get("issue"))
            if issue is None:
                continue

            kind = _event_kind(event)
            if kind in {"escrow", "escrow_create"}:
                creates.add(issue)
            elif kind == "payment":
                payment_closes.add(issue)
            elif kind in {"accept", "reject", "escrow_return"}:
                terminal_closes.add(issue)

    return creates, terminal_closes, payment_closes


def run_check(root: Path) -> dict[str, Any]:
    escrows = _load_json(
        root / "ledger" / "escrows.json",
        default={"active": {}},
    )
    active_issues = set(_load_active_issues(escrows))
    active_types = _load_active_types(escrows)

    creates, terminal_closes, payment_closes = _index_history_events(root / "ledger" / "history")
    phantom_issues = sorted(active_issues - creates, key=_issue_sort_key)
    multi_payment_types = {"every_good", "progressive", "linear"}
    payment_zombies = {
        issue
        for issue in active_issues & payment_closes
        if active_types.get(issue) not in multi_payment_types
    }
    zombie_issues = sorted((active_issues & terminal_closes) | payment_zombies, key=_issue_sort_key)

    return {
        "status": "FAIL" if phantom_issues or zombie_issues else "PASS",
        "total_active_escrows": len(active_issues),
        "phantom_count": len(phantom_issues),
        "zombie_count": len(zombie_issues),
        "phantom_issues": phantom_issues,
        "zombie_issues": zombie_issues,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        default=None,
        help="Path to repository root (default: script directory parent).",
    )
    args = parser.parse_args(argv)

    report = run_check(_repo_root(args.root))
    print(json.dumps(report, indent=2))
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
