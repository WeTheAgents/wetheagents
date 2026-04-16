#!/usr/bin/env python3
"""Escrow-to-task reward consistency checker.

Verifies that escrow amounts match the corresponding task reward in
ledger/task_index.json:

  1. Active escrows (ledger/escrows.json):
       - Non-progressive types: escrow.amount must equal task reward exactly.
       - Progressive/linear types: escrow.amount may be <= task reward
         (remaining budget after partial payouts).

  2. History escrow_create events (ledger/history/*.jsonl):
       - At creation time, the amount must equal the full task reward exactly.

Task reward is resolved as:
  - `reward_wea` field if present (new-format entry)
  - `reward` field as fallback (legacy entry)

Special handling:
  - Tasks not found in task_index: skipped gracefully (not a violation).
  - Tasks with no reward field: skipped gracefully.
  - Gauntlet tasks use reward = 19 + slot; that value is stored in the
    task_index `reward` / `reward_wea` field, so no special derivation is
    required at check time.

Output: JSON to stdout with fields: status, violations, skipped, summary.
Exit codes:
  0 — PASS (no violations)
  1 — FAIL (one or more violations, or fatal I/O error)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


# Types where the escrow amount can legitimately be below the full task reward
# because the budget is paid out incrementally.
_PARTIAL_ESCROW_TYPES: frozenset[str] = frozenset({"progressive", "linear"})


def _repo_root_from(root: str | None) -> Path:
    if root:
        return Path(root).resolve()
    return Path(__file__).resolve().parent.parent


def _get_task_reward(task: dict[str, Any]) -> int | None:
    """Return the task reward as an integer, or None if not present/valid."""
    for field in ("reward_wea", "reward"):
        val = task.get(field)
        if isinstance(val, int) and not isinstance(val, bool) and val > 0:
            return val
    return None


def _load_history_events(history_dir: Path) -> list[dict[str, Any]]:
    """Load all JSONL events from history_dir in filename order."""
    events: list[dict[str, Any]] = []
    if not history_dir.is_dir():
        return events
    for path in sorted(history_dir.glob("*.jsonl")):
        for raw in path.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict):
                events.append(entry)
    return events


def check_active_escrows(
    escrows: dict[str, Any],
    tasks: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Check active escrow amounts against task rewards.

    Returns:
        (violations, skipped) — each item is a dict describing the entry.
    """
    violations: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    active = escrows.get("active", {})
    for issue, escrow in sorted(active.items(), key=lambda kv: int(kv[0])):
        task = tasks.get(issue)
        if task is None:
            skipped.append({
                "source": "active",
                "issue": issue,
                "reason": "task not in task_index",
            })
            continue

        task_reward = _get_task_reward(task)
        if task_reward is None:
            skipped.append({
                "source": "active",
                "issue": issue,
                "reason": "task has no valid reward field",
            })
            continue

        escrow_amount = escrow.get("amount")
        if not isinstance(escrow_amount, int) or isinstance(escrow_amount, bool):
            skipped.append({
                "source": "active",
                "issue": issue,
                "reason": "escrow has no valid integer amount",
            })
            continue

        escrow_type = escrow.get("type", "")
        if escrow_type in _PARTIAL_ESCROW_TYPES:
            # Remaining budget may be less than full reward — only check ceiling.
            if escrow_amount > task_reward:
                violations.append({
                    "source": "active",
                    "issue": issue,
                    "escrow_amount": escrow_amount,
                    "expected_reward": task_reward,
                    "detail": (
                        f"active escrow #{issue} ({escrow_type}) amount {escrow_amount}"
                        f" exceeds task reward {task_reward}"
                    ),
                })
        else:
            if escrow_amount != task_reward:
                violations.append({
                    "source": "active",
                    "issue": issue,
                    "escrow_amount": escrow_amount,
                    "expected_reward": task_reward,
                    "detail": (
                        f"active escrow #{issue} amount {escrow_amount}"
                        f" != task reward {task_reward}"
                    ),
                })

    return violations, skipped


def check_history_escrows(
    events: list[dict[str, Any]],
    tasks: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Check history escrow_create event amounts against task rewards.

    At creation time the full task reward must have been escrowed, so an
    exact match is required (regardless of escrow type).

    Returns:
        (violations, skipped) — each item is a dict describing the entry.
    """
    violations: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for event in events:
        if event.get("type") != "escrow_create":
            continue

        issue = str(event.get("issue", "")).strip()
        if not issue:
            continue

        task = tasks.get(issue)
        if task is None:
            skipped.append({
                "source": "history",
                "issue": issue,
                "reason": "task not in task_index",
            })
            continue

        task_reward = _get_task_reward(task)
        if task_reward is None:
            skipped.append({
                "source": "history",
                "issue": issue,
                "reason": "task has no valid reward field",
            })
            continue

        event_amount = event.get("amount")
        if not isinstance(event_amount, int) or isinstance(event_amount, bool):
            skipped.append({
                "source": "history",
                "issue": issue,
                "reason": "history event has no valid integer amount",
            })
            continue

        if event_amount != task_reward:
            violations.append({
                "source": "history",
                "issue": issue,
                "escrow_amount": event_amount,
                "expected_reward": task_reward,
                "detail": (
                    f"history escrow_create #{issue} amount {event_amount}"
                    f" != task reward {task_reward}"
                ),
            })

    return violations, skipped


def run_check(
    root: Path,
    *,
    escrows: dict[str, Any] | None = None,
    tasks: dict[str, Any] | None = None,
    events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run both checks and return a result dict.

    Keyword overrides (escrows, tasks, events) are used by tests to inject
    synthetic data without touching the real ledger.
    """
    if escrows is None:
        try:
            escrows = json.loads(
                (root / "ledger" / "escrows.json").read_text(encoding="utf-8-sig")
            )
        except (OSError, json.JSONDecodeError) as exc:
            return {
                "status": "FAIL",
                "violations": [],
                "skipped": [],
                "summary": f"failed to load escrows.json: {exc}",
            }

    if tasks is None:
        try:
            data = json.loads(
                (root / "ledger" / "task_index.json").read_text(encoding="utf-8-sig")
            )
            tasks = data.get("tasks", {})
        except (OSError, json.JSONDecodeError) as exc:
            return {
                "status": "FAIL",
                "violations": [],
                "skipped": [],
                "summary": f"failed to load task_index.json: {exc}",
            }

    if events is None:
        events = _load_history_events(root / "ledger" / "history")

    active_violations, active_skipped = check_active_escrows(escrows, tasks)
    history_violations, history_skipped = check_history_escrows(events, tasks)

    all_violations = active_violations + history_violations
    all_skipped = active_skipped + history_skipped

    n = len(all_violations)
    status = "FAIL" if all_violations else "PASS"
    summary = (
        "No violations"
        if not all_violations
        else f"{n} violation{'s' if n != 1 else ''} found"
    )
    if all_skipped:
        summary += f"; {len(all_skipped)} entry/entries skipped"

    return {
        "status": status,
        "violations": all_violations,
        "skipped": all_skipped,
        "summary": summary,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Check escrow amounts match task rewards in task_index.json"
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root (default: auto-detect from script location)",
    )
    args = parser.parse_args(argv)

    result = run_check(_repo_root_from(args.root))
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
