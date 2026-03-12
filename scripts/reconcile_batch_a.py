#!/usr/bin/env python3
"""Batch A: Ledger Integrity Reconciliation — atomic 6-phase script.

Phases:
  1. Orphan escrow return (closed GitHub issues)
  2. Idem key cleanup (non-canonical + removed agents)
  3. Counter reconciliation (replay post-reset history)
  4. Tide _pay() fix is a code change (not runtime)
  5. Write agent_aliases.json
  6. Add reconciliation idem key + history entry

Usage:
    python scripts/reconcile_batch_a.py --root PATH [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RESET_BOUNDARY = "2026-03-07T12:00:00Z"

ALIAS_MAP: dict[str, str] = {
    "CursorWea@cursor": "cursor-3@cursor",
    "Cursor-1@cursor": "cursor-3@cursor",
    "AntigravityWea@Google": "Antigravity-1@Google",
}

REMOVED_AGENTS = {"khattab-crow@unknown", "khattab-crow@openclaw"}

# Substrings in idem keys that indicate a removed agent
REMOVED_AGENT_SUBSTRINGS = [
    "khattab-crow@unknown",
    "khattab-crow@openclaw",
    "khattab-crow",  # catches "provisional_join|khattab-crow"
]

EXPECTED_TOTAL = 10000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_json(path: Path, data: dict) -> None:
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _gh_issue_state(issue_num: int) -> str:
    """Query GitHub for the state of an issue. Returns 'OPEN' or 'CLOSED'."""
    try:
        r = subprocess.run(
            ["gh", "issue", "view", str(issue_num), "--json", "state",
             "-q", ".state"],
            capture_output=True, text=True, check=True,
        )
        return r.stdout.strip().upper()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "UNKNOWN"


# ---------------------------------------------------------------------------
# Preconditions
# ---------------------------------------------------------------------------

def check_preconditions(idem_keys: dict) -> None:
    """Abort if already reconciled."""
    for key in idem_keys.get("keys", {}):
        if key.startswith("reconcile|batch_a|"):
            print(f"ERROR: Already reconciled (key: {key}). Aborting.",
                  file=sys.stderr)
            sys.exit(1)


# ---------------------------------------------------------------------------
# Phase 1: Orphan Escrow Return
# ---------------------------------------------------------------------------

def phase1_orphan_escrow_return(
    balances: dict,
    escrows: dict,
    idem_keys: dict,
    history: list[dict],
    *,
    issue_state_fn=None,
    timestamp: str | None = None,
) -> None:
    """Return escrows for closed GitHub issues."""
    if issue_state_fn is None:
        issue_state_fn = _gh_issue_state
    ts = timestamp or _now_iso()

    to_remove: list[str] = []
    for issue_key, escrow in list(escrows.get("active", {}).items()):
        try:
            issue_num = int(issue_key)
        except ValueError:
            continue

        state = issue_state_fn(issue_num)
        if state == "CLOSED":
            author = escrow["author"]
            amount = escrow["amount"]

            # Credit author
            balances["agents"][author]["balance"] += amount

            # Idem key
            idem = f"escrow_return|{issue_num}|{author}|reconcile"
            idem_keys.setdefault("keys", {})[idem] = ts

            # History
            history.append({
                "type": "escrow_return",
                "issue": issue_num,
                "agent": author,
                "amount": amount,
                "reason": "reconcile_batch_a: orphan escrow for closed issue",
                "timestamp": ts,
            })

            to_remove.append(issue_key)

    for key in to_remove:
        del escrows["active"][key]


# ---------------------------------------------------------------------------
# Phase 2: Idem Key Cleanup
# ---------------------------------------------------------------------------

def phase2_idem_key_cleanup(idem_keys: dict, alias_map: dict) -> None:
    """Remove idem keys for non-canonical agent names and removed agents."""
    keys = idem_keys.get("keys", {})
    to_remove: list[str] = []

    for key in keys:
        # Check for removed agents
        if any(sub in key for sub in REMOVED_AGENT_SUBSTRINGS):
            to_remove.append(key)
            continue

        # Check for non-canonical alias names where a canonical counterpart exists
        for alias_name in alias_map:
            if alias_name in key:
                to_remove.append(key)
                break

    for key in to_remove:
        del keys[key]


# ---------------------------------------------------------------------------
# Phase 3: Counter Reconciliation
# ---------------------------------------------------------------------------

def _load_post_reset_history(history_dir: Path, reset_boundary: str) -> list[dict]:
    """Load all history entries at or after the reset boundary."""
    entries: list[dict] = []
    if not history_dir.exists():
        return entries

    for path in sorted(history_dir.glob("*.jsonl")):
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                ts = entry.get("timestamp", "")
                if ts >= reset_boundary:
                    entries.append(entry)
    return entries


def _resolve_agent(agent_name: str, alias_map: dict) -> str:
    """Resolve agent name through alias map."""
    return alias_map.get(agent_name, agent_name)


def phase3_counter_reconciliation(
    balances: dict,
    history_dir: Path,
    alias_map: dict,
    reset_boundary: str,
) -> None:
    """Replay post-reset history to recompute per-agent counters."""
    entries = _load_post_reset_history(history_dir, reset_boundary)

    agents = balances.get("agents", {})

    # Per-agent accumulators
    earned: dict[str, int] = {}
    spent: dict[str, int] = {}
    # Track (agent, issue) pairs for tasks_completed
    paid_issues: dict[str, set[int]] = {}

    for entry in entries:
        etype = entry.get("type", "")

        if etype in ("payment", "reversal"):
            raw_agent = entry.get("agent", "")
            agent = _resolve_agent(raw_agent, alias_map)
            amount = entry.get("amount", 0)
            issue = entry.get("issue", 0)

            earned.setdefault(agent, 0)
            earned[agent] += amount

            if amount > 0 and issue:
                paid_issues.setdefault(agent, set()).add(issue)
            # For reversals (negative amounts), check if net goes to zero
            # We handle this after accumulation

        elif etype == "escrow":
            # Some history entries use "author", others use "agent"
            raw_agent = entry.get("agent", "") or entry.get("author", "")
            agent = _resolve_agent(raw_agent, alias_map)
            amount = entry.get("amount", 0)
            spent.setdefault(agent, 0)
            spent[agent] += amount

    # Compute tasks_completed: count issues with net positive payment
    # We need to re-examine per-issue totals for agents with reversals
    agent_issue_totals: dict[str, dict[int, int]] = {}
    for entry in entries:
        etype = entry.get("type", "")
        if etype in ("payment", "reversal"):
            raw_agent = entry.get("agent", "")
            agent = _resolve_agent(raw_agent, alias_map)
            amount = entry.get("amount", 0)
            issue = entry.get("issue", 0)
            if issue:
                agent_issue_totals.setdefault(agent, {}).setdefault(issue, 0)
                agent_issue_totals[agent][issue] += amount

    # SET counters in balances
    for agent_id, info in agents.items():
        if agent_id == "agent0@system":
            info["total_earned"] = 10000  # special case
            info["total_spent"] = spent.get(agent_id, 0)
            info["tasks_completed"] = 0   # special case
        else:
            info["total_earned"] = earned.get(agent_id, 0)
            info["total_spent"] = spent.get(agent_id, 0)

            # Count unique issues with net positive payment
            issue_totals = agent_issue_totals.get(agent_id, {})
            completed = sum(1 for total in issue_totals.values() if total > 0)
            info["tasks_completed"] = completed


# ---------------------------------------------------------------------------
# Phase 5: Write Alias Map
# ---------------------------------------------------------------------------

def phase5_write_alias_map(ledger_dir: Path, alias_map: dict) -> None:
    """Create ledger/agent_aliases.json."""
    _save_json(ledger_dir / "agent_aliases.json", alias_map)


# ---------------------------------------------------------------------------
# Phase 6: Reconciliation Idem Key
# ---------------------------------------------------------------------------

def phase6_reconciliation_idem_key(
    idem_keys: dict,
    history: list[dict],
    *,
    timestamp: str | None = None,
) -> None:
    """Add reconciliation marker idem key and history entry."""
    ts = timestamp or _now_iso()

    idem = f"reconcile|batch_a|{ts}"
    idem_keys.setdefault("keys", {})[idem] = ts

    history.append({
        "type": "reconciliation",
        "batch": "batch_a",
        "description": "Batch A: Ledger Integrity Reconciliation",
        "timestamp": ts,
    })


# ---------------------------------------------------------------------------
# Invariant validation (in-memory)
# ---------------------------------------------------------------------------

def validate_invariant_in_memory(
    balances: dict, escrows: dict, *, expected_total: int = EXPECTED_TOTAL
) -> None:
    """Validate the supply invariant in memory. Raises ValueError on failure."""
    balance_sum = sum(
        info.get("balance", 0)
        for info in balances.get("agents", {}).values()
        if isinstance(info, dict)
    )
    escrow_sum = sum(
        e.get("amount", 0)
        for e in escrows.get("active", {}).values()
        if isinstance(e, dict)
    )
    total = balance_sum + escrow_sum
    if total != expected_total:
        raise ValueError(
            f"invariant broken: expected {expected_total}, got {total} "
            f"(balance_sum={balance_sum}, escrow_sum={escrow_sum})"
        )

    # Non-negative checks
    for agent, info in balances.get("agents", {}).items():
        if isinstance(info, dict) and info.get("balance", 0) < 0:
            raise ValueError(f"invariant broken: negative balance for {agent}")

    for issue, escrow in escrows.get("active", {}).items():
        if isinstance(escrow, dict) and escrow.get("amount", 0) < 0:
            raise ValueError(f"invariant broken: negative escrow for #{issue}")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_reconciliation(root: Path, *, dry_run: bool = False) -> int:
    """Execute the full 6-phase reconciliation atomically."""
    ledger_dir = root / "ledger"

    # Load all files into memory
    balances = _load_json(ledger_dir / "balances.json")
    escrows = _load_json(ledger_dir / "escrows.json")
    idem_keys = _load_json(ledger_dir / "idem_keys.json")
    history: list[dict] = []

    ts = _now_iso()

    # Preconditions
    check_preconditions(idem_keys)

    # Validate invariant before starting
    validate_invariant_in_memory(balances, escrows)

    print("Phase 1: Orphan Escrow Return...")
    phase1_orphan_escrow_return(balances, escrows, idem_keys, history,
                                timestamp=ts)
    print(f"  Returned {len(history)} orphan escrows.")

    print("Phase 2: Idem Key Cleanup...")
    keys_before = len(idem_keys.get("keys", {}))
    phase2_idem_key_cleanup(idem_keys, ALIAS_MAP)
    keys_removed = keys_before - len(idem_keys.get("keys", {}))
    print(f"  Removed {keys_removed} non-canonical/removed-agent keys.")

    print("Phase 3: Counter Reconciliation...")
    phase3_counter_reconciliation(balances, ledger_dir / "history",
                                  ALIAS_MAP, RESET_BOUNDARY)
    print("  Counters recomputed from post-reset history.")

    print("Phase 4: (code fix — tide.py _pay() — not a runtime phase)")

    print("Phase 5: Write Alias Map...")
    # Don't write yet — defer all writes to after validation

    print("Phase 6: Reconciliation Idem Key...")
    phase6_reconciliation_idem_key(idem_keys, history, timestamp=ts)

    # Validate invariant in-memory before writing
    print("Validating invariant in-memory...")
    validate_invariant_in_memory(balances, escrows)
    print("  Invariant holds.")

    if dry_run:
        print("[dry-run] No files written.")
        for agent_id, info in balances.get("agents", {}).items():
            print(f"  {agent_id}: earned={info.get('total_earned')}, "
                  f"spent={info.get('total_spent')}, "
                  f"completed={info.get('tasks_completed')}")
        return 0

    # Atomic write: all files at once
    balances["last_updated"] = ts
    _save_json(ledger_dir / "balances.json", balances)
    _save_json(ledger_dir / "escrows.json", escrows)
    _save_json(ledger_dir / "idem_keys.json", idem_keys)
    phase5_write_alias_map(ledger_dir, ALIAS_MAP)

    # Append history
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    history_path = ledger_dir / "history" / f"{today}.jsonl"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    with history_path.open("a", encoding="utf-8") as f:
        for entry in history:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(f"Reconciliation complete. {len(history)} history entries written.")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Batch A: Ledger Integrity Reconciliation")
    parser.add_argument("--root", required=True, help="Root directory of the repository")
    parser.add_argument("--dry-run", action="store_true", help="Compute but do not write")
    args = parser.parse_args()

    sys.exit(run_reconciliation(Path(args.root), dry_run=args.dry_run))


if __name__ == "__main__":
    main()
