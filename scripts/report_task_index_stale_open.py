#!/usr/bin/env python3
"""
Report `ledger/task_index.json` tasks that are marked `status=open` but have no
corresponding active escrow in `ledger/escrows.json`.

This is an ops triage helper: it does not mutate the ledger.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class StaleOpenTask:
    task_id: int
    title: str
    has_active_escrow: bool


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _active_escrow_issue_ids(escrows: dict[str, Any]) -> set[str]:
    """Return issue ids that currently have an active escrow.

    Current schema: `ledger/escrows.json` contains `{ "active": { "<issue>": {...} } }`.
    Older legacy formats used a list under `escrows`.
    """
    active = escrows.get("active")
    if isinstance(active, dict):
        return {str(k) for k in active.keys()}

    legacy = escrows.get("escrows")
    if isinstance(legacy, list):
        out: set[str] = set()
        for entry in legacy:
            if not isinstance(entry, dict):
                continue
            if entry.get("status") != "active":
                continue
            issue = entry.get("issue")
            if issue is None:
                continue
            out.add(str(issue))
        return out

    return set()


def _iter_stale_open_tasks(
    task_index: dict[str, Any], active_escrow_issue_ids: set[str]
) -> Iterable[StaleOpenTask]:
    tasks: dict[str, Any] = task_index.get("tasks", {})
    for task_id_str, task in tasks.items():
        if task.get("status") != "open":
            continue
        has_active_escrow = task_id_str in active_escrow_issue_ids
        if has_active_escrow:
            continue
        yield StaleOpenTask(
            task_id=int(task_id_str),
            title=str(task.get("title") or ""),
            has_active_escrow=has_active_escrow,
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".", help="Repository root (default: .)")
    parser.add_argument("--limit", type=int, default=200, help="Max rows to print (default: 200)")
    parser.add_argument(
        "--fail",
        action="store_true",
        help="Exit non-zero when stale-open tasks exist (default: false)",
    )
    args = parser.parse_args()

    # Windows consoles (and some CI environments) can have a non-UTF8 default
    # stdout encoding. Replace unencodable characters to keep the report usable.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    repo_root = Path(args.root)
    task_index_path = repo_root / "ledger" / "task_index.json"
    escrows_path = repo_root / "ledger" / "escrows.json"

    task_index = _load_json(task_index_path)
    escrows = _load_json(escrows_path)

    active_escrow_issue_ids = _active_escrow_issue_ids(escrows)

    stale = sorted(
        _iter_stale_open_tasks(task_index, active_escrow_issue_ids),
        key=lambda t: t.task_id,
    )

    print(f"active_escrows={len(active_escrow_issue_ids)}")
    print(f"stale_open_tasks={len(stale)}")
    if not stale:
        return 0

    print("")
    for row in stale[: max(0, args.limit)]:
        title_part = f" title={row.title}" if row.title else ""
        print(f"- #{row.task_id}{title_part}")

    if args.limit < len(stale):
        print(f"\n(truncated: printed {args.limit} of {len(stale)})")

    return 1 if args.fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
