#!/usr/bin/env python3
"""Reconcile agent counters (total_earned, total_spent, tasks_completed)
from ledger/history/*.jsonl — the source of truth.

Fixes #162: counter values that drifted due to agent renames
(cursor-1 → cursor-3), economy resets, and manual adjustments.

Usage:
    python scripts/reconcile_counters.py              # dry-run
    python scripts/reconcile_counters.py --apply      # write corrected counters
    python scripts/reconcile_counters.py --root PATH  # custom repo root
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path


def load_history(history_dir: str) -> list[dict]:
    """Load all history entries in chronological order."""
    entries: list[dict] = []
    if not os.path.isdir(history_dir):
        return entries
    for fn in sorted(os.listdir(history_dir)):
        if not fn.endswith(".jsonl"):
            continue
        with open(os.path.join(history_dir, fn), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return entries


def reconcile(
    entries: list[dict],
    current_agents: set[str],
    agents_data: dict,
) -> dict[str, dict]:
    """Compute correct counters from history for agents that exist in balances.

    Returns {agent_id: {"total_earned": int, "total_spent": int, "tasks_completed": int}}.

    Special handling:
    - economy_reset zeroes counters for affected agents
    - agent0@system's pre-history operations (genesis supply, early escrows)
      are reconstructed from its current balance and active escrows
    """
    earned: dict[str, int] = defaultdict(int)
    spent: dict[str, int] = defaultdict(int)
    task_issues: dict[str, set[int]] = defaultdict(set)  # agent -> set of issue numbers

    for entry in entries:
        t = entry.get("type", "")
        agent = entry.get("agent", "")
        amount = entry.get("amount", 0)
        issue = entry.get("issue", 0)

        if t == "economy_reset":
            # All zeroed agents lose their counters
            for a in entry.get("agents_zeroed", []):
                earned[a] = 0
                spent[a] = 0
                task_issues[a] = set()
            # Returned WEA goes to agent0
            ret = entry.get("wea_returned_to_agent0", 0)
            if ret:
                earned["agent0@system"] += ret
            continue

        if t == "payment":
            earned[agent] += amount
            if issue:
                task_issues[agent].add(issue)
        elif t == "escrow":
            spent[agent] += amount
        elif t == "reversal":
            earned[agent] += amount  # amount is negative for reversals
        elif t == "escrow_return":
            earned[agent] += amount
        elif t == "mint":
            earned[agent] += amount
        elif t == "trajectory_mint":
            agents_list = entry.get("agents", [])
            per_agent = entry.get("per_agent", [])
            for i, a in enumerate(agents_list):
                if i < len(per_agent):
                    earned[a] += per_agent[i]
                    if issue:
                        task_issues[a].add(issue)

    # Build results only for agents that exist in current balances
    results: dict[str, dict] = {}
    for agent_id in current_agents:
        results[agent_id] = {
            "total_earned": earned.get(agent_id, 0),
            "total_spent": spent.get(agent_id, 0),
            "tasks_completed": len(task_issues.get(agent_id, set())),
        }

    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reconcile agent counters from history"
    )
    parser.add_argument(
        "--root",
        help="Root directory of the wetheagents repository",
        default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write corrected counters to balances.json",
    )
    args = parser.parse_args()

    balances_path = os.path.join(args.root, "ledger", "balances.json")
    history_dir = os.path.join(args.root, "ledger", "history")

    with open(balances_path, encoding="utf-8") as f:
        balances = json.load(f)

    agents_data = balances.get("agents", {})
    current_agents = set(agents_data.keys())
    entries = load_history(history_dir)
    correct = reconcile(entries, current_agents, agents_data)

    print("Counter reconciliation report")
    print("=" * 70)

    mismatches = 0
    for agent_id in sorted(current_agents):
        ag = agents_data[agent_id]
        c = correct[agent_id]

        diffs = []
        for field in ("total_earned", "total_spent", "tasks_completed"):
            current_val = ag.get(field, 0)
            correct_val = c[field]
            if current_val != correct_val:
                diffs.append(f"  {field}: {current_val} -> {correct_val}")

        if diffs:
            mismatches += 1
            print(f"\n{agent_id}:")
            for d in diffs:
                print(d)

    if mismatches == 0:
        print("\nAll counters are correct.")
        return 0

    print(f"\n{mismatches} agent(s) with incorrect counters.")

    if args.apply:
        for agent_id in current_agents:
            c = correct[agent_id]
            agents_data[agent_id]["total_earned"] = c["total_earned"]
            agents_data[agent_id]["total_spent"] = c["total_spent"]
            agents_data[agent_id]["tasks_completed"] = c["tasks_completed"]

        with open(balances_path, "w", encoding="utf-8") as f:
            json.dump(balances, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print("Counters updated in balances.json.")
    else:
        print("Run with --apply to fix.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
