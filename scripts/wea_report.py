#!/usr/bin/env python3
"""
WEA Flow Report script.
Reads ledger files and outputs a Markdown report with 5 sections:
(1) Supply summary
(2) Top earners
(3) Flow analysis
(4) Escrow health
(5) Agent activity
"""

import json
import glob
import os
import sys
from datetime import datetime

def load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def main():
    root = "."
    for i, arg in enumerate(sys.argv):
        if arg == "--root" and i + 1 < len(sys.argv):
            root = sys.argv[i + 1]

    balances_file = os.path.join(root, "ledger", "balances.json")
    escrows_file = os.path.join(root, "ledger", "escrows.json")
    mints_file = os.path.join(root, "ledger", "trajectory_mints.json")
    history_pattern = os.path.join(root, "ledger", "history", "*.jsonl")

    balances_data = load_json(balances_file)
    escrows_data = load_json(escrows_file)
    mints_data = load_json(mints_file)

    # 1. Supply summary
    agents = balances_data.get("agents", {})
    sum_all_balances = sum(d.get("balance", 0) for d in agents.values())
    active_escrows = escrows_data.get("active", {})
    total_escrowed = sum(e.get("amount", 0) for e in active_escrows.values())
    total_minted = mints_data.get("total_minted", 0)

    # 2. Top earners
    earners = sorted(agents.items(), key=lambda x: x[1].get("total_earned", 0), reverse=True)
    
    # 3. Flow analysis
    history_files = glob.glob(history_pattern)
    transactions = []
    task_rewards = []
    for hf in history_files:
        with open(hf, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    cleaned_line = line.replace(r"\!", "!")
                    tx = json.loads(cleaned_line)
                    transactions.append(tx)
                    if tx.get("type") in ("payment", "duel-settle"):
                        if "amount" in tx:
                            task_rewards.append(tx["amount"])
                except json.JSONDecodeError as e:
                    print(f"Warning: could not parse JSON in {hf}: {e}", file=sys.stderr)
                    continue
    
    dates = set()
    for tx in transactions:
        ts = tx.get("timestamp") or tx.get("event_at")
        if ts:
            try:
                dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                dates.add(dt.date())
            except ValueError:
                pass

    unique_days = len(dates) if dates else 1
    tx_per_day = len(transactions) / unique_days if unique_days > 0 else 0
    avg_reward = sum(task_rewards) / len(task_rewards) if task_rewards else 0

    # 4. Escrow health
    oldest_escrow_issue = None
    oldest_escrow_date = None
    for issue, escrow in active_escrows.items():
        dt_str = escrow.get("created_at")
        if dt_str:
            try:
                dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
                if oldest_escrow_date is None or dt < oldest_escrow_date:
                    oldest_escrow_date = dt
                    oldest_escrow_issue = issue
            except ValueError:
                pass

    # 5. Agent activity
    active_agents = []
    dormant_agents = []
    for agent_name, d in agents.items():
        if d.get("tasks_completed", 0) > 0:
            active_agents.append((agent_name, d.get("tasks_completed", 0)))
        else:
            dormant_agents.append((agent_name, 0))

    # Generate Markdown
    md = []
    md.append("# WEA Flow Report")
    md.append("")
    md.append("## 1. Supply Summary")
    md.append(f"- **Total in Balances:** {sum_all_balances} WEA")
    md.append(f"- **Total Escrowed:** {total_escrowed} WEA")
    md.append(f"- **Total Minted:** {total_minted} WEA")
    md.append(f"- **Total Economy Size:** {sum_all_balances + total_escrowed} WEA (should be 10000 + minted)")
    md.append("")
    md.append("## 2. Top Earners")
    for i, (agent_name, data) in enumerate(earners[:10], 1):
        md.append(f"{i}. **{agent_name}**: {data.get('total_earned', 0)} WEA")
    md.append("")
    md.append("## 3. Flow Analysis")
    md.append(f"- **Total Transactions:** {len(transactions)}")
    md.append(f"- **Unique Days:** {unique_days}")
    md.append(f"- **WEA Velocity:** {tx_per_day:.2f} transactions/day")
    md.append(f"- **Average Task Reward:** {avg_reward:.2f} WEA")
    md.append("")
    md.append("## 4. Escrow Health")
    if oldest_escrow_issue:
        md.append(f"- **Oldest Active Escrow:** Issue #{oldest_escrow_issue} (created at {oldest_escrow_date})")
    else:
        md.append("- **Oldest Active Escrow:** None")
    md.append(f"- **Total Locked WEA:** {total_escrowed} WEA")
    md.append("")
    md.append("## 5. Agent Activity")
    md.append(f"- **Active Agents:** {len(active_agents)}")
    md.append(f"- **Dormant Agents:** {len(dormant_agents)}")
    md.append("")
    md.append("### Tasks per Agent (Active)")
    for agent_name, tasks in sorted(active_agents, key=lambda x: x[1], reverse=True):
        md.append(f"- **{agent_name}**: {tasks} tasks")

    print("\n".join(md))

if __name__ == "__main__":
    main()
