#!/usr/bin/env python3
"""
Task/Escrow sync checker (schema-compatible).

This repository's ledger schema does not (yet) include `ledger/task_index.json`
or `ledger/escrows.json`. Escrow state is tracked via idempotency keys in
`ledger/idem_keys.json`.

This script provides a minimal integrity check that is still useful for
Circle-1 "temperature" sweeps:
- Compute remaining escrow per issue: sum(escrow) - sum(payment, escrow_return)
- Flag issues that have negative remaining escrow (overpaid / double-return)

Exit codes:
- 0: OK (no negative remaining escrow)
- 1: FAIL (at least one issue negative)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, Tuple


def _repo_root(default_root: str | None) -> str:
    if default_root:
        return default_root
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _compute_remaining_by_issue(idem: Dict[str, Any]) -> Tuple[Dict[str, int], Dict[str, int], Dict[str, int]]:
    keys = idem.get("keys", {})
    escrowed: Dict[str, int] = {}
    paid: Dict[str, int] = {}
    returned: Dict[str, int] = {}

    for _, data in keys.items():
        if not isinstance(data, dict):
            continue
        action = data.get("action")
        issue = data.get("issue")
        amount = data.get("amount", 0)

        if issue is None:
            continue
        issue_str = str(issue)

        if not isinstance(amount, int):
            try:
                amount = int(amount)
            except Exception:
                continue

        if action == "escrow":
            escrowed[issue_str] = escrowed.get(issue_str, 0) + amount
        elif action == "payment":
            paid[issue_str] = paid.get(issue_str, 0) + amount
        elif action == "escrow_return":
            returned[issue_str] = returned.get(issue_str, 0) + amount

    remaining: Dict[str, int] = {}
    for issue in set(escrowed) | set(paid) | set(returned):
        remaining[issue] = escrowed.get(issue, 0) - paid.get(issue, 0) - returned.get(issue, 0)
    return remaining, paid, returned


def main() -> int:
    parser = argparse.ArgumentParser(description="Check internal escrow remaining per issue from idem_keys.json.")
    parser.add_argument("--root", default=None, help="Repo root (defaults to scripts/..)")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON to stdout.")
    args = parser.parse_args()

    root = _repo_root(args.root)
    idem_path = os.path.join(root, "ledger", "idem_keys.json")

    if not os.path.exists(idem_path):
        msg = f"Missing {idem_path}"
        if args.json:
            print(json.dumps({"ok": False, "error": msg}, indent=2))
        else:
            print(msg)
        return 2

    idem = _load_json(idem_path)
    remaining, paid, returned = _compute_remaining_by_issue(idem)

    negative = {issue: rem for issue, rem in remaining.items() if rem < 0}
    ok = len(negative) == 0

    if args.json:
        print(
            json.dumps(
                {
                    "ok": ok,
                    "schema": "idem_keys_escrow",
                    "issues_total": len(remaining),
                    "issues_negative_remaining": len(negative),
                    "negative_remaining_by_issue": negative,
                    "paid_by_issue": paid,
                    "returned_by_issue": returned,
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        if ok:
            print("OK: no issues have negative remaining escrow.")
        else:
            print("FAIL: some issues have negative remaining escrow:")
            for issue, rem in sorted(negative.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else kv[0]):
                print(f"  - issue #{issue}: remaining={rem}")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

