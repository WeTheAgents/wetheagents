#!/usr/bin/env python3
"""
Report task-index drift for Circle-1 temperature sweeps.

In this repo snapshot, task state is tracked via GitHub issues and escrow/payout
events live in `ledger/idem_keys.json`. Some environments also maintain a local
`ledger/task_index.json` cache of issue statuses.

This script is schema-aware:
- If `ledger/task_index.json` is missing, it reports `skipped=true` and exits 0.
- If present, it reports:
  - `open_no_active_escrow`: tasks marked open with <=0 remaining escrow
  - `open_has_payment_events`: tasks marked open with any payment events

Exit codes:
- 0: OK (no drift, or skipped)
- 1: FAIL (drift present)
- 2: usage/config/file error
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, List, Tuple


def _repo_root(default_root: str | None) -> str:
    if default_root:
        return default_root
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _escrow_and_payment_by_issue(idem: Dict[str, Any]) -> Tuple[Dict[str, int], Dict[str, int]]:
    keys = idem.get("keys", {})
    remaining: Dict[str, int] = {}
    payments: Dict[str, int] = {}
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
            remaining[issue_str] = remaining.get(issue_str, 0) + amount_i
        elif action == "payment":
            remaining[issue_str] = remaining.get(issue_str, 0) - amount_i
            payments[issue_str] = payments.get(issue_str, 0) + amount_i
        elif action == "escrow_return":
            remaining[issue_str] = remaining.get(issue_str, 0) - amount_i
    return remaining, payments


def main() -> int:
    parser = argparse.ArgumentParser(description="Report task_index drift vs escrow/payment events.")
    parser.add_argument("--root", default=None, help="Repo root (defaults to scripts/..)")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    parser.add_argument("--limit", type=int, default=20, help="Max issues listed per drift class.")
    args = parser.parse_args()

    root = _repo_root(args.root)
    task_index_path = os.path.join(root, "ledger", "task_index.json")
    idem_path = os.path.join(root, "ledger", "idem_keys.json")

    if not os.path.exists(task_index_path):
        payload = {"ok": True, "skipped": True, "reason": "ledger/task_index.json not present in this repo schema"}
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print("SKIP: ledger/task_index.json not present; drift report unavailable.")
        return 0

    if not os.path.exists(idem_path):
        payload = {"ok": False, "error": f"Missing {idem_path}"}
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(payload["error"])
        return 2

    task_index = _load_json(task_index_path)
    idem = _load_json(idem_path)
    remaining, payments = _escrow_and_payment_by_issue(idem)

    tasks = task_index.get("tasks", {})
    open_no_active_escrow: List[int] = []
    open_has_payment_events: List[int] = []

    for issue_str, task in tasks.items():
        if not isinstance(task, dict):
            continue
        if task.get("status") != "open":
            continue
        rem = remaining.get(str(issue_str), 0)
        if rem <= 0:
            if str(issue_str).isdigit():
                open_no_active_escrow.append(int(issue_str))
        if payments.get(str(issue_str), 0) > 0:
            if str(issue_str).isdigit():
                open_has_payment_events.append(int(issue_str))

    open_no_active_escrow = open_no_active_escrow[: args.limit]
    open_has_payment_events = open_has_payment_events[: args.limit]

    drift_counts = {
        "open_no_active_escrow": len(open_no_active_escrow),
        "open_has_payment_events": len(open_has_payment_events),
    }
    ok = all(v == 0 for v in drift_counts.values())

    payload = {
        "ok": ok,
        "skipped": False,
        "drift_counts": drift_counts,
        "examples": {
            "open_no_active_escrow": open_no_active_escrow,
            "open_has_payment_events": open_has_payment_events,
        },
    }

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

