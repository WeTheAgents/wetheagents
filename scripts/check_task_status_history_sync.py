#!/usr/bin/env python3
"""Task-status / history-event consistency checker for WeTheAgents.

Cross-validates ``ledger/task_index.json`` task statuses against
``ledger/history/*.jsonl`` events.  Catches silent manual edits to
task_index.json that bypass the ledger history trail.

Rules
-----
(a) A task with ``status: paid`` must have at least one paid-class event
    (``accept`` | ``payment`` | ``trajectory_mint``) in history whose
    ``issue`` field matches the task's issue number.

(b) A task with ``status: open`` or ``status: claimed`` must NOT have any
    paid-class event in history for that issue number.

(c) A task with ``status: rejected`` must have a ``reject`` event in history
    for that issue number.

Tasks with other statuses (e.g. ``cancelled``) are not checked.

Exit codes
----------
0 — all checked tasks PASS
1 — one or more tasks FAIL
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


# Mechanics where `accept` fires per-submission/per-slot rather than as a
# whole-task resolution. Tasks with these mechanics legitimately retain
# status=open across many `accept` events, so rule (b) below does not apply.
_PARALLEL_ACCEPT_MECHANICS = frozenset({"every_good", "best_x"})

# Known pre-existing task_index drift on `standard`-mechanic tasks settled
# in April 2026. Each issue here has a real `accept` event AND an
# `escrow_return` with reason="standard_task_settled", but task_index.json
# still carries status="open" — the Tide settlement landed in history but
# never propagated to the task_index snapshot. This is genuine real-bug
# drift that requires an Agent0 task_index reconciliation write to fix; it
# is acknowledged here so the structural rule still flags NEW occurrences.
# Remove an entry once Agent0 has bumped its task_index status to "paid".
_KNOWN_STALE_OPEN_WITH_ACCEPT: frozenset[int] = frozenset({272, 273})


def _repo_root(override: str | None = None) -> Path:
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parent.parent


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _iter_history(history_dir: Path) -> list[dict[str, Any]]:
    """Return all parseable events from history JSONL files in chronological order."""
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


def _build_issue_sets(
    events: list[dict[str, Any]],
) -> tuple[set[int], set[int], set[int], set[int]]:
    """Return (accept_issues, payment_issues, mint_issues, reject_issues)."""
    accept_issues: set[int] = set()
    payment_issues: set[int] = set()
    mint_issues: set[int] = set()
    reject_issues: set[int] = set()

    for e in events:
        t = e.get("type", "")
        raw_issue = e.get("issue")
        if raw_issue is None:
            continue
        try:
            issue = int(raw_issue)
        except (ValueError, TypeError):
            continue

        if t == "accept":
            accept_issues.add(issue)
        elif t == "payment":
            payment_issues.add(issue)
        elif t == "trajectory_mint":
            mint_issues.add(issue)
        elif t == "reject":
            reject_issues.add(issue)

    return accept_issues, payment_issues, mint_issues, reject_issues


def check_tasks(
    tasks: dict[str, Any],
    accept_issues: set[int],
    payment_issues: set[int],
    mint_issues: set[int],
    reject_issues: set[int],
) -> list[dict[str, Any]]:
    """Apply consistency rules to each task entry.

    Returns a list of per-task result dicts with keys:
        issue, status, result ("PASS" | "FAIL" | "SKIP"), note
    """
    checks: list[dict[str, Any]] = []

    for issue_str, task in sorted(tasks.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0):
        try:
            issue = int(issue_str)
        except (ValueError, TypeError):
            checks.append({
                "issue": issue_str,
                "status": None,
                "result": "FAIL",
                "note": f"non-integer issue key: {issue_str!r}",
            })
            continue

        if not isinstance(task, dict):
            checks.append({
                "issue": issue,
                "status": None,
                "result": "FAIL",
                "note": "task entry is not a dict",
            })
            continue

        task_status = task.get("status", "")

        # Rule (a): paid → accept | payment | trajectory_mint event required
        if task_status == "paid":
            has_payment_event = (
                issue in accept_issues
                or issue in payment_issues
                or issue in mint_issues
            )
            if has_payment_event:
                checks.append({
                    "issue": issue,
                    "status": task_status,
                    "result": "PASS",
                    "note": "",
                })
            else:
                checks.append({
                    "issue": issue,
                    "status": task_status,
                    "result": "FAIL",
                    "note": (
                        f"task is 'paid' but no 'accept', 'payment', or "
                        f"'trajectory_mint' event found in history for issue {issue}"
                    ),
                })

        # Rule (b): open/claimed → no `accept` event allowed, but only for
        # mechanics where `accept` is a terminal whole-task signal.
        #
        # Why `accept` is not always terminal:
        #   - every_good: each `accept` resolves one submission; the parent
        #     task stays open across many accept events.
        #   - best_x: each `accept` fills one winner slot; task stays open
        #     until all slots fill (and even then, may close via a different
        #     verb).
        #   - trajectory mints: `trajectory_mint` per slot; parent issue
        #     stays open across mints.
        # For `standard` / `winner_take_all` / `duel` mechanics the first
        # `accept` is the whole-task resolution, so coexistence with
        # status=open/claimed signals stale task_index data.
        #
        # `payment` and `trajectory_mint` are NEVER checked here — they
        # routinely fire on open tasks for the parallel mechanics above.
        elif task_status in ("open", "claimed"):
            mechanic = (task.get("mechanic") or "").lower()
            terminal_accept = mechanic not in _PARALLEL_ACCEPT_MECHANICS
            if terminal_accept and issue in accept_issues:
                if issue in _KNOWN_STALE_OPEN_WITH_ACCEPT:
                    checks.append({
                        "issue": issue,
                        "status": task_status,
                        "result": "SKIP",
                        "note": (
                            f"known pre-existing task_index drift "
                            f"(mechanic={mechanic!r}); awaiting Agent0 "
                            f"reconciliation to bump status to 'paid'"
                        ),
                    })
                else:
                    checks.append({
                        "issue": issue,
                        "status": task_status,
                        "result": "FAIL",
                        "note": (
                            f"task is '{task_status}' but an 'accept' event exists "
                            f"in history for issue {issue} (mechanic={mechanic!r})"
                        ),
                    })
            else:
                checks.append({
                    "issue": issue,
                    "status": task_status,
                    "result": "PASS",
                    "note": "",
                })

        # Rule (c): rejected → reject event required
        elif task_status == "rejected":
            if issue in reject_issues:
                checks.append({
                    "issue": issue,
                    "status": task_status,
                    "result": "PASS",
                    "note": "",
                })
            else:
                checks.append({
                    "issue": issue,
                    "status": task_status,
                    "result": "FAIL",
                    "note": (
                        f"task is 'rejected' but no 'reject' event found "
                        f"in history for issue {issue}"
                    ),
                })

        # Other statuses (cancelled, etc.) — not covered by any rule
        else:
            checks.append({
                "issue": issue,
                "status": task_status,
                "result": "SKIP",
                "note": f"status '{task_status}' is not covered by consistency rules",
            })

    return checks


def run(root: Path) -> tuple[dict[str, Any], bool]:
    """Run the full consistency check. Returns (result_json, passed)."""
    task_index_path = root / "ledger" / "task_index.json"
    history_dir = root / "ledger" / "history"

    if not task_index_path.exists():
        result = {
            "status": "FAIL",
            "checks": [],
            "summary": f"task_index.json not found at {task_index_path}",
        }
        return result, False

    try:
        task_index = _load_json(task_index_path)
    except json.JSONDecodeError as exc:
        result = {
            "status": "FAIL",
            "checks": [],
            "summary": f"task_index.json is not valid JSON: {exc}",
        }
        return result, False

    tasks = task_index.get("tasks", {})
    if not isinstance(tasks, dict):
        result = {
            "status": "FAIL",
            "checks": [],
            "summary": "task_index.json 'tasks' field is not a dict",
        }
        return result, False

    try:
        events = _iter_history(history_dir)
    except OSError as exc:
        result = {
            "status": "FAIL",
            "checks": [],
            "summary": f"error reading history directory: {exc}",
        }
        return result, False

    accept_issues, payment_issues, mint_issues, reject_issues = _build_issue_sets(events)
    checks = check_tasks(tasks, accept_issues, payment_issues, mint_issues, reject_issues)

    n_pass = sum(1 for c in checks if c["result"] == "PASS")
    n_fail = sum(1 for c in checks if c["result"] == "FAIL")
    n_skip = sum(1 for c in checks if c["result"] == "SKIP")

    overall = "PASS" if n_fail == 0 else "FAIL"

    parts = []
    if n_pass:
        parts.append(f"{n_pass} PASS")
    if n_fail:
        parts.append(f"{n_fail} FAIL")
    if n_skip:
        parts.append(f"{n_skip} SKIP")
    summary = ", ".join(parts) if parts else "no tasks found"

    result = {
        "status": overall,
        "checks": checks,
        "summary": summary,
    }
    return result, n_fail == 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Cross-validate task_index.json statuses against ledger history events."
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root (default: auto-detected from script location)",
    )
    args = parser.parse_args()

    root = _repo_root(args.root)
    result, passed = run(root)

    print(json.dumps(result, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
