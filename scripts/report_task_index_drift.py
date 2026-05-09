#!/usr/bin/env python3
"""Offline drift report for ledger/task_index.json.

This script is designed for Circle-1 "temperature reduction" work when GitHub
is unavailable or blocked. It compares:

- `ledger/task_index.json` (declared task state)
- `ledger/escrows.json` (active escrows only)
- `ledger/history/*.jsonl` (settlement/payment evidence)

It does **not** attempt to mutate the ledger. Instead it produces a compact
report that can be used to drive a GitHub-connected reconciliation pass.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from io_helpers import load_json  # noqa: E402


def _repo_root_from(root: str | None) -> Path:
    if root:
        return Path(root).resolve()
    return Path(__file__).resolve().parent.parent


def _iter_history(root: Path) -> list[dict[str, Any]]:
    history_dir = root / "ledger" / "history"
    if not history_dir.exists():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(history_dir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                records.append(payload)
    return records


def _build_indexes(
    history: list[dict[str, Any]],
) -> tuple[dict[int, set[str]], dict[int, list[dict[str, Any]]]]:
    payments_by_issue: dict[int, set[str]] = {}
    events_by_issue: dict[int, list[dict[str, Any]]] = {}

    for record in history:
        try:
            issue = int(record.get("issue"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue

        events_by_issue.setdefault(issue, []).append(record)
        if record.get("type") == "payment":
            agent = str(record.get("agent", "")).strip()
            if agent:
                payments_by_issue.setdefault(issue, set()).add(agent)

    return payments_by_issue, events_by_issue


def _title_for(issue: int, task_index: dict[str, Any]) -> str:
    task = task_index.get("tasks", {}).get(str(issue), {})
    title = str(task.get("title") or "").strip()
    if title:
        return title
    return "<missing title>"


def _compact_issue_list(
    issues: list[int],
    task_index: dict[str, Any],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for issue in issues[:limit]:
        out.append({"issue": issue, "title": _title_for(issue, task_index)})
    return out


def build_report(root: Path, *, limit: int) -> dict[str, Any]:
    task_index = load_json(
        root / "ledger" / "task_index.json",
        default={"tasks": {}},
        encoding="utf-8-sig",
    )
    escrows = load_json(
        root / "ledger" / "escrows.json",
        default={"active": {}},
        encoding="utf-8-sig",
    )
    history = _iter_history(root)
    payments_by_issue, events_by_issue = _build_indexes(history)

    tasks: dict[str, dict[str, Any]] = task_index.get("tasks", {}) or {}
    active_escrows: dict[str, Any] = escrows.get("active", {}) or {}

    open_tasks = [int(k) for k, v in tasks.items() if v.get("status") == "open"]
    claimed_tasks = [int(k) for k, v in tasks.items() if v.get("status") == "claimed"]
    paid_tasks = [int(k) for k, v in tasks.items() if v.get("status") == "paid"]

    open_no_escrow = sorted([i for i in open_tasks if str(i) not in active_escrows])
    claimed_no_escrow = sorted(
        [i for i in claimed_tasks if str(i) not in active_escrows]
    )

    open_with_payments = sorted([i for i in open_tasks if payments_by_issue.get(i)])
    claimed_with_payments = sorted(
        [i for i in claimed_tasks if payments_by_issue.get(i)]
    )

    paid_missing_payments = sorted([i for i in paid_tasks if not payments_by_issue.get(i)])

    issues_in_history = sorted(events_by_issue.keys())
    missing_task_index = sorted(
        [i for i in issues_in_history if str(i) not in tasks]
    )

    return {
        "active_escrows": len(active_escrows),
        "task_index": {
            "open": len(open_tasks),
            "claimed": len(claimed_tasks),
            "paid": len(paid_tasks),
        },
        "drift": {
            "open_no_active_escrow": {
                "count": len(open_no_escrow),
                "sample": _compact_issue_list(open_no_escrow, task_index, limit=limit),
            },
            "claimed_no_active_escrow": {
                "count": len(claimed_no_escrow),
                "sample": _compact_issue_list(
                    claimed_no_escrow, task_index, limit=limit
                ),
            },
            "open_has_payment_events": {
                "count": len(open_with_payments),
                "sample": _compact_issue_list(
                    open_with_payments, task_index, limit=limit
                ),
            },
            "claimed_has_payment_events": {
                "count": len(claimed_with_payments),
                "sample": _compact_issue_list(
                    claimed_with_payments, task_index, limit=limit
                ),
            },
            "paid_missing_payment_events": {
                "count": len(paid_missing_payments),
                "sample": _compact_issue_list(
                    paid_missing_payments, task_index, limit=limit
                ),
            },
            "history_issue_missing_task_index_entry": {
                "count": len(missing_task_index),
                "sample": _compact_issue_list(
                    missing_task_index, task_index, limit=limit
                ),
            },
        },
        "notes": [
            "This report is offline-only: it does not query GitHub for issue truth.",
            "Reconciliation should be driven by GitHub issue state + escrow-first rule.",
        ],
    }


def _print_human(report: dict[str, Any]) -> None:
    print(f"active_escrows={report['active_escrows']}")
    print(
        "task_index:"
        f" open={report['task_index']['open']}"
        f" claimed={report['task_index']['claimed']}"
        f" paid={report['task_index']['paid']}"
    )
    print("")
    drift = report["drift"]
    for key in [
        "open_no_active_escrow",
        "claimed_no_active_escrow",
        "open_has_payment_events",
        "claimed_has_payment_events",
        "paid_missing_payment_events",
        "history_issue_missing_task_index_entry",
    ]:
        block = drift[key]
        print(f"{key}={block['count']}")
        for row in block["sample"]:
            print(f"  - #{row['issue']} title={row['title']}")
        print("")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Offline drift report for ledger/task_index.json vs escrows/history."
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root (default: auto-detect from script location).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum sample size per drift category (default: 20).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON (otherwise prints a human report).",
    )
    args = parser.parse_args()

    root = _repo_root_from(args.root)
    report = build_report(root, limit=args.limit)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        _print_human(report)

    return 0


if __name__ == "__main__":
    sys.exit(main())

