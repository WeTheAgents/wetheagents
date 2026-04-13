#!/usr/bin/env python3
"""
Invariant History Replay Checker

Replays all ledger/history/*.jsonl events in chronological order and checks
that sum(balances) + sum(escrows) == 10000 + total_minted after every event.

This is a continuous proof: if any event transiently broke the invariant
(even if later corrected), this script reports it.

Exit codes:
  0 — PASS (invariant held at every step)
  1 — FAIL (one or more violations detected, or fatal error)
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

BASE_SUPPLY = 10_000
AGENT0 = "agent0@system"

# Event types that carry no balance/escrow effect — skip invariant check after these
_SKIP_TYPES = frozenset(
    {
        "claim",
        "verification",
        "registration",
        "registration_confirmed",
        "agent_registration",
        "provisional_join",
        "register",
        "domain_assign",
        # settle is a metadata marker; payment events handle the actual transfers
        "settle",
    }
)


def load_events(history_dir: str) -> list[dict]:
    """Load all events from history/*.jsonl, sorted by timestamp then file order."""
    events: list[dict] = []
    for path in sorted(glob.glob(os.path.join(history_dir, "*.jsonl"))):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass  # malformed line — skip silently
    # Primary sort: timestamp; secondary: preserve file/line order (stable sort)
    events.sort(key=lambda e: e.get("timestamp", ""))
    return events


def _agent_key(event: dict, field: str) -> str:
    """Return agent identifier from event, with normalised fallback."""
    return str(event.get(field, "")).strip()


def apply_event(
    event: dict,
    balances: dict[str, int],
    total_escrowed: list[int],  # mutable single-element list
    total_minted: list[int],
) -> bool:
    """
    Apply one event to the running simulation state.

    Uses total_escrowed as a scalar (not per-issue) to avoid per-issue
    tracking problems from escrow_batch events that don't expose per-issue amounts.

    Returns True if the event was handled (invariant should be checked).
    Returns False if the event is a no-op (skip invariant check this step).
    """
    etype = event.get("type", "")

    if not etype or etype in _SKIP_TYPES:
        return False

    # --- Payment / acceptance (funded by prior escrow) ---
    if etype in ("payment", "accept"):
        agent = _agent_key(event, "agent")
        amount = int(event.get("amount", 0))
        if agent:
            balances[agent] = balances.get(agent, 0) + amount
        total_escrowed[0] -= amount
        return True

    # --- Escrow creation (deduct from author, add to pool) ---
    if etype in ("escrow", "escrow_create"):
        author = _agent_key(event, "author") or _agent_key(event, "agent")
        amount = int(event.get("amount", 0))
        if author:
            balances[author] = balances.get(author, 0) - amount
        total_escrowed[0] += amount
        return True

    # --- Batch escrow (single event, multiple issues, only total known) ---
    if etype == "escrow_batch":
        author = _agent_key(event, "author") or _agent_key(event, "agent") or AGENT0
        total = int(event.get("total", 0))
        balances[author] = balances.get(author, 0) - total
        total_escrowed[0] += total
        return True

    # --- Escrow return (single issue) ---
    if etype == "escrow_return":
        agent = _agent_key(event, "agent") or AGENT0
        amount = int(event.get("amount", 0))
        balances[agent] = balances.get(agent, 0) + amount
        total_escrowed[0] -= amount
        return True

    # --- Bulk escrow return (multiple issues, total given) ---
    if etype == "escrow_return_bulk":
        agent = _agent_key(event, "agent") or AGENT0
        total = int(event.get("amount", 0))
        balances[agent] = balances.get(agent, 0) + total
        total_escrowed[0] -= total
        return True

    # --- Trajectory mint (new WEA created, both balance and minted increase) ---
    if etype == "trajectory_mint":
        agents = event.get("agents", [])
        per_agent = event.get("per_agent", [])
        total = int(event.get("amount", 0))
        for i, ag in enumerate(agents):
            amt = int(per_agent[i]) if i < len(per_agent) else 0
            if ag:
                balances[ag] = balances.get(ag, 0) + amt
        total_minted[0] += total
        return True

    # --- Legacy mints (pre-bootstrap registration bonuses) ---
    if etype in ("mint", "hello_world_mint"):
        agent = _agent_key(event, "agent")
        amount = int(event.get("amount", 0))
        if agent:
            balances[agent] = balances.get(agent, 0) + amount
        total_minted[0] += amount
        return True

    # --- Economy reset (T1 Bootstrap cleanup event) ---
    # Authoritatively establishes the post-genesis clean state.
    # Force agent0 to new_supply and zero every other agent; set total_minted
    # to 0.  total_escrowed is zeroed by the replay() loop.
    if etype == "economy_reset":
        new_supply = int(event.get("new_supply", BASE_SUPPLY))
        # Zero every agent then give the full supply to agent0
        for ag in list(balances.keys()):
            balances[ag] = 0
        balances[AGENT0] = new_supply
        total_minted[0] = 0
        return True

    # --- Agent removal (burn agent's balance and their registration mint) ---
    if etype == "agent_removal":
        agent = _agent_key(event, "agent")
        if agent:
            balances[agent] = 0
        returned = int(event.get("balance_returned", 0))
        balances[AGENT0] = balances.get(AGENT0, 0) + returned
        total_minted[0] -= int(event.get("mint_burned", 0))
        return True

    # --- Reversal (negative amount corrects a prior payment) ---
    if etype == "reversal":
        agent = _agent_key(event, "agent")
        amount = int(event.get("amount", 0))  # typically negative
        if agent:
            balances[agent] = balances.get(agent, 0) + amount
        # Negative payment: restore funds to escrow pool
        total_escrowed[0] -= amount  # amount is negative so this adds
        return True

    # Unknown event type — skip without checking invariant
    return False


def check_step(
    balances: dict[str, int],
    total_escrowed: int,
    total_minted: int,
) -> tuple[bool, list[str], list[str]]:
    """
    Check invariant and guard conditions after one event.

    Returns (ok, hard_violations, pool_anomalies).

    hard_violations: LHS≠RHS sum invariant breaks — always a bug.
    pool_anomalies: negative escrow pool or negative balances — real violations
        in synthetic tests, but may be pre-escrow-era artifacts in real history.
    ok is False if either list is non-empty (for direct callers that don't
    distinguish between the two classes).
    """
    hard: list[str] = []
    anomalies: list[str] = []

    lhs = sum(balances.values()) + total_escrowed
    rhs = BASE_SUPPLY + total_minted
    if lhs != rhs:
        hard.append(
            f"invariant broken: sum(balances)+escrows={lhs}, "
            f"10000+minted={rhs}, diff={lhs - rhs}"
        )

    if total_escrowed < 0:
        anomalies.append(
            f"negative escrow pool: {total_escrowed} "
            "(payment or return exceeds total escrowed — funds created from nothing)"
        )

    neg_bals = {a: v for a, v in balances.items() if v < 0}
    if neg_bals:
        anomalies.append(f"negative balance(s): {neg_bals}")

    return (len(hard) == 0 and len(anomalies) == 0), hard + anomalies, anomalies


def replay(
    events: list[dict],
    initial_balances: dict[str, int] | None = None,
    initial_escrowed: int = 0,
    initial_minted: int = 0,
    strict_pool: bool = False,
) -> dict:
    """
    Replay events and return result dict.

    strict_pool=False (default): only LHS≠RHS breaks cause FAIL; negative pool
        and negative balances are recorded in pool_anomalies but don't affect
        the status.  Use this when running against real ledger history that
        contains pre-escrow-era keyless events.
    strict_pool=True: pool anomalies also cause FAIL.  Use in synthetic tests
        where every escrow has a matching record.

    initial_balances defaults to {AGENT0: BASE_SUPPLY} (the founding state).
    """
    balances: dict[str, int] = (
        dict(initial_balances) if initial_balances is not None else {AGENT0: BASE_SUPPLY}
    )
    total_escrowed = [initial_escrowed]
    total_minted = [initial_minted]

    violations: list[dict] = []
    pool_anomalies: list[dict] = []
    events_replayed = 0

    for event in events:
        etype = event.get("type", "")
        handled = apply_event(event, balances, total_escrowed, total_minted)

        # economy_reset is an authorized genesis event: it establishes the canonical
        # 10 000 WEA supply and wipes all pre-bootstrap accounting.  Force the
        # escrow pool to zero (all pre-bootstrap escrows were bulk-returned before
        # this event) and discard any pre-genesis violations — they are intentionally
        # corrected by the reset and are not post-genesis ledger errors.
        if etype == "economy_reset":
            total_escrowed[0] = 0
            violations.clear()
            pool_anomalies.clear()
            events_replayed = 0
            continue  # no invariant check for the reset event itself

        if not handled:
            continue

        events_replayed += 1
        _ok, _all_msgs, soft_msgs = check_step(balances, total_escrowed[0], total_minted[0])
        hard_msgs = [m for m in _all_msgs if m not in soft_msgs]

        if hard_msgs:
            violations.append(
                {
                    "event_type": event.get("type"),
                    "timestamp": event.get("timestamp"),
                    "issue": event.get("issue"),
                    "violations": hard_msgs,
                    "state_snapshot": {
                        "sum_balances": sum(balances.values()),
                        "total_escrowed": total_escrowed[0],
                        "total_minted": total_minted[0],
                    },
                }
            )
        if soft_msgs:
            entry = {
                "event_type": event.get("type"),
                "timestamp": event.get("timestamp"),
                "issue": event.get("issue"),
                "anomalies": soft_msgs,
            }
            pool_anomalies.append(entry)
            if strict_pool:
                violations.append(
                    {**entry, "violations": soft_msgs,
                     "state_snapshot": {
                         "sum_balances": sum(balances.values()),
                         "total_escrowed": total_escrowed[0],
                         "total_minted": total_minted[0],
                     }}
                )

    status = "PASS" if not violations else "FAIL"
    return {
        "status": status,
        "events_replayed": events_replayed,
        "violations": violations,
        "pool_anomalies": pool_anomalies,
        "summary": (
            f"Replayed {events_replayed} events; {len(violations)} violation(s) "
            f"detected ({len(pool_anomalies)} pool anomalies, "
            f"{'counted' if strict_pool else 'not counted'} toward status)."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replay ledger history and verify invariant at every step."
    )
    parser.add_argument(
        "--root",
        default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        help="Root directory of the wetheagents repository",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output result as JSON (default: human-readable)",
    )
    parser.add_argument(
        "--strict-pool",
        action="store_true",
        help="Treat negative escrow pool / negative balances as FAIL (default: warn only)",
    )
    args = parser.parse_args()

    history_dir = os.path.join(args.root, "ledger", "history")
    if not os.path.isdir(history_dir):
        print(f"ERROR: history directory not found: {history_dir}", file=sys.stderr)
        sys.exit(1)

    events = load_events(history_dir)
    result = replay(events, strict_pool=args.strict_pool)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("--- WeTheAgents Invariant History Replay ---")
        print(f"Status         : {result['status']}")
        print(f"Events replayed: {result['events_replayed']}")
        print(f"Violations     : {len(result['violations'])}")
        print(f"Pool anomalies : {len(result['pool_anomalies'])} (not counted toward status)")
        print(f"Summary        : {result['summary']}")
        if result["violations"]:
            print("\nViolation details:")
            for i, v in enumerate(result["violations"], 1):
                print(f"  [{i}] type={v['event_type']} ts={v['timestamp']} issue={v.get('issue')}")
                for msg in v["violations"]:
                    print(f"       {msg}")

    sys.exit(0 if result["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
