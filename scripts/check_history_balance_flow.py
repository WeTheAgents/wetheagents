#!/usr/bin/env python3
"""
check_history_balance_flow.py

Replays all ledger/history/*.jsonl events in chronological order, maintaining
a running per-agent balance. Detects two classes of history-ledger drift:

  1. Any agent's balance goes negative at any point mid-history (spending
     more than earned — an integrity violation even if later corrected).
  2. Any agent's final computed balance diverges from ledger/balances.json
     (history and ledger have drifted apart).

What this catches that other checks miss:
  - check_invariant_history_replay only checks global sum invariant; negative
    per-agent balances are pool_anomalies (warnings, not hard failures).
  - check_balance_history_reconciliation only checks final balances; it cannot
    detect a negative mid-history balance that is later corrected.

Accounting model (consistent with check_balance_history_reconciliation):
  Credits  : payment, mint, hello_world_mint, reversal, accept,
             trajectory_mint, escrow_return, escrow_return_bulk,
             economy_reset.wea_returned_to_agent0, agent_removal.balance_returned
  Debits   : escrow (agent field only), escrow_create (agent then author),
             escrow_batch (author or agent)
  Special  : economy_reset resets balances; registration_confirmed migrates
             balance from previous_id to canonical id.
  Skip     : agent0@system final comparison (legacy escrow_batch irreconcilable offsets)

Exit codes:
  0 — PASS (no negative mid-history balances; all final balances match)
  1 — FAIL (negative balance detected, or final mismatch found)
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

AGENT0 = "agent0@system"
AGENT0_GENESIS = 10_000

# When 'type' holds a mechanic name rather than an event action, use 'event' instead.
_MECHANIC_KEYWORDS: frozenset[str] = frozenset({
    "standard", "progressive", "best_x", "winner_take_all",
    "duel", "linear", "every_good", "pod", "wta", "every_accepted",
})

# Pure metadata events — no balance changes, safe to skip.
_METADATA_TYPES: frozenset[str] = frozenset({
    "settle",
    "domain_assign",
    "verification",
    "provisional_join",
    "claim",
    "registration",
    "agent_registration",
    "register",
})


def _repo_root(override: str | None = None) -> Path:
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parent.parent


def _normalize_type(event: dict) -> str:
    """Return the canonical event action type, handling mechanic-as-type encoding."""
    t = event.get("type", "")
    if not t or t in _MECHANIC_KEYWORDS:
        t = event.get("event", t)
    return t


def load_events(history_dir: Path) -> list[dict]:
    """Load all events from history/*.jsonl, sorted by filename (chronological)."""
    events: list[dict] = []
    if not history_dir.is_dir():
        return events
    for path in sorted(history_dir.glob("*.jsonl")):
        for raw in path.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                e = json.loads(raw)
                if isinstance(e, dict):
                    events.append(e)
            except json.JSONDecodeError:
                pass
    return events


def replay(events: list[dict]) -> dict[str, Any]:
    """
    Replay events and track running per-agent balance.

    Returns:
      events_replayed: count of balance-affecting events processed
      negative_violations: list of dicts for each event that left a balance negative
      final_balances: dict[agent, int] after all events
    """
    balances: dict[str, int] = defaultdict(int)
    balances[AGENT0] = AGENT0_GENESIS

    # Deduplicate escrow_return by (issue, agent) — some history files contain
    # duplicate entries for the same return that must only count once.
    seen_returns: set[tuple[str, str]] = set()

    # Deduplicate payment events by (issue, agent, amount, balance_after).
    # A duplicate write where all four fields match is a no-op replay: both
    # rows post-state the same balance_after, proving only one mutation
    # applied. Legitimate multi-payment per (issue, agent) always advances
    # balance_after, so this tight signature does not over-collapse.
    seen_payments: set[tuple[str, str, int, int]] = set()

    negative_violations: list[dict] = []
    events_replayed = 0

    for event in events:
        t = _normalize_type(event)

        # ------------------------------------------------------------------ #
        # economy_reset — authoritative bootstrap clean-slate                  #
        # ------------------------------------------------------------------ #
        if t == "economy_reset":
            for zeroed in event.get("agents_zeroed", []):
                balances[str(zeroed)] = 0
            returned = int(event.get("wea_returned_to_agent0", 0))
            if returned:
                balances[AGENT0] += returned
            # Pre-bootstrap violations are intentionally corrected by the reset.
            negative_violations.clear()
            seen_returns.clear()
            events_replayed = 0
            continue

        # ------------------------------------------------------------------ #
        # Metadata — no balance effect                                         #
        # ------------------------------------------------------------------ #
        if t in _METADATA_TYPES:
            continue

        # ------------------------------------------------------------------ #
        # Identity migration                                                   #
        # ------------------------------------------------------------------ #
        if t == "registration_confirmed":
            new_id = str(event.get("agent", "") or "")
            old_id = str(event.get("previous_id", "") or "")
            if old_id and new_id and old_id != new_id:
                balances[new_id] += balances[old_id]
                balances[old_id] = 0
            continue

        # ------------------------------------------------------------------ #
        # Balance-affecting events                                             #
        # ------------------------------------------------------------------ #

        if t in ("payment", "mint", "hello_world_mint", "reversal", "accept"):
            a = str(event.get("agent", "") or event.get("author", "") or "")
            amount = int(event.get("amount", 0))
            if a:
                if t == "payment" and "balance_after" in event:
                    issue = str(event.get("issue", "_no_issue_"))
                    key = (issue, a, amount, int(event.get("balance_after", 0)))
                    if key in seen_payments:
                        continue
                    seen_payments.add(key)
                balances[a] += amount

        elif t == "trajectory_mint":
            # Three historical formats are supported:
            #   1. Single-agent (modern): "agent" + "amount"
            #   2. Single-agent (legacy heartbeat): "to" + "amount"
            #   3. Multi-agent: "agents" list + "per_agent" list
            # Without the `to` fallback, legacy mints are silently dropped,
            # leaving the agent's computed balance short by the mint amount.
            a = str(event.get("agent", "") or event.get("to", "") or "")
            amount = int(event.get("amount", 0))
            if a:
                balances[a] += amount
            else:
                for i, ag in enumerate(event.get("agents", [])):
                    per = event.get("per_agent", [])
                    if i < len(per):
                        balances[str(ag)] += int(per[i])

        elif t == "escrow_return":
            a = str(
                event.get("recipient", "")
                or event.get("agent", "")
                or event.get("author", "")
                or AGENT0
            )
            amount = int(event.get("amount", 0))
            issue = str(event.get("issue", "_no_issue_"))
            key = (issue, a)
            if key not in seen_returns:
                seen_returns.add(key)
                balances[a] += amount

        elif t == "escrow_return_bulk":
            a = str(
                event.get("recipient", "")
                or event.get("agent", "")
                or event.get("author", "")
                or AGENT0
            )
            balances[a] += int(event.get("amount", 0))

        elif t == "escrow":
            # Only the explicit 'agent' field counts as a debit (not 'author').
            # This matches the accounting model of check_balance_history_reconciliation.
            debit = str(event.get("agent", "") or "")
            if debit:
                balances[debit] -= int(event.get("amount", 0))

        elif t == "escrow_create":
            # 'agent' first, then 'author' fallback for legacy rows.
            debit = str(event.get("agent", "") or event.get("author", "") or "")
            if debit:
                balances[debit] -= int(event.get("amount", 0))

        elif t == "escrow_batch":
            debit = str(
                event.get("author", "")
                or event.get("agent", "")
                or AGENT0
            )
            balances[debit] -= int(event.get("total", 0))

        elif t == "agent_removal":
            agent = str(event.get("agent", "") or "")
            if agent:
                balances[agent] = 0
            returned = int(event.get("balance_returned", 0))
            if returned:
                balances[AGENT0] += returned

        else:
            # Unknown event type — no balance effect, don't count.
            continue

        events_replayed += 1

        # Check for negative balances after every balance-affecting event.
        for agent, bal in balances.items():
            if bal < 0:
                negative_violations.append({
                    "agent": agent,
                    "balance": bal,
                    "event_type": event.get("type", ""),
                    "timestamp": event.get("timestamp", ""),
                    "issue": event.get("issue"),
                })

    return {
        "events_replayed": events_replayed,
        "negative_violations": negative_violations,
        "final_balances": dict(balances),
    }


def compare_final(
    computed: dict[str, int],
    balances_json: dict,
) -> list[dict]:
    """
    Compare computed final balances to balances.json.

    agent0@system is SKIP'd: legacy escrow_batch events make its balance
    irreconcilable from history alone (same policy as
    check_balance_history_reconciliation).

    Returns a list of mismatch dicts for FAIL-level discrepancies.
    """
    mismatches: list[dict] = []
    agents = balances_json.get("agents", {})
    if not isinstance(agents, dict):
        return [{"error": "balances.json 'agents' field is not a dict"}]

    for agent_id, info in sorted(agents.items()):
        if agent_id == AGENT0:
            continue
        stored = int(info.get("balance", 0)) if isinstance(info, dict) else 0
        comp = computed.get(agent_id, 0)
        if comp != stored:
            mismatches.append({
                "agent": agent_id,
                "stored": stored,
                "computed": comp,
                "delta": comp - stored,
            })

    # Flag agents with non-zero computed balance absent from balances.json.
    for agent_id, comp in sorted(computed.items()):
        if agent_id == AGENT0:
            continue
        if agent_id not in agents and comp != 0:
            mismatches.append({
                "agent": agent_id,
                "stored": None,
                "computed": comp,
                "delta": None,
                "note": "agent present in history but absent from balances.json",
            })

    return mismatches


def run(root: Path) -> tuple[dict[str, Any], bool]:
    """Full check: load history, replay, detect negatives, compare final."""
    balances_path = root / "ledger" / "balances.json"
    history_dir = root / "ledger" / "history"

    if not balances_path.exists():
        return {
            "status": "FAIL",
            "events_replayed": 0,
            "negative_violations": [],
            "final_mismatches": [],
            "summary": f"balances.json not found: {balances_path}",
        }, False

    try:
        balances_json = json.loads(balances_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {
            "status": "FAIL",
            "events_replayed": 0,
            "negative_violations": [],
            "final_mismatches": [],
            "summary": f"balances.json invalid JSON: {exc}",
        }, False

    events = load_events(history_dir)
    replay_result = replay(events)

    negative_violations = replay_result["negative_violations"]
    final_mismatches = compare_final(replay_result["final_balances"], balances_json)

    passed = (not negative_violations) and (not final_mismatches)
    status = "PASS" if passed else "FAIL"

    parts: list[str] = [f"events_replayed={replay_result['events_replayed']}"]
    if negative_violations:
        parts.append(f"{len(negative_violations)} negative-balance violation(s)")
    if final_mismatches:
        parts.append(f"{len(final_mismatches)} final-balance mismatch(es)")
    if passed:
        parts.append("all checks passed")

    return {
        "status": status,
        "events_replayed": replay_result["events_replayed"],
        "negative_violations": negative_violations,
        "final_mismatches": final_mismatches,
        "summary": "; ".join(parts),
    }, passed


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Replay history balance flow. "
            "Fails on negative mid-history balances or final mismatch with balances.json."
        )
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root (default: auto-detected from script location)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output result as JSON",
    )
    args = parser.parse_args()

    root = _repo_root(args.root)
    result, passed = run(root)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("--- WeTheAgents History Balance Flow ---")
        print(f"Status          : {result['status']}")
        print(f"Events replayed : {result['events_replayed']}")
        print(f"Neg violations  : {len(result['negative_violations'])}")
        print(f"Final mismatches: {len(result['final_mismatches'])}")
        print(f"Summary         : {result['summary']}")
        if result["negative_violations"]:
            print("\nNegative balance violations (first 10):")
            for v in result["negative_violations"][:10]:
                print(
                    f"  {v['agent']}: balance={v['balance']}"
                    f" after {v['event_type']} at {v['timestamp']}"
                    f" issue={v['issue']}"
                )
        if result["final_mismatches"]:
            print("\nFinal balance mismatches:")
            for m in result["final_mismatches"]:
                note = m.get("note", "")
                print(
                    f"  {m['agent']}: stored={m.get('stored')}"
                    f" computed={m.get('computed')}"
                    f" delta={m.get('delta')}"
                    + (f" ({note})" if note else "")
                )

    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
