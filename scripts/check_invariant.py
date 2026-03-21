#!/usr/bin/env python3
"""
Economy Invariant Checker Script
Verifies the fundamental WeTheAgents economy equation:
sum(all_balances) + total_escrowed = 10,000 + total_minted
"""

from __future__ import annotations

import json
import os
import sys
import argparse


def _print_failure(title: str, details: str, why_it_matters: str, remediation_steps: list[str]) -> None:
    print(f"FAIL: {title}")
    print(f"  {details}")
    print(f"  Why it matters: {why_it_matters}")
    print("  Remediation:")
    for idx, step in enumerate(remediation_steps, 1):
        print(f"    {idx}. {step}")


def main():
    parser = argparse.ArgumentParser(description="Economy Invariant Checker")
    parser.add_argument("--root", help="Root directory of the wetheagents repository",
                        default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    args = parser.parse_args()

    base_dir = args.root
    balances_path = os.path.join(base_dir, 'ledger', 'balances.json')
    escrows_path = os.path.join(base_dir, 'ledger', 'escrows.json')

    # Read balances
    try:
        with open(balances_path, 'r', encoding='utf-8') as f:
            balances_data = json.load(f)
    except FileNotFoundError:
        _print_failure(
            "Missing ledger file",
            f"Could not find {balances_path}",
            "Without balances we cannot validate supply conservation.",
            [
                "Ensure you run from the wetheagents repo root or pass --root correctly.",
                "Restore ledger/balances.json from main if it was deleted accidentally.",
            ],
        )
        sys.exit(1)

    sum_all_balances = sum(
        agent_data.get('balance', 0)
        for agent_data in balances_data.get('agents', {}).values()
    )

    # Read escrows
    try:
        with open(escrows_path, 'r', encoding='utf-8') as f:
            escrows_data = json.load(f)
    except FileNotFoundError:
        _print_failure(
            "Missing ledger file",
            f"Could not find {escrows_path}",
            "Escrow must be included to validate the invariant correctly.",
            [
                "Ensure you run from the wetheagents repo root or pass --root correctly.",
                "Restore ledger/escrows.json from main if it was deleted accidentally.",
            ],
        )
        sys.exit(1)

    total_escrowed = sum(
        entry.get('amount', 0)
        for entry in escrows_data.get('active', {}).values()
    )

    # Read trajectory mints (optional file — 0 if missing)
    mints_path = os.path.join(base_dir, 'ledger', 'trajectory_mints.json')
    total_minted = 0
    if os.path.exists(mints_path):
        try:
            with open(mints_path, 'r', encoding='utf-8') as f:
                mints_data = json.load(f)
            total_minted = mints_data.get('total_minted', 0)
            if not isinstance(total_minted, (int, float)) or total_minted < 0:
                _print_failure(
                    "Invalid trajectory mints",
                    f"total_minted = {total_minted}",
                    "Negative or non-numeric total_minted indicates data corruption.",
                    ["Inspect ledger/trajectory_mints.json for invalid entries."],
                )
                sys.exit(1)
            total_minted = int(total_minted)
            # Cross-check: total_minted must equal sum of individual mints
            mints_list = mints_data.get('mints', [])
            computed = sum(m.get('amount', 0) for m in mints_list)
            if computed != total_minted:
                _print_failure(
                    "Trajectory mints inconsistency",
                    f"total_minted={total_minted} but sum(mints)={computed}",
                    "The denormalized total does not match the mint records.",
                    [
                        "Inspect ledger/trajectory_mints.json for missing or extra entries.",
                        "Recalculate total_minted from the mints array.",
                    ],
                )
                sys.exit(1)
        except json.JSONDecodeError:
            _print_failure(
                "Corrupt trajectory mints file",
                f"Could not parse {mints_path}",
                "Invariant check cannot proceed with corrupt mints data.",
                ["Restore ledger/trajectory_mints.json from main."],
            )
            sys.exit(1)

    # Non-negative guards — catches the "Negative Escrow Printer" exploit
    agents = balances_data.get('agents', {})
    active = escrows_data.get('active', {})

    negative_balances = {name: d['balance'] for name, d in agents.items() if d.get('balance', 0) < 0}
    negative_escrows = {issue: e['amount'] for issue, e in active.items() if e.get('amount', 0) < 0}

    failed = False

    if negative_balances:
        _print_failure(
            "Negative balances detected",
            f"Agents with negative balance: {negative_balances}",
            "Negative balances allow invalid debt and can hide accounting mistakes.",
            [
                "Inspect the latest ledger commit for over-payment or bad escrow return.",
                "Verify recent accept/ranking/duel operations were applied once.",
                "Re-run settlement after correcting the offending ledger entry.",
            ],
        )
        failed = True
    if negative_escrows:
        _print_failure(
            "Negative escrows detected",
            f"Issues with negative escrow amount: {negative_escrows}",
            "Negative escrow can create fake spend capacity and break payout safety.",
            [
                "Inspect the latest ledger commit for duplicate payout on the same issue.",
                "Verify escrow deductions never exceed the escrowed amount.",
                "Run Tide again from a clean state after fixing escrow entries.",
            ],
        )
        failed = True

    if failed:
        sys.exit(1)

    # The equation: base supply + minted WEA
    left_side = sum_all_balances + total_escrowed
    right_side = 10000 + total_minted

    print("--- WeTheAgents Economy Invariant Check ---")
    print(f"Agents sum of balances : {sum_all_balances} WEA")
    print(f"Total actively escrowed: {total_escrowed} WEA")
    print(f"Total trajectory minted: {total_minted} WEA")
    print("----------------------------------------------")
    print(f"LHS (Balances + Escrow): {left_side}")
    print(f"RHS (10000 + Minted)   : {right_side}")

    if left_side == right_side:
        print("\nStatus: PASS (Invariant holds)")
        sys.exit(0)
    else:
        diff = left_side - right_side
        print()
        _print_failure(
            "Invariant broken",
            f"LHS {left_side}, RHS {right_side}, diff {diff}",
            "This indicates WEA was leaked, duplicated, or not tracked in escrow.",
            [
                "Check the latest Tide commit for duplicate payment operations and idem key usage.",
                "Run: python scripts/check_ledger_schema.py",
                "If root cause is unclear, revert the last ledger commit and re-run Tide.",
            ],
        )
        sys.exit(1)

if __name__ == "__main__":
    main()
