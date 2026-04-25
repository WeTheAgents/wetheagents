#!/usr/bin/env python3
"""Return a gauntlet founding escrow back to agent0 after mint.

Usage:
    python scripts/gauntlet_escrow_return.py --issue N --cycle C --traj "T5S31"
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Return gauntlet founding escrow to agent0")
    parser.add_argument("--issue", type=int, required=True)
    parser.add_argument("--cycle", type=int, required=True)
    parser.add_argument("--traj", required=True, help='e.g. "T5S31"')
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

    idem_key = f"escrow-return-cycle{args.cycle}-{args.issue}"
    if idem_key in idem_keys:
        print(f"SKIP: idem key {idem_key!r} already exists — already returned")
        return 0

    issue_str = str(args.issue)
    escrow = escrows.get("active", {}).get(issue_str)
    if not escrow:
        print(f"ERROR: no active escrow for issue #{args.issue}")
        return 1

    amount = int(escrow["amount"])
    author = str(escrow["author"])

    agents = balances["agents"]
    if author not in agents:
        print(f"ERROR: author {author!r} not in balances")
        return 1

    agents[author]["balance"] = int(agents[author].get("balance", 0)) + amount
    agents[author]["total_spent"] = int(agents[author].get("total_spent", 0)) - amount
    del escrows["active"][issue_str]

    balances["version"] = int(balances.get("version", 0)) + 1
    escrows["version"] = int(escrows.get("version", 0)) + 1

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    idem_keys[idem_key] = ts

    hist_entry = {
        "ts": ts,
        "type": "escrow_return",
        "issue": args.issue,
        "amount": amount,
        "recipient": author,
        "reason": f"gauntlet founding escrow \u2014 cycle{args.cycle} {args.traj} minted",
        "idem_key": idem_key,
    }

    bal_path.write_text(json.dumps(balances, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    esc_path.write_text(json.dumps(escrows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    idem_path.write_text(json.dumps(idem_keys, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with open(hist_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(hist_entry, ensure_ascii=False) + "\n")

    print(f"Returned escrow #{args.issue}: {amount} WEA to {author}. idem_key={idem_key!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
