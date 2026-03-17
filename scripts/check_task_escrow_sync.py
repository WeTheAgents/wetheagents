#!/usr/bin/env python3
"""Task-escrow synchronization checks.

Validates that task_index.json and escrows.json are consistent:
- Every open task has an active escrow.
- Every active escrow has a task_index entry.
- No escrow amount exceeds its task reward.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _repo_root_from(root: str | None) -> Path:
    if root:
        return Path(root).resolve()
    return Path(__file__).resolve().parent.parent


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def check_open_tasks_have_escrow(
    tasks: dict[str, Any],
    escrows: dict[str, Any],
) -> list[str]:
    """Every task with status 'open' must have a corresponding active escrow."""
    active = escrows.get("active", {})
    failures: list[str] = []
    for issue, task in sorted(tasks.get("tasks", {}).items(), key=lambda kv: int(kv[0])):
        if str(task.get("status", "")).strip() != "open":
            continue
        if issue not in active:
            failures.append(f"task #{issue} is open but has no active escrow")
    return failures


def check_escrows_have_task(
    tasks: dict[str, Any],
    escrows: dict[str, Any],
) -> list[str]:
    """Every active escrow must have a corresponding task_index entry."""
    all_tasks = tasks.get("tasks", {})
    failures: list[str] = []
    for issue in sorted(escrows.get("active", {}), key=lambda v: int(v)):
        if issue not in all_tasks:
            failures.append(f"escrow #{issue} has no entry in task_index.json")
    return failures


def check_escrow_not_exceeds_reward(
    tasks: dict[str, Any],
    escrows: dict[str, Any],
) -> list[str]:
    """No escrow amount should exceed its task reward."""
    all_tasks = tasks.get("tasks", {})
    active = escrows.get("active", {})
    failures: list[str] = []
    for issue in sorted(set(all_tasks) & set(active), key=lambda v: int(v)):
        escrow_amount = active[issue].get("amount", 0)
        task_reward = all_tasks[issue].get("reward", 0)
        if escrow_amount > task_reward:
            failures.append(
                f"escrow #{issue} amount {escrow_amount} exceeds task reward {task_reward}"
            )
    return failures


def run_checks(root: Path) -> list[tuple[str, list[str]]]:
    tasks = _load_json(root / "ledger" / "task_index.json", {"tasks": {}})
    escrows = _load_json(root / "ledger" / "escrows.json", {"active": {}})

    return [
        ("Every open task has an active escrow", check_open_tasks_have_escrow(tasks, escrows)),
        ("Every active escrow has a task_index entry", check_escrows_have_task(tasks, escrows)),
        ("No escrow amount exceeds task reward", check_escrow_not_exceeds_reward(tasks, escrows)),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Task-escrow synchronization checks"
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Path to repository root (default: auto-detect from script location)",
    )
    args = parser.parse_args()

    root = _repo_root_from(args.root)
    failed = False
    for title, problems in run_checks(root):
        if problems:
            failed = True
            print(f"FAIL: {title}")
            for problem in problems:
                print(f"  - {problem}")
        else:
            print(f"PASS: {title}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
