#!/usr/bin/env python3
"""
Report stale-open tasks from `ledger/task_index.json`.

This repository snapshot does not use `ledger/task_index.json` yet. The Circle-1
director sweep expects this script to exist, so we provide a schema-aware
implementation that:
- Exits 0 when `ledger/task_index.json` is absent (explicitly "skipped").
- When present, reports tasks with `status=open` that lack any remaining escrow.

Exit codes:
- 0: OK (no stale-open tasks, or skipped due to missing task_index)
- 1: FAIL (stale-open tasks found and --fail passed)
- 2: usage/config/file error
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Tuple


def _repo_root(default_root: str | None) -> str:
    if default_root:
        return default_root
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _remaining_escrow_by_issue(idem: Dict[str, Any]) -> Dict[str, int]:
    keys = idem.get("keys", {})
    escrows: Dict[str, int] = {}
    for _, data in keys.items():
        if not isinstance(data, dict):
            continue
        action = data.get("action")
        issue = data.get("issue")
        amount = data.get("amount", 0)
        if issue is None:
            continue
        issue_str = str(issue)
        try:
            amount_i = int(amount)
        except Exception:
            continue
        if action == "escrow":
            escrows[issue_str] = escrows.get(issue_str, 0) + amount_i
        elif action in ("payment", "escrow_return"):
            escrows[issue_str] = escrows.get(issue_str, 0) - amount_i
    return escrows


def _find_stale_open(task_index: Dict[str, Any], remaining_escrow: Dict[str, int], limit: int) -> List[Dict[str, Any]]:
    tasks = task_index.get("tasks", {})
    stale: List[Dict[str, Any]] = []
    for issue, task in tasks.items():
        if not isinstance(task, dict):
            continue
        if task.get("status") != "open":
            continue
        rem = remaining_escrow.get(str(issue), 0)
        if rem <= 0:
            stale.append({"issue": int(issue) if str(issue).isdigit() else issue, "remaining_escrow": rem, "task": task})
        if len(stale) >= limit:
            break
    return stale


def main() -> int:
    parser = argparse.ArgumentParser(description="Report tasks with status=open but no remaining escrow.")
    parser.add_argument("--root", default=None, help="Repo root (defaults to scripts/..)")
    parser.add_argument("--fail", action="store_true", help="Exit non-zero if stale-open tasks are found.")
    parser.add_argument("--limit", type=int, default=20, help="Max number of tasks to print/report.")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args()

    root = _repo_root(args.root)
    task_index_path = os.path.join(root, "ledger", "task_index.json")
    idem_path = os.path.join(root, "ledger", "idem_keys.json")

    if not os.path.exists(task_index_path):
        payload = {"ok": True, "skipped": True, "reason": "ledger/task_index.json not present in this repo schema"}
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print("SKIP: ledger/task_index.json not present; no stale-open report available.")
        return 0

    if not os.path.exists(idem_path):
        msg = f"Missing {idem_path}"
        if args.json:
            print(json.dumps({"ok": False, "error": msg}, indent=2))
        else:
            print(msg)
        return 2

    task_index = _load_json(task_index_path)
    idem = _load_json(idem_path)
    remaining = _remaining_escrow_by_issue(idem)

    stale = _find_stale_open(task_index, remaining, args.limit)
    ok = len(stale) == 0

    if args.json:
        print(json.dumps({"ok": ok, "skipped": False, "count": len(stale), "tasks": stale}, indent=2, sort_keys=True))
    else:
        if ok:
            print("OK: no stale-open tasks found.")
        else:
            print(f"STALE-OPEN ({len(stale)} shown, limit={args.limit}):")
            for item in stale:
                print(f"  - issue #{item['issue']}: remaining_escrow={item['remaining_escrow']}")

    if ok:
        return 0
    return 1 if args.fail else 0


if __name__ == "__main__":
    raise SystemExit(main())

