#!/usr/bin/env python3
"""task_index.json consistency checks: payment history, escrows, claims, accepted agents."""

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
    """Return (payments_by_issue, events_by_issue) from flattened history."""
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


def check_paid_tasks_have_payment_events(
    task_index: dict[str, Any],
    payments_by_issue: dict[int, set[str]],
) -> list[str]:
    """For each task with status=paid, at least one payment event must exist in history."""
    failures: list[str] = []
    for issue_str, task in task_index.get("tasks", {}).items():
        if task.get("status") != "paid":
            continue
        if not payments_by_issue.get(int(issue_str)):
            failures.append(
                f"task #{issue_str} status=paid but no payment event in history"
            )
    return failures


def check_open_tasks_escrow_amount(
    task_index: dict[str, Any],
    escrows: dict[str, Any],
) -> list[str]:
    """For open tasks with an active escrow, verify the escrow amount is consistent."""
    failures: list[str] = []
    active = escrows.get("active", {})
    for issue_str, task in task_index.get("tasks", {}).items():
        if task.get("status") != "open":
            continue
        escrow = active.get(issue_str)
        if escrow is None:
            continue  # no escrow for this open task — nothing to check

        amount = escrow.get("amount", 0)
        if not isinstance(amount, (int, float)) or amount <= 0:
            failures.append(
                f"task #{issue_str} status=open but escrow amount={amount!r} is not positive"
            )

        reward = task.get("reward")
        if reward is None:
            continue

        esc_type = escrow.get("type", "")
        if esc_type == "every_good":
            per = escrow.get("per_acceptance")
            if per is not None and (
                not isinstance(per, (int, float))
                or isinstance(per, bool)
                or per <= 0
                or per > reward
            ):
                failures.append(
                    f"task #{issue_str} every_good escrow per_acceptance={per} is not within task reward={reward}"
                )
            if amount > reward:
                failures.append(
                    f"task #{issue_str} every_good escrow amount={amount} exceeds task reward={reward}"
                )
        else:
            if amount != reward:
                failures.append(
                    f"task #{issue_str} escrow amount={amount} != task reward={reward}"
                )
    return failures


def check_claimed_tasks_have_evidence(
    task_index: dict[str, Any],
    escrows: dict[str, Any],
    events_by_issue: dict[int, list[dict[str, Any]]],
) -> list[str]:
    """For claimed tasks, verify a claim event exists in history or an escrow entry exists."""
    failures: list[str] = []
    active = escrows.get("active", {})
    for issue_str, task in task_index.get("tasks", {}).items():
        if task.get("status") != "claimed":
            continue
        issue = int(issue_str)
        has_claim = any(
            e.get("type") == "claim" for e in events_by_issue.get(issue, [])
        )
        has_escrow = issue_str in active
        if not has_claim and not has_escrow:
            failures.append(
                f"task #{issue_str} status=claimed but no claim event in history and no active escrow"
            )
    return failures


def check_accepted_agents_have_payments(
    task_index: dict[str, Any],
    payments_by_issue: dict[int, set[str]],
) -> list[str]:
    """For tasks with non-empty accepted_agents, each agent must have a payment event."""
    failures: list[str] = []
    for issue_str, task in task_index.get("tasks", {}).items():
        accepted: list[str] = task.get("accepted_agents") or []
        if not accepted:
            continue
        issue = int(issue_str)
        payers = payments_by_issue.get(issue, set())
        for agent in accepted:
            if agent not in payers:
                failures.append(
                    f"task #{issue_str} accepted_agent={agent!r} has no payment event in history"
                )
    return failures


def check_no_stale_escrows(
    task_index: dict[str, Any],
    escrows: dict[str, Any],
) -> list[str]:
    """Tasks with status=paid or status=cancelled must not have active escrow entries."""
    failures: list[str] = []
    active = escrows.get("active", {})
    for issue_str in active:
        task = task_index.get("tasks", {}).get(issue_str)
        if task is None:
            continue
        status = task.get("status")
        if status in ("paid", "cancelled"):
            failures.append(
                f"task #{issue_str} status={status} but still has an active escrow entry"
            )
    return failures


def run_checks(root: Path) -> list[tuple[str, list[str]]]:
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

    return [
        (
            "Paid tasks have at least one payment event in history",
            check_paid_tasks_have_payment_events(task_index, payments_by_issue),
        ),
        (
            "Open tasks with active escrow have consistent amount",
            check_open_tasks_escrow_amount(task_index, escrows),
        ),
        (
            "Claimed tasks have a claim event or escrow entry",
            check_claimed_tasks_have_evidence(task_index, escrows, events_by_issue),
        ),
        (
            "Accepted agents all have payment events in history",
            check_accepted_agents_have_payments(task_index, payments_by_issue),
        ),
        (
            "No stale escrows for paid or cancelled tasks",
            check_no_stale_escrows(task_index, escrows),
        ),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="task_index.json consistency checks against escrows and history"
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root (default: auto-detect from script location)",
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
