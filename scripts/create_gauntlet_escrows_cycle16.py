"""One-shot script: create cycle-16 gauntlet founding escrows for issues #688-693."""
from __future__ import annotations
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import ledger_ops

LEDGER = ROOT / "ledger"
HISTORY = LEDGER / "history"

TASKS = [
    {"issue": 688, "trajectory": "T1", "slot": 27, "amount": 46},
    {"issue": 689, "trajectory": "T2", "slot": 28, "amount": 47},
    {"issue": 690, "trajectory": "T3", "slot": 25, "amount": 44},
    {"issue": 691, "trajectory": "T4", "slot": 25, "amount": 44},
    {"issue": 692, "trajectory": "T5", "slot": 24, "amount": 43},
    {"issue": 693, "trajectory": "T6", "slot": 30, "amount": 49},
]

def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))

def save(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

def main() -> None:
    balances = load(LEDGER / "balances.json")
    escrows = load(LEDGER / "escrows.json")
    idem_keys = load(LEDGER / "idem_keys.json")

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    history_entries: list[dict] = []

    for task in TASKS:
        issue = task["issue"]
        traj = task["trajectory"].lower()
        idem_key = f"escrow_create_{issue}_{traj}_gauntlet"
        if idem_key in idem_keys:
            print(f"SKIP #{issue}: idem key already exists")
            continue

        ledger_ops.create_escrow(
            balances,
            escrows,
            issue=issue,
            author="agent0@system",
            reward=task["amount"],
            created_at=ts,
            fee=0,
            escrow_type="standard",
        )
        idem_keys[idem_key] = ts
        history_entries.append({
            "ts": ts,
            "op": "escrow_create",
            "issue": issue,
            "amount": task["amount"],
            "from": "agent0@system",
            "reason": f"gauntlet {task['trajectory']}S{task['slot']} founding escrow",
            "idem_key": idem_key,
        })
        print(f"Created escrow for #{issue} ({task['trajectory']}S{task['slot']}): {task['amount']} WEA")

    balances["last_updated"] = ts
    balances["version"] = balances.get("version", 0) + 1
    escrows["version"] = escrows.get("version", 0) + 1

    save(LEDGER / "balances.json", balances)
    save(LEDGER / "escrows.json", escrows)
    save(LEDGER / "idem_keys.json", idem_keys)

    history_path = HISTORY / f"{today}.jsonl"
    HISTORY.mkdir(parents=True, exist_ok=True)
    with history_path.open("a", encoding="utf-8") as f:
        for entry in history_entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(f"Done. Wrote {len(history_entries)} history entries.")

if __name__ == "__main__":
    main()
