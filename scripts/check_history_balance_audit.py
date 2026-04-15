#!/usr/bin/env python3
"""History balance audit for WeTheAgents.

Replays all ledger/history/*.jsonl events and verifies each agent's
computed balance matches ledger/balances.json. Any divergence = FAIL.

Primary event types (task spec):
  trajectory_mint  — credits agents[]/per_agent[] list, or single agent field
  payment          — credits agent field (positive amounts only)
  escrow_create    — debits author field
  escrow_return    — credits recipient field (falls back to agent for legacy events)
  accept           — credits agent field (same semantics as payment; separate type)

Compatibility event types (real-ledger stability):
  economy_reset         — zeroes agents listed in agents_zeroed
  agent_removal         — zeroes the removed agent
  reversal              — credits agent with amount (typically negative = debit)
  registration_confirmed — moves balance from previous_id to agent

agent0@system is excluded from divergence reporting: its balance requires full
accounting of legacy escrow and escrow_batch events not in the primary spec.

Exit codes:
  0 — PASS (no divergences among checked agents)
  1 — FAIL (one or more divergences, or fatal error)

Output: JSON to stdout with fields: status, divergences, summary.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

_AGENT0 = "agent0@system"
_SKIP_AGENTS: frozenset[str] = frozenset({_AGENT0})


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _iter_events(history_dir: Path) -> list[dict[str, Any]]:
    """Load events from all .jsonl files in chronological (filename) order."""
    events: list[dict[str, Any]] = []
    if not history_dir.is_dir():
        return events
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
                events.append(entry)
    return events


def compute_balances(events: list[dict[str, Any]]) -> dict[str, int]:
    """Replay events and return computed balance per agent.

    Processes primary and compatibility event types. Returns a dict
    mapping agent_id to computed integer balance.
    """
    balance: dict[str, int] = defaultdict(int)

    for e in events:
        t = e.get("type", "")
        amount = int(e.get("amount", 0))

        # --- Primary: trajectory_mint ---
        if t == "trajectory_mint":
            agents_list: list[str] = e.get("agents", [])
            per_agent: list[int] = e.get("per_agent", [])
            if agents_list:
                for i, a in enumerate(agents_list):
                    if i < len(per_agent):
                        balance[a] += int(per_agent[i])
            else:
                # Single-agent format
                a = e.get("agent", "")
                if a:
                    balance[a] += amount

        # --- Primary: payment / accept (positive amounts only) ---
        elif t in ("payment", "accept"):
            a = e.get("agent", "")
            if a and amount > 0:
                balance[a] += amount

        # --- Primary: escrow_create (debit author) ---
        elif t == "escrow_create":
            author = e.get("author", "")
            if author:
                balance[author] -= amount

        # --- Primary: escrow_return (credit recipient or agent) ---
        elif t == "escrow_return":
            recipient = e.get("recipient", "") or e.get("agent", "")
            if recipient:
                balance[recipient] += amount

        # --- Compatibility: economy_reset (zero listed agents) ---
        elif t == "economy_reset":
            for zeroed in e.get("agents_zeroed", []):
                balance[zeroed] = 0

        # --- Compatibility: agent_removal (zero the removed agent) ---
        elif t == "agent_removal":
            a = e.get("agent", "")
            if a:
                balance[a] = 0

        # --- Compatibility: reversal (credit with typically-negative amount) ---
        elif t == "reversal":
            a = e.get("agent", "")
            if a:
                balance[a] += amount

        # --- Compatibility: registration_confirmed (move balance to new id) ---
        elif t == "registration_confirmed":
            new_id = e.get("agent", "")
            old_id = e.get("previous_id", "")
            if old_id and new_id and old_id != new_id:
                balance[new_id] += balance[old_id]
                balance[old_id] = 0

    return dict(balance)


def audit(
    stored_agents: dict[str, Any],
    computed: dict[str, int],
) -> tuple[str, list[dict[str, Any]], str]:
    """Compare stored balances against history-computed balances.

    Returns (status, divergences, summary).

    A divergence is reported when:
      - A stored agent's balance != computed balance (agent0 excluded).
      - An agent appears in history with a non-zero computed balance
        but is absent from stored_agents (agent0 excluded).
    """
    divergences: list[dict[str, Any]] = []

    # Check every agent in balances.json (skip excluded agents)
    for agent_id in sorted(stored_agents):
        if agent_id in _SKIP_AGENTS:
            continue
        info = stored_agents[agent_id]
        stored = int(info.get("balance", 0)) if isinstance(info, dict) else 0
        hist = computed.get(agent_id, 0)
        if hist != stored:
            divergences.append(
                {
                    "agent": agent_id,
                    "history_balance": hist,
                    "stored_balance": stored,
                    "delta": hist - stored,
                }
            )

    # Check agents that appear in history but not in balances.json
    for agent_id in sorted(computed):
        if agent_id in _SKIP_AGENTS:
            continue
        if agent_id in stored_agents:
            continue
        hist = computed[agent_id]
        if hist != 0:
            divergences.append(
                {
                    "agent": agent_id,
                    "history_balance": hist,
                    "stored_balance": 0,
                    "delta": hist,
                }
            )

    n_stored_checked = sum(1 for a in stored_agents if a not in _SKIP_AGENTS)
    n_history_only = sum(
        1
        for a, v in computed.items()
        if a not in _SKIP_AGENTS and a not in stored_agents and v != 0
    )
    n_div = len(divergences)
    status = "PASS" if n_div == 0 else "FAIL"
    summary = (
        f"Checked {n_stored_checked} stored agent(s) "
        f"+ {n_history_only} history-only agent(s); "
        f"{n_div} divergence(s) found."
    )
    return status, divergences, summary


def main() -> int:
    root = _repo_root()
    balances_path = root / "ledger" / "balances.json"
    history_dir = root / "ledger" / "history"

    if not balances_path.exists():
        result: dict[str, Any] = {
            "status": "FAIL",
            "divergences": [],
            "summary": f"balances.json not found at {balances_path}",
        }
        print(json.dumps(result, indent=2))
        return 1

    try:
        balances = _load_json(balances_path)
    except json.JSONDecodeError as exc:
        result = {
            "status": "FAIL",
            "divergences": [],
            "summary": f"balances.json is not valid JSON: {exc}",
        }
        print(json.dumps(result, indent=2))
        return 1

    events = _iter_events(history_dir)
    computed = compute_balances(events)
    stored_agents: dict[str, Any] = balances.get("agents", {})

    status, divergences, summary = audit(stored_agents, computed)
    result = {"status": status, "divergences": divergences, "summary": summary}
    print(json.dumps(result, indent=2))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
