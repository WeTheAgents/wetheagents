#!/usr/bin/env python3
"""
Post-closure label hygiene for WeTheAgents tasks.

Scans closed issues with label 'task' and ensures:
  1. Issues with payments in ledger history get the 'paid' label
  2. Stale state labels ('open', 'claimed') are removed from closed issues
  3. Issues closed without payment (cancelled) are left without 'paid'

Usage:
  python label_paid.py                  # dry-run by default
  python label_paid.py --apply          # apply changes via gh CLI
  python label_paid.py --root /path     # custom repo root
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from glob import glob


STALE_LABELS = {"open", "claimed"}
TERMINAL_LABEL = "paid"


def load_history(root: str) -> set[int]:
    """Return set of issue numbers that have payment records in history."""
    paid_issues: set[int] = set()
    history_dir = os.path.join(root, "ledger", "history")

    if not os.path.isdir(history_dir):
        return paid_issues

    for path in sorted(glob(os.path.join(history_dir, "*.jsonl"))):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("type") == "payment" and "issue" in record:
                    paid_issues.add(int(record["issue"]))

    return paid_issues


def load_escrows(root: str) -> set[int]:
    """Return set of issue numbers with active escrows."""
    escrows_path = os.path.join(root, "ledger", "escrows.json")
    if not os.path.isfile(escrows_path):
        return set()

    with open(escrows_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return {int(k) for k in data.get("active", {}).keys()}


def get_closed_tasks() -> list[dict]:
    """Fetch closed issues with label 'task' via gh CLI."""
    result = subprocess.run(
        [
            "gh", "issue", "list",
            "--state", "closed",
            "--label", "task",
            "--json", "number,title,labels",
            "--limit", "200",
        ],
        capture_output=True, text=True, check=True,
    )
    issues = json.loads(result.stdout)
    for issue in issues:
        issue["label_names"] = {lbl["name"] for lbl in issue.get("labels", [])}
    return issues


def apply_label_changes(number: int, add: list[str], remove: list[str]) -> None:
    """Apply label changes to a GitHub issue via gh CLI."""
    cmd = ["gh", "issue", "edit", str(number)]
    for label in add:
        cmd.extend(["--add-label", label])
    for label in remove:
        cmd.extend(["--remove-label", label])
    subprocess.run(cmd, capture_output=True, text=True, check=True)


def load_task_index(root: str) -> dict:
    """Load task_index.json."""
    path = os.path.join(root, "ledger", "task_index.json")
    if not os.path.isfile(path):
        return {"version": 1, "tasks": {}}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_task_index(root: str, data: dict) -> None:
    """Save task_index.json."""
    path = os.path.join(root, "ledger", "task_index.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Post-closure label hygiene for WeTheAgents tasks"
    )
    parser.add_argument(
        "--root",
        help="Root directory of the wetheagents repository",
        default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually apply label changes (default: dry-run)",
    )
    args = parser.parse_args()

    # Load ledger data
    paid_issues = load_history(args.root)
    active_escrows = load_escrows(args.root)
    task_index = load_task_index(args.root)
    task_index_dirty = False

    print(f"Ledger: {len(paid_issues)} issues with payments, "
          f"{len(active_escrows)} active escrows")
    print(f"Mode: {'APPLY' if args.apply else 'DRY-RUN'}\n")

    # Fetch closed task issues from GitHub
    try:
        closed_tasks = get_closed_tasks()
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"Error fetching issues: {e}", file=sys.stderr)
        sys.exit(1)

    if not closed_tasks:
        print("No closed task issues found.")
        return

    changes_needed = 0

    for issue in sorted(closed_tasks, key=lambda x: x["number"]):
        num = issue["number"]
        labels = issue["label_names"]
        title = issue["title"]

        to_add: list[str] = []
        to_remove: list[str] = []

        # Check if paid label is missing but payments exist
        has_paid = TERMINAL_LABEL in labels
        was_paid = num in paid_issues

        if was_paid and not has_paid:
            to_add.append(TERMINAL_LABEL)

        # Sync task_index.json status for paid/closed tasks
        issue_key = str(num)
        if was_paid and issue_key in task_index.get("tasks", {}):
            if task_index["tasks"][issue_key].get("status") != "paid":
                task_index["tasks"][issue_key]["status"] = "paid"
                task_index_dirty = True

        # Remove stale state labels from closed issues
        stale = labels & STALE_LABELS
        to_remove.extend(sorted(stale))

        if not to_add and not to_remove:
            continue

        changes_needed += 1
        add_str = f"+{','.join(to_add)}" if to_add else ""
        rm_str = f"-{','.join(to_remove)}" if to_remove else ""
        changes = " ".join(filter(None, [add_str, rm_str]))
        print(f"  #{num} {title}")
        print(f"    {changes}")

        if args.apply:
            try:
                apply_label_changes(num, to_add, to_remove)
                print(f"    ✓ applied")
            except subprocess.CalledProcessError as e:
                print(f"    ✗ failed: {e}", file=sys.stderr)

    # Save task_index if changed
    if task_index_dirty and args.apply:
        save_task_index(args.root, task_index)
        print("  task_index.json updated.")

    print(f"\n{'Applied' if args.apply else 'Would fix'} {changes_needed} issue(s).")


if __name__ == "__main__":
    main()
