#!/usr/bin/env python3
"""Create a gauntlet founding escrow from agent0 for a specific issue.

Usage:
    python scripts/gauntlet_escrow_create.py --issue N --amount A [--root PATH]

Directly deducts from agent0@system balance (no 1-WEA Tide fee).
Used for heartbeat-created gauntlet tasks to avoid double-escrow with Tide.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Create gauntlet founding escrow from agent0")
    parser.add_argument("--issue", type=int, required=True)
    parser.add_argument("--amount", type=int, required=True)
    parser.add_argument("--root", default=".", type=Path)
    args = parser.parse_args()

    root = args.root
    bal_path = root / "ledger" / "balances.json"
    esc_path = root / "ledger" / "escrows.json"
    idem_path = root / "ledger" / "idem_keys.json"
    hist_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    hist_path = root / "ledger" / "history" / f"{hist_date}.jsonl"

    balances = json.loads(bal_path.read_text(encoding="utf-8"))
    escrows = json.loads(esc_path.read_text(encoding="utf-8"))
    idem_keys = json.loads(idem_path.read_text(encoding="utf-8"))

    idem_key = f"escrow_create|{args.issue}"
    if idem_key in idem_keys:
        print(f"SKIP: idem key {idem_key!r} already exists — escrow already created")
        return 0

    issue_str = str(args.issue)
    active = escrows.setdefault("active", {})
    if issue_str in active:
        print(f"ERROR: active escrow for issue #{args.issue} already exists")
        return 1

    agents = balances["agents"]
    author = "agent0@system"
    if author not in agents:
        print(f"ERROR: {author} not in balances")
        return 1

    a0 = agents[author]
    if a0.get("balance", 0) < args.amount:
        print(f"ERROR: agent0 balance {a0.get('balance', 0)} < {args.amount}")
        return 1

    a0["balance"] = int(a0.get("balance", 0)) - args.amount
    a0["total_spent"] = int(a0.get("total_spent", 0)) + args.amount
    a0["tasks_created"] = int(a0.get("tasks_created", 0)) + 1

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    active[issue_str] = {
        "author": author,
        "amount": args.amount,
        "type": "standard",
        "created_at": ts,
    }

    balances["version"] = int(balances.get("version", 0)) + 1
    escrows["version"] = int(escrows.get("version", 0)) + 1

    idem_keys[idem_key] = ts

    hist_entry = {
        "ts": ts,
        "type": "escrow_create",
        "issue": args.issue,
        "amount": args.amount,
        "author": author,
        "escrow_type": "standard",
        "idem_key": idem_key,
    }

    bal_path.write_text(json.dumps(balances, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    esc_path.write_text(json.dumps(escrows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    idem_path.write_text(json.dumps(idem_keys, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with open(hist_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(hist_entry, ensure_ascii=False) + "\n")

    print(f"Created escrow #{args.issue}: {args.amount} WEA from {author}. idem_key={idem_key!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
