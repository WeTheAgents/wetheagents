#!/usr/bin/env python3
"""
Task Spec Completeness Scanner.

Validates that every task in task_index.json has all required specification
fields populated, flagging spec gaps before they cause payment or dispatch
errors.

Field requirements by status tier:

  All tasks:
    - status          (required)
    - reward_type     (required — satisfied by `reward_type` OR `mechanic`)
    - budget          (required — satisfied by `budget` OR `reward`)

  Claimed / accepted tasks (additionally):
    - agent           (who claimed the task)
    - escrow_idem_key (prevents double-payment)

  Paid tasks with agent metadata (additionally):
    - accepted_at OR paid_at (at least one payment timestamp)

Note on field aliases: the current task_index schema stores reward type as
`mechanic` and budget as `reward`.  The checker accepts either the canonical
spec name or the schema alias so that both old and new task entries pass.
The paid-tier timestamp check applies only to paid tasks that carry an `agent`
field (indicating they were processed through the tracked claim flow); legacy
paid tasks without agent metadata are exempt.

Exits 0 if all tasks are complete, 1 if any gaps are found.
"""

from __future__ import annotations

import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TASK_INDEX_PATH = os.path.join(BASE_DIR, "ledger", "task_index.json")

ERRORS: list[str] = []


def err(issue: str, field: str, msg: str) -> None:
    ERRORS.append(f"  FAIL [#{issue}]: missing '{field}' — {msg}")


def _has_field(task: dict, *names: str) -> bool:
    """Return True if task has at least one of the given field names with a
    truthy value (non-None, non-empty string)."""
    for name in names:
        v = task.get(name)
        if v is not None and v != "" and v != []:
            return True
    return False


def validate_task(issue: str, task: dict) -> None:
    if not isinstance(task, dict):
        err(issue, "task", "entry is not a JSON object")
        return

    status = task.get("status", "")

    # --- Tier 1: all tasks ---
    if not _has_field(task, "status"):
        err(issue, "status", "every task must have a status")

    if not _has_field(task, "reward_type", "mechanic"):
        err(issue, "reward_type", "every task must specify a reward type (reward_type or mechanic)")

    if not _has_field(task, "budget", "reward"):
        err(issue, "budget", "every task must specify a budget (budget or reward)")

    # --- Tier 2: claimed / accepted ---
    if status in ("claimed", "accepted"):
        if not _has_field(task, "agent"):
            err(issue, "agent", "claimed/accepted task must identify the claiming agent")
        if not _has_field(task, "escrow_idem_key"):
            err(issue, "escrow_idem_key", "claimed/accepted task must have escrow_idem_key to prevent double-payment")

    # --- Tier 3: paid (only tasks tracked through the claim flow) ---
    if status == "paid" and _has_field(task, "agent"):
        if not _has_field(task, "accepted_at", "paid_at"):
            err(issue, "accepted_at/paid_at", "paid task with agent must have accepted_at or paid_at timestamp")


def main() -> None:
    print("--- Task Spec Completeness Scan ---")

    if not os.path.exists(TASK_INDEX_PATH):
        print(f"ERROR: {TASK_INDEX_PATH} not found")
        sys.exit(1)

    try:
        with open(TASK_INDEX_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"ERROR: invalid JSON in task_index.json: {e}")
        sys.exit(1)

    tasks = data.get("tasks", {})
    if not isinstance(tasks, dict):
        print("ERROR: task_index.json 'tasks' must be a JSON object")
        sys.exit(1)

    for issue, task in tasks.items():
        validate_task(str(issue), task)

    if ERRORS:
        print(f"\n{len(ERRORS)} spec gap(s) found:\n")
        for e in ERRORS:
            print(e)
        print("\nStatus: FAIL")
        sys.exit(1)
    else:
        print(f"All {len(tasks)} task(s) pass spec completeness check.")
        print("\nStatus: PASS")
        sys.exit(0)


if __name__ == "__main__":
    main()
