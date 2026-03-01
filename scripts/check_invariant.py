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
    idem_keys_path = os.path.join(base_dir, 'ledger', 'idem_keys.json')
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

    # Read idem keys to calculate escrows
    try:
        with open(idem_keys_path, 'r', encoding='utf-8') as f:
            idem_data = json.load(f)
    except FileNotFoundError:
        print(f"Error: Could not find {idem_keys_path}")
        sys.exit(1)

    keys = idem_data.get('keys', {})
    
    # Calculate net escrow
    # Escrow logic: 
    # An escrow key looks like "escrow|{issue}|{agent}" with "action": "escrow" and "amount": X.
    # When tasks are paid out, "payment" keys are created: "payment|{issue}|{agent}..." 
    # Payments reduce the open escrow budget for that issue.
    # However, WeTheAgents tracks tasks as issues. If a task is resolved completely, the escrow is gone.
    # Actually, the prompt says: "subtract any returned/paid escrows". 
    # Let's map total escrowed per issue and then subtract payments on that issue.
    
    escrows_by_issue = {}
    
    for key_id, data in keys.items():
        action = data.get('action')
        issue = str(data.get('issue'))
        amount = data.get('amount', 0)
        
        if action == 'escrow':
            if issue not in escrows_by_issue:
                escrows_by_issue[issue] = 0
            escrows_by_issue[issue] += amount
            
        elif action in ('payment', 'escrow_return'):
            if issue in escrows_by_issue:
                escrows_by_issue[issue] -= amount

    # Total escrowed is the sum of remaining positive escrows for each issue
    total_escrowed = 0
    for issue, remaining in escrows_by_issue.items():
        if remaining > 0:
            total_escrowed += remaining

    # Count mints
    hello_world_mints = 0
    try:
        with open(registry_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    # Every valid line in the registry is one completed hello world
                    hello_world_mints += 1
    except FileNotFoundError:
        # It's perfectly fine if nobody has done hello world yet
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
