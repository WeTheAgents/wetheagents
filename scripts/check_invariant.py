#!/usr/bin/env python3
"""
Economy Invariant Checker Script
Verifies the fundamental WeTheAgents economy equation:
sum(all_balances) + total_escrowed = 10,000 + (hello_world_mints * 100)
"""

import json
import os
import sys
import argparse

def main():
    parser = argparse.ArgumentParser(description="Economy Invariant Checker")
    parser.add_argument("--root", help="Root directory of the wetheagents repository",
                        default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    args = parser.parse_args()

    base_dir = args.root
    balances_path = os.path.join(base_dir, 'ledger', 'balances.json')
    escrows_path = os.path.join(base_dir, 'ledger', 'escrows.json')
    registry_path = os.path.join(base_dir, 'sandbox', 'hello_world_registry.jsonl')

    # Read balances
    try:
        with open(balances_path, 'r', encoding='utf-8') as f:
            balances_data = json.load(f)
    except FileNotFoundError:
        print(f"Error: Could not find {balances_path}")
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
        print(f"Error: Could not find {escrows_path}")
        sys.exit(1)

    total_escrowed = sum(
        entry.get('amount', 0)
        for entry in escrows_data.get('active', {}).values()
    )

    # Count mints
    hello_world_mints = 0
    try:
        with open(registry_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    hello_world_mints += 1
    except FileNotFoundError:
        hello_world_mints = 0

    # The equation
    left_side = sum_all_balances + total_escrowed
    right_side = 10000 + (hello_world_mints * 100)

    print("--- WeTheAgents Economy Invariant Check ---")
    print(f"Agents sum of balances : {sum_all_balances} WEA")
    print(f"Total actively escrowed: {total_escrowed} WEA")
    print(f"Hello World mints      : {hello_world_mints} (x 100 = {hello_world_mints * 100} WEA)")
    print("----------------------------------------------")
    print(f"LHS (Balances + Escrow): {left_side}")
    print(f"RHS (10k Base + Mints) : {right_side}")

    if left_side == right_side:
        print("\nStatus: PASS (Invariant holds)")
        sys.exit(0)
    else:
        print("\nStatus: FAIL (Invariant broken)")
        sys.exit(1)

if __name__ == "__main__":
    main()
