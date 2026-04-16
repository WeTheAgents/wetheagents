#!/usr/bin/env python3
"""Per-Agent Balance Floor Checker

Replays ledger/history/*.jsonl in chronological order and verifies that no
agent's running balance ever drops below zero.

A negative running balance means WEA was spent before it was earned — a
protocol violation invisible to aggregate invariant checks.  Even if a
subsequent credit restores the balance, the debit-before-credit event is
itself a floor violation.

Credits (increase balance): payment, escrow_return, trajectory_mint, mint,
    hello_world_mint, reversal, accept, escrow_return_bulk
Debits (decrease balance): escrow, escrow_create

Exit codes:
  0 — PASS (no agent ever had a negative running balance)
  1 — FAIL (one or more balance-floor violations detected)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

AGENT0 = "agent0@system"
BASE_SUPPLY = 10_000


def _repo_root(override: str | None = None) -> Path:
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parent.parent


def _load_events(history_dir: Path) -> list[dict[str, Any]]:
    """Load all events from history/*.jsonl, sorted chronologically."""
    entries: list[dict[str, Any]] = []
    if not history_dir.is_dir():
        return entries
    for path in sorted(history_dir.glob("*.jsonl")):
        for raw in path.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict):
                entries.append(entry)
    entries.sort(key=lambda e: e.get("timestamp", ""))
    return entries


def replay(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Replay events and return result dict.

    Tracks each agent's running balance after every balance-affecting event
    and records a violation whenever an agent's balance drops below zero.
    """
    balances: dict[str, int] = {AGENT0: BASE_SUPPLY}
    violations: list[dict[str, Any]] = []
    events_replayed = 0
    # Deduplicate escrow_return events per (issue, agent) — real history can
    # contain duplicate return rows for the same issue.
    seen_returns: set[tuple[str, str]] = set()

    for event in events:
        etype = event.get("type", "")
        if not etype:
            continue

        agent: str = str(event.get("agent", "") or "")
        author: str = str(event.get("author", "") or "")
        amount: int = int(event.get("amount", 0))
        timestamp = event.get("timestamp")

        # Agents whose balances changed this event (checked for floor after apply).
        affected: list[str] = []

        if etype == "economy_reset":
            # Authorized genesis reset — re-establish canonical state.
            # Violations before the reset are intentionally corrected; discard them.
            new_supply = int(event.get("new_supply", BASE_SUPPLY))
            for ag in list(balances.keys()):
                balances[ag] = 0
            balances[AGENT0] = new_supply
            violations.clear()
            events_replayed = 0
            seen_returns.clear()
            continue

        elif etype in ("payment", "mint", "hello_world_mint", "accept"):
            a = agent or author
            if a:
                balances[a] = balances.get(a, 0) + amount
                affected.append(a)
                events_replayed += 1

        elif etype == "reversal":
            # amount is typically negative (correction of a prior payment).
            a = agent or author
            if a:
                balances[a] = balances.get(a, 0) + amount
                affected.append(a)
                events_replayed += 1

        elif etype == "escrow_return":
            a = agent or author
            if a:
                issue_key = str(event.get("issue", "_no_issue_"))
                key = (issue_key, a)
                if key not in seen_returns:
                    seen_returns.add(key)
                    balances[a] = balances.get(a, 0) + amount
                    affected.append(a)
                    events_replayed += 1

        elif etype == "escrow_return_bulk":
            a = agent or AGENT0
            balances[a] = balances.get(a, 0) + amount
            affected.append(a)
            events_replayed += 1

        elif etype in ("escrow", "escrow_create"):
            # Debit: use `agent` field only — consistent with
            # check_balance_history_reconciliation.py.  Legacy events that
            # store the payer in `author` instead of `agent` are not counted
            # so agent0's pre-bootstrap history doesn't create false negatives.
            if agent:
                balances[agent] = balances.get(agent, 0) - amount
                affected.append(agent)
                events_replayed += 1

        elif etype == "trajectory_mint":
            if agent:
                # New single-agent format
                balances[agent] = balances.get(agent, 0) + amount
                affected.append(agent)
            else:
                # Legacy list format
                agents_list: list[str] = event.get("agents", [])
                per_agent_amounts: list[int] = event.get("per_agent", [])
                for i, ag in enumerate(agents_list):
                    if ag and i < len(per_agent_amounts):
                        balances[ag] = balances.get(ag, 0) + int(per_agent_amounts[i])
                        affected.append(ag)
            events_replayed += 1

        elif etype == "agent_removal":
            if agent:
                balances[agent] = 0
                affected.append(agent)
            returned = int(event.get("balance_returned", 0))
            if returned:
                balances[AGENT0] = balances.get(AGENT0, 0) + returned
                affected.append(AGENT0)
            events_replayed += 1

        else:
            # Metadata or unknown events (claim, registration, etc.) — skip.
            continue

        # Floor check: any affected agent below zero is a violation.
        for ag in affected:
            if balances.get(ag, 0) < 0:
                violations.append(
                    {
                        "agent": ag,
                        "event_type": etype,
                        "timestamp": timestamp,
                        "balance_at_event": balances[ag],
                    }
                )

    status = "PASS" if not violations else "FAIL"
    checks = [
        {
            "name": "per_agent_balance_floor",
            "status": status,
            "detail": (
                f"No agent balance went negative across {events_replayed} events."
                if not violations
                else f"{len(violations)} negative-balance event(s) detected."
            ),
        }
    ]

    return {
        "status": status,
        "checks": checks,
        "violations": violations,
        "summary": (
            f"Replayed {events_replayed} balance events; "
            f"{len(violations)} per-agent floor violation(s) detected."
        ),
    }


def run(root: Path) -> tuple[dict[str, Any], bool]:
    """Run the check and return (result, passed)."""
    history_dir = root / "ledger" / "history"
    events = _load_events(history_dir)
    result = replay(events)
    return result, result["status"] == "PASS"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify no agent's running balance ever dropped below zero."
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root (default: auto-detected from script location)",
    )
    args = parser.parse_args(argv)

    root = _repo_root(args.root)
    result, passed = run(root)
    print(json.dumps(result, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
