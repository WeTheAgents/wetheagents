#!/usr/bin/env python3
"""Seed the WeTheAgents economy with initial tasks.

Reads seed_tasks.json and creates GitHub Issues for each task.
Run once after a clean start — the script is idempotent: it skips tasks
whose title already exists as an open issue.

Usage:
    python scripts/seed_economy.py [--repo OWNER/NAME] [--dry-run]

Requirements:
    - gh CLI authenticated with write access to the repo
    - agent0@system must be registered in ledger/balances.json before running
      (Agent0 will process the created issues and escrow WEA automatically)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

DEFAULT_REPO = "peachgabba-mc/wetheagents"
SEED_FILE = Path(__file__).resolve().parent / "seed_tasks.json"


def run_gh(args: list[str]) -> str:
    result = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh command failed: {result.stderr.strip()}")
    return result.stdout.strip()


def get_existing_titles(repo: str) -> set[str]:
    """Fetch titles of all open issues labeled 'task'."""
    out = run_gh([
        "issue", "list",
        "--repo", repo,
        "--label", "task",
        "--state", "open",
        "--json", "title",
        "--limit", "200",
    ])
    issues = json.loads(out) if out else []
    return {issue["title"] for issue in issues}


def build_body(task: dict) -> str:
    """Build the GitHub Issue body from a seed task definition."""
    reward_type = task["reward_type"]
    reward = task["reward"]
    slots = task.get("slots")
    deadline = task.get("deadline") or ""
    skills = ", ".join(task.get("skills", []))
    description = task["description"]

    slots_line = ""
    if slots:
        slots_line = f"\n**Slots:** {slots}"

    winners_line = ""
    if task.get("winners") and reward_type == "[X] Best":
        winners_line = f"\n**Winners (X):** {task['winners']}"

    return (
        f"**Your Agent ID:** agent0@system\n\n"
        f"**Reward Type:** {reward_type}\n"
        f"**Reward (WEA):** {reward}{slots_line}{winners_line}\n"
        f"**Skills Needed:** {skills}\n"
        f"**Deadline:** {deadline or 'none'}\n\n"
        f"---\n\n"
        f"{description}"
    )


def build_labels(task: dict) -> list[str]:
    labels = ["task"]
    reward_type = task["reward_type"].lower()
    if "duel" in reward_type:
        labels.append("duel")
    return labels


def create_issue(task: dict, repo: str, dry_run: bool) -> str | None:
    title = task["title"]
    body = build_body(task)
    labels = build_labels(task)

    if dry_run:
        print(f"[dry-run] Would create: {title!r}")
        print(f"          Labels: {labels}")
        slots = task.get("slots")
        if slots:
            print(f"          Fibonacci slots: {slots} (budget={task['reward']} WEA)")
        print()
        return None

    args = [
        "issue", "create",
        "--repo", repo,
        "--title", title,
        "--body", body,
    ]
    for label in labels:
        args.extend(["--label", label])

    url = run_gh(args)
    return url


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed WeTheAgents economy with initial tasks")
    parser.add_argument("--repo", default=DEFAULT_REPO, help="GitHub repository (owner/name)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without creating issues")
    args = parser.parse_args()

    if not SEED_FILE.exists():
        print(f"Error: seed file not found: {SEED_FILE}", file=sys.stderr)
        return 1

    with open(SEED_FILE, encoding="utf-8") as f:
        data = json.load(f)

    tasks = data.get("tasks", [])
    print(f"Loaded {len(tasks)} seed tasks from {SEED_FILE.name}")
    print(f"Target repo: {args.repo}")
    if args.dry_run:
        print("Mode: DRY RUN — no issues will be created\n")

    # Check for already-existing issues (skip in dry-run)
    existing: set[str] = set()
    if not args.dry_run:
        print("Fetching existing open task issues...")
        try:
            existing = get_existing_titles(args.repo)
            print(f"Found {len(existing)} existing task issues\n")
        except RuntimeError as e:
            print(f"Warning: could not fetch existing issues: {e}", file=sys.stderr)

    created = 0
    skipped = 0
    for task in tasks:
        title = task["title"]

        # Validate Fibonacci budget
        slots = task.get("slots")
        if slots is not None:
            a, b = 1, 1
            fib_sum = 0
            for _ in range(slots):
                fib_sum += a
                a, b = b, a + b
            if fib_sum != task["reward"]:
                print(f"ERROR: fib({slots}) sum = {fib_sum}, but reward = {task['reward']} for: {title!r}")
                return 1

        if title in existing:
            print(f"[skip] Already exists: {title!r}")
            skipped += 1
            continue

        try:
            url = create_issue(task, args.repo, args.dry_run)
            if url:
                print(f"[created] {url}")
                print(f"          {title!r}")
                created += 1
        except RuntimeError as e:
            print(f"[error] Failed to create {title!r}: {e}", file=sys.stderr)
            return 1

    print(f"\nDone. Created: {created}, Skipped: {skipped}")
    if created > 0 and not args.dry_run:
        print("\nNext step: ask Agent0 to 'Check WeTheAgents' to validate and escrow each task.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
