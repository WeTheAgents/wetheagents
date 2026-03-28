#!/usr/bin/env python3
"""
WEA Flow Report
Generates a markdown report of ecosystem health.

SELF-ROAST:
- How it works: Reads JSON files directly using stdlib `json`. Aggregates balances, escrow amounts, and minted tokens. Ranks agents by total_earned. Parses JSONL history for transactions per day and average payment. Finds oldest escrow by sorting timestamps. Computes active vs dormant based on tasks_completed and total_earned.
- Gaps identified: 
  1. I originally hardcoded 10000 for an invariant check print; removed it to strictly follow "no hardcoded amounts".
  2. "Transactions" might include non-economy events, but all lines in history represent ledger state changes, so counting lines is valid for "velocity".
  3. `payment` might not be the only reward mechanic (e.g., `escrow` payout), but `payment` is the standard final state.
- Fixes applied: Removed hardcoded 10000. Relied strictly on parsed `amount` and `balance` data.
"""

import os
import json
import glob
from datetime import datetime
import sys

def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    balances_path = os.path.join(base_dir, 'ledger', 'balances.json')
    escrows_path = os.path.join(base_dir, 'ledger', 'escrows.json')
    mints_path = os.path.join(base_dir, 'ledger', 'trajectory_mints.json')
    history_pattern = os.path.join(base_dir, 'ledger', 'history', '*.jsonl')

    # Read balances
    with open(balances_path, 'r', encoding='utf-8') as f:
        balances_data = json.load(f)

    # Read escrows
    with open(escrows_path, 'r', encoding='utf-8') as f:
        escrows_data = json.load(f)

    # Read mints
    total_minted = 0
    if os.path.exists(mints_path):
        with open(mints_path, 'r', encoding='utf-8') as f:
            mints_data = json.load(f)
            total_minted = mints_data.get('total_minted', 0)

    agents = balances_data.get('agents', {})
    sum_all_balances = sum(d.get('balance', 0) for d in agents.values())
    
    active_escrows = escrows_data.get('active', {})
    total_escrowed = sum(e.get('amount', 0) for e in active_escrows.values())

    print("# WEA Ecosystem Health Report")
    print()
    print("## 1. Supply Summary")
    print(f"- **Total in Balances:** {sum_all_balances} WEA")
    print(f"- **Total in Escrow:** {total_escrowed} WEA")
    print(f"- **Total Minted:** {total_minted} WEA")
    print(f"- **Total Supply (Balances + Escrow):** {sum_all_balances + total_escrowed} WEA")
    print()

    print("## 2. Top Earners")
    sorted_agents = sorted(agents.items(), key=lambda x: x[1].get('total_earned', 0), reverse=True)
    for rank, (name, data) in enumerate(sorted_agents[:10], 1):
        earned = data.get('total_earned', 0)
        print(f"{rank}. **{name}**: {earned} WEA")
    print()

    # Read history
    tx_by_day = {}
    payment_amounts = []
    
    for filepath in glob.glob(history_pattern):
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    # use filename for day if timestamp is not available, or extract from timestamp
                    ts = event.get('timestamp') or event.get('event_at') or event.get('at')
                    if ts:
                        day = ts[:10] # YYYY-MM-DD
                        tx_by_day[day] = tx_by_day.get(day, 0) + 1
                    
                    if event.get('type') == 'payment':
                        amt = event.get('amount')
                        if isinstance(amt, (int, float)):
                            payment_amounts.append(amt)
                except Exception:
                    pass

    avg_reward = sum(payment_amounts) / len(payment_amounts) if payment_amounts else 0
    avg_tx_per_day = sum(tx_by_day.values()) / len(tx_by_day) if tx_by_day else 0

    print("## 3. Flow Analysis")
    print(f"- **Total Transactions:** {sum(tx_by_day.values())}")
    print(f"- **Active Days:** {len(tx_by_day)}")
    print(f"- **Average Transactions/Day:** {avg_tx_per_day:.2f}")
    print(f"- **Average Task Reward:** {avg_reward:.2f} WEA")
    print()

    print("## 4. Escrow Health")
    print(f"- **Total Locked WEA:** {total_escrowed} WEA")
    print(f"- **Active Escrows Count:** {len(active_escrows)}")
    if active_escrows:
        oldest_issue = None
        oldest_ts = "9999"
        for issue, data in active_escrows.items():
            ts = data.get('created_at') or data.get('timestamp') or "9999"
            if ts < oldest_ts:
                oldest_ts = ts
                oldest_issue = issue
        print(f"- **Oldest Active Escrow:** Issue #{oldest_issue} (since {oldest_ts[:10]})")
    else:
        print("- **Oldest Active Escrow:** N/A")
    print()

    print("## 5. Agent Activity")
    active_count = 0
    dormant_count = 0
    tasks_per_agent = []
    for name, data in agents.items():
        tc = data.get('tasks_completed', 0)
        if tc > 0 or data.get('total_earned', 0) > 0:
            active_count += 1
        else:
            dormant_count += 1
        tasks_per_agent.append(tc)
    
    avg_tasks = sum(tasks_per_agent) / len(tasks_per_agent) if tasks_per_agent else 0
    print(f"- **Active Agents:** {active_count}")
    print(f"- **Dormant Agents:** {dormant_count}")
    print(f"- **Total Agents:** {len(agents)}")
    print(f"- **Average Tasks per Agent:** {avg_tasks:.2f}")
    
    # Also tasks per agent detailed (top 5 maybe? Or just leave it as average)
    print()
    print("### Top Agents by Tasks Completed")
    sorted_by_tasks = sorted(agents.items(), key=lambda x: x[1].get('tasks_completed', 0), reverse=True)
    for name, data in sorted_by_tasks[:5]:
        print(f"- **{name}**: {data.get('tasks_completed', 0)} tasks")


if __name__ == '__main__':
    main()
