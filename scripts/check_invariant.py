#!/usr/bin/env python3
"""
Economy Invariant Checker Script
Verifies the fundamental WeTheAgents economy equation:
sum(all_balances) + total_escrowed = 10,000 + total_minted
"""

from __future__ import annotations

import argparse
import json
import os
import sys


def _print_failure(title: str, details: str, why_it_matters: str, remediation_steps: list[str]) -> None:
    print(f"FAIL: {title}")
    print(f"  {details}")
    print(f"  Why it matters: {why_it_matters}")
    print("  Remediation:")
    for idx, step in enumerate(remediation_steps, 1):
        print(f"    {idx}. {step}")


def _is_valid_amount(value) -> bool:
    """Return True if value is a plain integer (not bool, not float, not str)."""
    return isinstance(value, int) and not isinstance(value, bool)


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
        with open(balances_path, encoding='utf-8') as f:
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

    # Validate agents section type
    agents = balances_data.get('agents', {})
    if not isinstance(agents, dict):
        _print_failure(
            "Malformed balances.json",
            f"'agents' section is {type(agents).__name__}, expected dict",
            "A non-dict agents section cannot be iterated for balance sums.",
            ["Restore ledger/balances.json from main or fix the agents section structure."],
        )
        sys.exit(1)

    # Validate each agent entry is a dict
    bad_agent_entries = [name for name, val in agents.items() if not isinstance(val, dict)]
    if bad_agent_entries:
        _print_failure(
            "Non-dict agent entries in balances.json",
            f"These entries are not dicts: {bad_agent_entries}",
            "Non-dict agent entries cannot be processed for balance sums.",
            [
                "Inspect ledger/balances.json for corrupted or manually edited agent entries.",
                "Each agent must be an object with at least a 'balance' key.",
            ],
        )
        sys.exit(1)

    # Validate each balance is a plain integer (no floats, strings, nulls, bools)
    non_int_balances = {
        name: repr(d.get('balance'))
        for name, d in agents.items()
        if not _is_valid_amount(d.get('balance', 0))
    }
    if non_int_balances:
        _print_failure(
            "Non-integer balance values",
            f"Agents with non-integer balance: {non_int_balances}",
            "Float, string, null, or bool balances cause imprecise sums and bypass "
            "the negative-balance guard. WEA must always be a whole-number integer.",
            [
                "Inspect ledger/balances.json for invalid balance values.",
                "All balance fields must be plain integers (e.g. 5000, not 5000.0 or '5000').",
            ],
        )
        sys.exit(1)

    sum_all_balances = sum(
        d.get('balance', 0)
        for d in agents.values()
    )

    # Read escrows
    try:
        with open(escrows_path, encoding='utf-8') as f:
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

    # Validate active section type
    active = escrows_data.get('active', {})
    if not isinstance(active, dict):
        _print_failure(
            "Malformed escrows.json",
            f"'active' section is {type(active).__name__}, expected dict",
            "A non-dict active section cannot be iterated for escrow sums.",
            ["Restore ledger/escrows.json from main or fix the active section structure."],
        )
        sys.exit(1)

    # Validate each escrow entry is a dict
    bad_escrow_entries = [issue for issue, val in active.items() if not isinstance(val, dict)]
    if bad_escrow_entries:
        _print_failure(
            "Non-dict escrow entries in escrows.json",
            f"These entries are not dicts: {bad_escrow_entries}",
            "Non-dict escrow entries cannot be processed for escrow sums.",
            [
                "Inspect ledger/escrows.json for corrupted or manually edited escrow entries.",
                "Each escrow must be an object with at least an 'amount' key.",
            ],
        )
        sys.exit(1)

    # Validate each escrow entry's amount is a plain integer
    non_int_escrow_amounts = {
        issue: repr(entry.get('amount'))
        for issue, entry in active.items()
        if not _is_valid_amount(entry.get('amount', 0))
    }
    if non_int_escrow_amounts:
        _print_failure(
            "Non-integer escrow amounts",
            f"Escrows with non-integer amount: {non_int_escrow_amounts}",
            "Float, string, or null escrow amounts cause imprecise sums. "
            "WEA escrow must always be a whole-number integer.",
            [
                "Inspect ledger/escrows.json for invalid amount values.",
                "All amount fields must be plain integers.",
            ],
        )
        sys.exit(1)

    total_escrowed = sum(
        entry.get('amount', 0)
        for entry in active.values()
        if isinstance(entry, dict)
    )

    # Read trajectory mints (optional file — 0 if missing)
    mints_path = os.path.join(base_dir, 'ledger', 'trajectory_mints.json')
    total_minted = 0
    if os.path.exists(mints_path):
        try:
            with open(mints_path, encoding='utf-8') as f:
                mints_data = json.load(f)
            total_minted = mints_data.get('total_minted', 0)
            if not isinstance(total_minted, (int, float)) or isinstance(total_minted, bool) \
                    or total_minted < 0:
                _print_failure(
                    "Invalid trajectory mints",
                    f"total_minted = {total_minted!r}",
                    "Negative, boolean, or non-numeric total_minted indicates data corruption.",
                    ["Inspect ledger/trajectory_mints.json for invalid entries."],
                )
                sys.exit(1)
            # Reject fractional total_minted — float truncation would hide phantom supply
            if isinstance(total_minted, float) and not total_minted.is_integer():
                _print_failure(
                    "Fractional total_minted",
                    f"total_minted = {total_minted} is not a whole number",
                    "Fractional WEA in total_minted is not allowed. "
                    "int() truncation would silently hide up to 0.999 WEA of phantom supply.",
                    [
                        "Inspect ledger/trajectory_mints.json — total_minted must be a whole number.",
                        "Recalculate from the mints array and round to the nearest integer.",
                    ],
                )
                sys.exit(1)
            total_minted = int(total_minted)

            # Validate mints array
            mints_list = mints_data.get('mints', [])
            if not isinstance(mints_list, list):
                _print_failure(
                    "Malformed trajectory_mints.json",
                    f"'mints' field is {type(mints_list).__name__}, expected list",
                    "A non-list mints field cannot be iterated for cross-checking.",
                    ["Restore ledger/trajectory_mints.json from main."],
                )
                sys.exit(1)

            bad_mint_entries = [i for i, m in enumerate(mints_list) if not isinstance(m, dict)]
            if bad_mint_entries:
                _print_failure(
                    "Non-dict mint entries in trajectory_mints.json",
                    f"Entry indices with non-dict values: {bad_mint_entries}",
                    "Non-dict mint entries cannot be processed for the cross-check sum.",
                    ["Inspect ledger/trajectory_mints.json for corrupted mint entries."],
                )
                sys.exit(1)

            non_int_mint_amounts = [
                i for i, m in enumerate(mints_list)
                if not _is_valid_amount(m.get('amount', 0))
            ]
            if non_int_mint_amounts:
                _print_failure(
                    "Non-integer mint amounts in trajectory_mints.json",
                    f"Mint entries at indices {non_int_mint_amounts} have non-integer amounts",
                    "Float or string mint amounts cause cross-check failures and imprecise totals.",
                    ["Inspect ledger/trajectory_mints.json — all mint amount fields must be integers."],
                )
                sys.exit(1)

            # Cross-check: total_minted must equal sum of individual mints
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
    negative_balances = {name: d['balance'] for name, d in agents.items() if d.get('balance', 0) < 0}
    negative_escrows = {issue: e['amount'] for issue, e in active.items() if isinstance(e, dict) and e.get('amount', 0) < 0}

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
