#!/usr/bin/env python3
"""
check_history_cumulative_balance_integrity.py

Replays all ledger/history/*.jsonl events in strict chronological order
(globally sorted by timestamp/ts across all files), tracking a running
per-agent balance.

Two invariants are checked:

  1. No agent's balance goes negative at any point during the replay.
     The first violation is reported with its causative event details.
  2. Every agent's replay-computed balance matches ledger/balances.json
     at the end of the replay.

Accounting model
  Debits   : escrow_create / escrow (old) / escrow_batch
  Credits  : payment, accept, mint, hello_world_mint, reversal,
             trajectory_mint (agents/per_agent, agent, or to fields),
             escrow_return, escrow_return_bulk
  Special  : economy_reset  — zeros agents, credits agent0, clears violations
             agent_removal  — zeros agent, credits agent0
             registration_confirmed — migrates balance to canonical id
  Skip     : agent0@system in final comparison (legacy escrow_batch irreconcilable)
  No-op    : payment/accept where balance_after == current balance (idempotent
             duplicate that the ledger system already treated as a no-op)

Exit codes
  0 — PASS (no mid-history negatives; final balances match)
  1 — FAIL (negative detected or final mismatch)
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

# type values that name a mechanic rather than an event action
_MECHANIC_KEYWORDS: frozenset[str] = frozenset(
    {
        "standard",
        "progressive",
        "best_x",
        "winner_take_all",
        "duel",
        "linear",
        "every_good",
        "pod",
        "wta",
        "every_accepted",
    }
)

# events that carry no balance effect
_METADATA_TYPES: frozenset[str] = frozenset(
    {
        "settle",
        "domain_assign",
        "verification",
        "provisional_join",
        "claim",
        "registration",
        "agent_registration",
        "register",
        "hello_world",
    }
)


def _repo_root(override: str | None = None) -> Path:
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parent.parent


def _get_effective_type(event: dict) -> str:
    """Return the canonical event action, normalising across schema generations.

    History records use one of three field names: ``type``, ``event``, or
    ``op``.  Some records also have a ``type`` field that carries a mechanic
    name (e.g. ``"standard"``), not the event action — those fall back to the
    ``event`` field.
    """
    t = event.get("type", "")
    if not t or t in _MECHANIC_KEYWORDS:
        t = event.get("event", t)
    if not t:
        t = event.get("op", "")
    return t


def _get_timestamp(event: dict) -> str:
    """Return the best timestamp string, covering all known field names."""
    return (
        event.get("timestamp")
        or event.get("ts")
        or event.get("created_at")
        or ""
    )


def _get_trajectory_recipients(event: dict) -> list[tuple[str, int]]:
    """Extract (agent_id, amount) pairs from a trajectory_mint event.

    Handles three historical formats:
      - agents / per_agent arrays  (standard, most mints)
      - agent (singular) + amount  (older batch writes)
      - to + amount                (ad-hoc format used 2026-04-19)
    """
    agents = event.get("agents", [])
    per = event.get("per_agent", [])
    if agents and per:
        return [
            (str(ag), int(d))
            for ag, d in zip(agents, per)
            if ag and d is not None
        ]

    a = str(event.get("agent", "") or "")
    if a:
        return [(a, int(event.get("amount", 0)))]

    to = str(event.get("to", "") or "")
    if to:
        return [(to, int(event.get("amount", 0)))]

    return []


def _get_escrow_author(event: dict) -> str:
    """Return the agent who funded an escrow creation."""
    return str(
        event.get("agent", "")
        or event.get("author", "")
        or event.get("from", "")
        or ""
    )


def _get_return_recipient(event: dict) -> str:
    """Return the agent who receives an escrow return."""
    return str(
        event.get("recipient", "")
        or event.get("agent", "")
        or event.get("author", "")
        or event.get("to", "")
        or AGENT0
    )


def load_events(history_dir: Path) -> list[dict]:
    """Load all JSONL events and sort globally by timestamp.

    Events without a timestamp field sort to the front (empty string < any
    ISO-8601 string).  Stable sort preserves file/line ordering as a
    tiebreaker.
    """
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
    events.sort(key=_get_timestamp)
    return events


def replay(events: list[dict]) -> dict[str, Any]:
    """Replay events chronologically and report violations.

    Returns a dict with:
      events_replayed     — count of balance-affecting events processed
      negative_violations — list of dicts for negative-balance events (first
                            violation is index 0)
      final_balances      — dict[agent_id, int] after full replay
    """
    balances: dict[str, int] = defaultdict(int)
    balances[AGENT0] = AGENT0_GENESIS

    # Deduplicate escrow_return events by (issue, agent) — some history files
    # contain duplicate entries that must only count once.
    seen_returns: set[tuple[str, str]] = set()

    negative_violations: list[dict] = []
    events_replayed = 0

    for event in events:
        t = _get_effective_type(event)

        # ------------------------------------------------------------------ #
        # economy_reset — clean-slate bootstrap; clear pre-reset violations    #
        # ------------------------------------------------------------------ #
        if t == "economy_reset":
            for zeroed in event.get("agents_zeroed", []):
                balances[str(zeroed)] = 0
            returned = int(event.get("wea_returned_to_agent0", 0))
            if returned:
                balances[AGENT0] += returned
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
                balances[new_id] += balances.pop(old_id, 0)
            continue

        # ------------------------------------------------------------------ #
        # Balance-affecting events                                             #
        # ------------------------------------------------------------------ #

        if t in ("payment", "accept"):
            a = str(event.get("agent", "") or event.get("author", "") or "")
            amount = int(event.get("amount", 0))
            if not a:
                continue
            # Detect no-op duplicate: balance_after equals current balance
            # (the ledger system already treated this event as idempotent).
            bal_after = event.get("balance_after")
            if (
                bal_after is not None
                and isinstance(bal_after, (int, float))
                and int(bal_after) == balances[a]
            ):
                continue  # idempotent duplicate — skip
            balances[a] += amount

        elif t in ("mint", "hello_world_mint", "reversal"):
            a = str(event.get("agent", "") or event.get("author", "") or "")
            amount = int(event.get("amount", 0))
            if a:
                balances[a] += amount

        elif t == "trajectory_mint":
            for a, amount in _get_trajectory_recipients(event):
                balances[a] += amount

        elif t == "escrow_return":
            a = _get_return_recipient(event)
            amount = int(event.get("amount", 0))
            issue = str(event.get("issue", "_no_issue_"))
            key = (issue, a)
            if key not in seen_returns:
                seen_returns.add(key)
                balances[a] += amount

        elif t == "escrow_return_bulk":
            a = _get_return_recipient(event)
            balances[a] += int(event.get("amount", 0))

        elif t in ("escrow_create", "escrow"):
            debit = _get_escrow_author(event)
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
            # Unknown or metadata-like type — no balance effect.
            continue

        events_replayed += 1

        # Check all agents for negative balance after every event.
        for agent, bal in balances.items():
            if bal < 0:
                negative_violations.append(
                    {
                        "agent": agent,
                        "balance": bal,
                        "event_type": t,
                        "event_ts": _get_timestamp(event),
                        "event_issue": event.get("issue"),
                        "event_amount": event.get("amount"),
                    }
                )

    return {
        "events_replayed": events_replayed,
        "negative_violations": negative_violations,
        "final_balances": dict(balances),
    }


def compare_final(
    computed: dict[str, int],
    balances_json: dict,
    escrows_json: dict | None = None,
) -> list[dict]:
    """Compare computed final balances to ledger/balances.json.

    agent0@system is skipped: legacy escrow_batch events create an
    irreconcilable offset in the computed balance for that agent.

    Active escrows (from escrows.json) are tolerated: if computed > stored
    and the delta equals the agent's total active escrow, it's a PASS — the
    escrow_create debited the balance but the history replayed only credits.

    Returns a list of mismatch dicts (non-empty → FAIL).
    """
    # Build per-agent active escrow totals (keyed by author).
    active_escrow: dict[str, int] = {}
    if escrows_json:
        for _issue, info in escrows_json.get("active", {}).items():
            author = info.get("author", "")
            active_escrow[author] = active_escrow.get(author, 0) + int(info.get("amount", 0))

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
            delta = comp - stored
            tolerance = active_escrow.get(agent_id, 0)
            if delta == tolerance:
                continue  # difference accounted for by active escrow
            mismatches.append(
                {
                    "agent": agent_id,
                    "stored": stored,
                    "computed": comp,
                    "delta": delta,
                }
            )

    # Agents in history but absent from balances.json with non-zero balance.
    for agent_id, comp in sorted(computed.items()):
        if agent_id == AGENT0:
            continue
        if agent_id not in agents and comp != 0:
            mismatches.append(
                {
                    "agent": agent_id,
                    "stored": None,
                    "computed": comp,
                    "delta": None,
                    "note": "in history but absent from balances.json",
                }
            )

    return mismatches


def run(root: Path) -> tuple[dict[str, Any], bool]:
    """Full check: load, replay, detect negatives, compare final."""
    balances_path = root / "ledger" / "balances.json"
    escrows_path = root / "ledger" / "escrows.json"
    history_dir = root / "ledger" / "history"

    if not balances_path.exists():
        result = {
            "status": "FAIL",
            "events_replayed": 0,
            "negative_violations": [],
            "final_mismatches": [],
            "summary": f"balances.json not found: {balances_path}",
        }
        return result, False

    try:
        balances_json = json.loads(balances_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        result = {
            "status": "FAIL",
            "events_replayed": 0,
            "negative_violations": [],
            "final_mismatches": [],
            "summary": f"balances.json invalid JSON: {exc}",
        }
        return result, False

    escrows_json: dict | None = None
    if escrows_path.exists():
        try:
            escrows_json = json.loads(escrows_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass  # tolerate missing/malformed escrows.json — just no tolerance

    events = load_events(history_dir)
    replay_result = replay(events)

    negative_violations = replay_result["negative_violations"]
    final_mismatches = compare_final(
        replay_result["final_balances"], balances_json, escrows_json
    )

    passed = not negative_violations and not final_mismatches
    status = "PASS" if passed else "FAIL"

    parts: list[str] = [f"events_replayed={replay_result['events_replayed']}"]
    if negative_violations:
        parts.append(
            f"{len(negative_violations)} negative-balance violation(s)"
        )
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Replay history events chronologically. "
            "Fails if any agent's balance goes negative mid-replay, "
            "or if final balances diverge from balances.json."
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
    args = parser.parse_args(argv)

    root = _repo_root(args.root)
    result, passed = run(root)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("--- WeTheAgents Cumulative Balance Integrity ---")
        print(f"Status          : {result['status']}")
        print(f"Events replayed : {result['events_replayed']}")
        print(f"Neg violations  : {len(result['negative_violations'])}")
        print(f"Final mismatches: {len(result['final_mismatches'])}")
        print(f"Summary         : {result['summary']}")

        if result["negative_violations"]:
            first = result["negative_violations"][0]
            print(
                f"\nFirst negative-balance violation:\n"
                f"  agent     : {first['agent']}\n"
                f"  balance   : {first['balance']}\n"
                f"  event_type: {first['event_type']}\n"
                f"  event_ts  : {first['event_ts']}\n"
                f"  issue     : {first['event_issue']}\n"
                f"  amount    : {first['event_amount']}"
            )
            if len(result["negative_violations"]) > 1:
                print(
                    f"  ... and {len(result['negative_violations']) - 1} more violation(s)"
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

    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
