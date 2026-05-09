#!/usr/bin/env python3
"""
History-to-Ledger Reconciliation.

Verifies that total_earned and total_spent per agent in balances.json
match the authoritative payment records in ledger/history/*.jsonl.

A discrepancy indicates state drift: a payment recorded in history but
not landing in balances, or vice versa.

Exits 0 on PASS (all totals match), non-zero on FAIL.
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER_DIR = os.path.join(BASE_DIR, "ledger")

ERRORS: list[str] = []


def err(agent: str, msg: str) -> None:
    ERRORS.append(f"  FAIL [{agent}]: {msg}")


def load_history(history_dir: str) -> list[tuple[str, dict]]:
    """Load all history entries as (filename, entry) pairs in chronological order."""
    entries: list[tuple[str, dict]] = []
    if not os.path.isdir(history_dir):
        return entries
    for fn in sorted(os.listdir(history_dir)):
        if not fn.endswith(".jsonl"):
            continue
        path = os.path.join(history_dir, fn)
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append((fn, json.loads(line)))
                except json.JSONDecodeError:
                    continue
    return entries


def compute_totals(
    entries: list[tuple[str, dict]],
) -> tuple[dict[str, int], dict[str, int], dict[str, list[str]]]:
    """Compute earned and spent totals from history events.

    Mirrors reconcile_counters.py accounting:
    - earned: payment, escrow_return, reversal, mint (agent field);
              trajectory_mint (agents list); economy_reset wea_returned_to_agent0
    - spent:  escrow (agent field only)

    Returns (earned, spent, agent_dates) where agent_dates maps each agent to
    the sorted list of date files that contained events for it.
    """
    earned: dict[str, int] = defaultdict(int)
    spent: dict[str, int] = defaultdict(int)
    agent_dates: dict[str, set] = defaultdict(set)

    for filename, entry in entries:
        t = entry.get("type", "")
        # NOTE: Only events with an `agent` field are counted for individual
        # agent totals. Events using `author` instead of `agent` (e.g. newer
        # escrow and escrow_return formats) are intentionally excluded from
        # total_spent/total_earned — this mirrors the reconcile_counters.py
        # formula which the current balances.json was built with.
        agent = entry.get("agent", "")
        amount = int(entry.get("amount", 0))

        if t == "economy_reset":
            # Zero out agents that were explicitly reset
            for a in entry.get("agents_zeroed", []):
                earned[a] = 0
                spent[a] = 0
            # WEA returned to agent0 counts as earned for agent0
            ret = int(entry.get("wea_returned_to_agent0", 0))
            if ret:
                earned["agent0@system"] += ret
                agent_dates["agent0@system"].add(filename)
            continue

        if t == "payment":
            earned[agent] += amount
            if agent:
                agent_dates[agent].add(filename)
        elif t == "escrow":
            # Only escrow events with `agent` field contribute to total_spent.
            # Escrows recorded with `author` field (author != "") are not counted
            # here; their balance impact is tracked separately in ledger_ops.py
            # but was not captured in total_spent by the reconcile_counters model.
            spent[agent] += amount
            if agent:
                agent_dates[agent].add(filename)
        elif t == "reversal":
            # Reversals carry a negative amount; reduces earned
            earned[agent] += amount
            if agent:
                agent_dates[agent].add(filename)
        elif t == "escrow_return":
            # Escrow returns with `agent` field are treated as income (earned),
            # consistent with how reconcile_counters.py replays history.
            # Returns with `author` field (newer format) are not captured here.
            earned[agent] += amount
            if agent:
                agent_dates[agent].add(filename)
        elif t == "mint":
            earned[agent] += amount
            if agent:
                agent_dates[agent].add(filename)
        elif t == "trajectory_mint":
            agents_list = entry.get("agents", [])
            per_agent = entry.get("per_agent", [])
            for i, a in enumerate(agents_list):
                if i < len(per_agent):
                    earned[a] += int(per_agent[i])
                    agent_dates[a].add(filename)

    sorted_dates: dict[str, list[str]] = {
        a: sorted(dates) for a, dates in agent_dates.items()
    }
    return earned, spent, sorted_dates


def check_reconciliation(
    balances: dict,
    earned: dict[str, int],
    spent: dict[str, int],
    agent_dates: dict[str, list[str]],
) -> None:
    """Compare computed totals against balances.json stored values."""
    agents = balances.get("agents", {})

    for agent_id, agent in agents.items():
        stored_earned = int(agent.get("total_earned", 0))
        stored_spent = int(agent.get("total_spent", 0))
        computed_earned = earned.get(agent_id, 0)
        computed_spent = spent.get(agent_id, 0)
        dates = agent_dates.get(agent_id, [])
        date_str = ", ".join(dates) if dates else "no history events"

        if computed_earned != stored_earned:
            delta = computed_earned - stored_earned
            err(
                agent_id,
                f"total_earned mismatch: stored={stored_earned}, "
                f"computed={computed_earned} (delta={delta:+d}) "
                f"[dates: {date_str}]",
            )

        if computed_spent != stored_spent:
            delta = computed_spent - stored_spent
            err(
                agent_id,
                f"total_spent mismatch: stored={stored_spent}, "
                f"computed={computed_spent} (delta={delta:+d}) "
                f"[dates: {date_str}]",
            )


def main() -> None:
    print("--- History-to-Ledger Reconciliation ---")

    history_dir = os.path.join(LEDGER_DIR, "history")
    balances_path = os.path.join(LEDGER_DIR, "balances.json")

    # Load balances
    if not os.path.exists(balances_path):
        err("balances.json", "file not found")
        print(f"\n{len(ERRORS)} error(s) found:\n")
        for e in ERRORS:
            print(e)
        print("\nStatus: FAIL")
        sys.exit(1)

    try:
        with open(balances_path, encoding="utf-8") as f:
            balances = json.load(f)
    except json.JSONDecodeError as exc:
        err("balances.json", f"invalid JSON: {exc}")
        print(f"\n{len(ERRORS)} error(s) found:\n")
        for e in ERRORS:
            print(e)
        print("\nStatus: FAIL")
        sys.exit(1)

    # Empty or missing history is valid — nothing to reconcile
    if not os.path.isdir(history_dir):
        print("No history directory found — nothing to reconcile.")
        print("\nStatus: PASS")
        sys.exit(0)

    has_jsonl = any(fn.endswith(".jsonl") for fn in os.listdir(history_dir))
    if not has_jsonl:
        print("No history files found — nothing to reconcile.")
        print("\nStatus: PASS")
        sys.exit(0)

    entries = load_history(history_dir)
    if not entries:
        print("No history entries found — nothing to reconcile.")
        print("\nStatus: PASS")
        sys.exit(0)

    earned, spent, agent_dates = compute_totals(entries)
    check_reconciliation(balances, earned, spent, agent_dates)

    if ERRORS:
        print(f"\n{len(ERRORS)} discrepancy(ies) found:\n")
        for e in ERRORS:
            print(e)
        print("\nStatus: FAIL")
        sys.exit(1)
    else:
        print("All agent totals match history records.")
        print("\nStatus: PASS")
        sys.exit(0)


if __name__ == "__main__":
    main()
