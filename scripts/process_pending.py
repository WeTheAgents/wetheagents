#!/usr/bin/env python3
"""Process the ledger/pending.json payment queue.

Reads pending.json, validates each entry against escrows.json and idem_keys.json,
executes payments in a single batch commit, then clears the queue.

Supports all reward mechanics: standard, progressive, every_good, ranking, duel.

Usage:
    python scripts/process_pending.py [--root PATH] [--dry-run]

Run this when Agent0 is ready to batch-settle approved payments.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.economy_constants import SPLIT_TABLE
    from scripts.tide_ops import fib, idem_key_hash
except ModuleNotFoundError:  # pragma: no cover - script execution fallback
    from economy_constants import SPLIT_TABLE
    from tide_ops import fib, idem_key_hash

VALID_MECHANICS = {"standard", "progressive", "every_good", "ranking", "duel"}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_idem_key(mechanic: str, issue: str, agent: str, entry: dict) -> str:
    """Build raw idempotency key based on mechanic type."""
    if mechanic == "ranking":
        rank = entry.get("rank", 0)
        return f"payment|{issue}|{agent}|ranking|{rank}"
    if mechanic == "duel":
        role = entry.get("role", "unknown")
        return f"payment|{issue}|{agent}|duel|{role}"
    # standard, progressive, every_good
    return f"payment|{issue}|{agent}"


def process(root: Path, dry_run: bool) -> int:  # noqa: C901, PLR0912, PLR0915
    pending_path = root / "ledger" / "pending.json"
    balances_path = root / "ledger" / "balances.json"
    escrows_path = root / "ledger" / "escrows.json"
    idem_path = root / "ledger" / "idem_keys.json"

    pending = load_json(pending_path)
    queue = pending.get("queue", [])

    if not queue:
        print("Queue is empty. Nothing to process.")
        return 0

    started_at = now_iso()

    balances = load_json(balances_path)
    escrows = load_json(escrows_path)
    idem_keys = load_json(idem_path)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    history_path = root / "ledger" / "history" / f"{today}.jsonl"

    errors: list[str] = []
    payments: list[dict] = []
    seen_keys: set[str] = set()

    # Batch simulation state: track progressive paid_count and remaining budget per issue
    simulated_paid_counts: dict[str, int] = {}
    simulated_remaining: dict[str, int] = {}

    # =========================================================================
    # VALIDATION LOOP
    # =========================================================================
    for i, entry in enumerate(queue):
        issue = str(entry.get("issue", ""))
        agent = entry.get("agent", "")
        proposed_amount = entry.get("amount", 0)
        proposed_by = entry.get("proposed_by", "unknown")
        mechanic = entry.get("mechanic", "standard")
        event_at = entry.get("event_at", "")

        # --- Basic field validation ---
        if not issue or not agent:
            errors.append(f"Entry {i}: missing issue or agent")
            continue

        if mechanic not in VALID_MECHANICS:
            errors.append(f"Entry {i}: unknown mechanic '{mechanic}'")
            continue

        if not event_at:
            errors.append(f"Entry {i}: missing event_at")
            continue

        # --- Mechanic-specific field validation ---
        if mechanic == "ranking":
            if "rank" not in entry or "total_ranked" not in entry:
                errors.append(f"Entry {i}: ranking requires 'rank' and 'total_ranked'")
                continue
        elif mechanic == "duel":
            role = entry.get("role", "")
            if role not in ("winner", "runner-up"):
                errors.append(f"Entry {i}: duel requires role 'winner' or 'runner-up'")
                continue

        # --- Check idem key (ledger + current batch) ---
        raw_key = build_idem_key(mechanic, issue, agent, entry)
        key_hash = idem_key_hash(raw_key)
        if key_hash in idem_keys.get("keys", {}) or key_hash in seen_keys:
            errors.append(f"Entry {i}: idem key already exists -- {raw_key}")
            continue
        seen_keys.add(key_hash)

        # --- Check escrow exists ---
        escrow = escrows.get("active", {}).get(issue)
        if escrow is None:
            errors.append(f"Entry {i}: no escrow found for issue #{issue}")
            continue

        # --- Verify proposed_by matches escrow author ---
        if proposed_by != escrow.get("author"):
            errors.append(
                f"Entry {i}: proposed_by '{proposed_by}' != escrow author "
                f"'{escrow.get('author')}' for issue #{issue}"
            )
            continue

        # --- Check agent exists ---
        if agent not in balances.get("agents", {}):
            errors.append(f"Entry {i}: agent not found in balances: {agent}")
            continue

        # --- Amount validation by mechanic ---
        if mechanic in {"progressive", "linear"}:
            paid_count = simulated_paid_counts.get(issue, escrow.get("paid_count", 0))
            slots = escrow.get("slots", 0)
            if paid_count >= slots:
                errors.append(f"Entry {i}: issue #{issue} -- all {slots} slots already filled")
                continue
            if mechanic == "progressive":
                expected_amount = fib(paid_count + 1)
                label = f"fib({paid_count + 1})"
            else:
                expected_amount = paid_count + 1
                label = f"linear slot {paid_count + 1}"
            if proposed_amount != expected_amount:
                errors.append(
                    f"Entry {i}: issue #{issue} -- proposed {proposed_amount} "
                    f"!= expected {label} = {expected_amount}"
                )
                continue
            # Update simulation state
            simulated_paid_counts[issue] = paid_count + 1

        elif mechanic == "every_good":
            remaining = simulated_remaining.get(issue, escrow["amount"])
            if proposed_amount <= 0:
                errors.append(f"Entry {i}: amount must be > 0")
                continue
            if proposed_amount > remaining:
                errors.append(
                    f"Entry {i}: issue #{issue} -- amount {proposed_amount} "
                    f"exceeds remaining budget {remaining}"
                )
                continue

        elif mechanic in ("ranking", "duel"):
            remaining = simulated_remaining.get(issue, escrow["amount"])
            if proposed_amount <= 0:
                errors.append(f"Entry {i}: amount must be > 0")
                continue
            if proposed_amount > remaining:
                errors.append(
                    f"Entry {i}: issue #{issue} -- amount {proposed_amount} "
                    f"exceeds remaining budget {remaining}"
                )
                continue

        else:  # standard
            if proposed_amount != escrow["amount"]:
                errors.append(
                    f"Entry {i}: issue #{issue} -- proposed {proposed_amount} "
                    f"!= escrow amount {escrow['amount']} (tamper check)"
                )
                continue

        # Track remaining budget for non-progressive mechanics
        if mechanic != "progressive":
            prev_remaining = simulated_remaining.get(issue, escrow["amount"])
            simulated_remaining[issue] = prev_remaining - proposed_amount

        payments.append({
            "entry": entry,
            "issue": issue,
            "agent": agent,
            "amount": proposed_amount,
            "key_hash": key_hash,
            "raw_key": raw_key,
            "proposed_by": proposed_by,
            "mechanic": mechanic,
            "event_at": event_at,
        })

    # =========================================================================
    # CROSS-ENTRY VALIDATION: ranking and duel must exhaust escrow
    # =========================================================================
    batch_totals: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "budget": 0})
    for p in payments:
        if p["mechanic"] in ("ranking", "duel"):
            issue = p["issue"]
            batch_totals[issue]["total"] += p["amount"]
            batch_totals[issue]["budget"] = escrows.get("active", {}).get(issue, {}).get("amount", 0)

    for issue, info in batch_totals.items():
        if info["total"] != info["budget"]:
            errors.append(
                f"Cross-entry: issue #{issue} -- {info['total']} WEA paid "
                f"!= {info['budget']} WEA budget (ranking/duel must exhaust escrow)"
            )

    # =========================================================================
    # ERROR CHECK (all-or-nothing)
    # =========================================================================
    if errors:
        print(f"\n{len(errors)} validation error(s):")
        for err in errors:
            print(f"  ERROR: {err}")
        print("\nFix errors and re-run. No payments processed.")
        return 1

    # --- Preview ---
    print(f"Validated {len(payments)} payment(s):")
    for p in payments:
        label = p["mechanic"]
        if label == "ranking":
            label = f"ranking #{p['entry'].get('rank')}"
        elif label == "duel":
            label = f"duel {p['entry'].get('role')}"
        print(f"  #{p['issue']} -> {p['agent']}: +{p['amount']} WEA ({label})")

    if dry_run:
        print("\n[dry-run] No changes written.")
        return 0

    # =========================================================================
    # EXECUTE PAYMENTS
    # =========================================================================
    ts = now_iso()
    history_lines: list[str] = []

    for p in payments:
        issue = p["issue"]
        agent = p["agent"]
        amount = p["amount"]
        mechanic = p["mechanic"]

        # Update agent balance
        balances["agents"][agent]["balance"] += amount
        balances["agents"][agent]["total_earned"] = (
            balances["agents"][agent].get("total_earned", 0) + amount
        )
        balances["agents"][agent]["tasks_completed"] = (
            balances["agents"][agent].get("tasks_completed", 0) + 1
        )

        # Update escrow
        escrow = escrows["active"][issue]
        escrow["amount"] -= amount

        if mechanic == "progressive":
            escrow["paid_count"] += 1
            if escrow["paid_count"] >= escrow["slots"]:
                del escrows["active"][issue]
        elif escrow["amount"] <= 0:
            # standard, every_good, ranking, duel -- delete when exhausted
            del escrows["active"][issue]

        # Record idem key
        idem_keys.setdefault("keys", {})[p["key_hash"]] = {
            "action": "payment",
            "issue": issue,
            "agent": agent,
            "mechanic": mechanic,
            "timestamp": ts,
        }

        # History entry
        history_entry = {
            "timestamp": ts,
            "event_at": p["event_at"],
            "started_at": started_at,
            "type": "payment",
            "mechanic": mechanic,
            "agent": agent,
            "amount": amount,
            "issue": int(issue),
            "proposed_by": p["proposed_by"],
        }
        # Mechanic-specific history fields
        if mechanic == "ranking":
            history_entry["rank"] = p["entry"].get("rank")
        elif mechanic == "duel":
            history_entry["duel_role"] = p["entry"].get("role")
        # Forward optional cost fields
        for field in ("model", "tokens_input", "tokens_output"):
            if field in p["entry"]:
                history_entry[field] = p["entry"][field]
        history_lines.append(json.dumps(history_entry, ensure_ascii=False))

    # Bump versions + timestamps
    balances["version"] = balances.get("version", 1) + 1
    balances["last_updated"] = ts
    escrows["version"] = escrows.get("version", 1) + 1

    # Write ledger files
    save_json(balances_path, balances)
    save_json(escrows_path, escrows)
    save_json(idem_path, idem_keys)

    # Append history
    history_path.parent.mkdir(parents=True, exist_ok=True)
    with history_path.open("a", encoding="utf-8") as f:
        for line in history_lines:
            f.write(line + "\n")

    # Clear queue
    pending["queue"] = []
    pending["version"] = pending.get("version", 1) + 1
    save_json(pending_path, pending)

    print(f"\nDone. {len(payments)} payment(s) processed. Queue cleared.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Process pending payment queue")
    parser.add_argument("--root", default=None, help="Repository root (auto-detected if omitted)")
    parser.add_argument("--dry-run", action="store_true", help="Validate without writing")
    args = parser.parse_args()

    if args.root:
        root = Path(args.root).resolve()
    else:
        current = Path.cwd().resolve()
        for candidate in [current, *current.parents]:
            if (candidate / "ledger" / "balances.json").exists():
                root = candidate
                break
        else:
            print("Error: cannot find repository root (ledger/balances.json not found).", file=sys.stderr)
            return 2

    return process(root, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
