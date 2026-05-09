#!/usr/bin/env python3
"""Earnings metadata consistency check for WeTheAgents.

Verifies that the ``total_earned`` and ``total_spent`` metadata fields in
``ledger/balances.json`` match what ``ledger/history/*.jsonl`` actually shows
for each agent.

This complements ``check_balance_history_reconciliation.py``. The balance
reconciler verifies the replayed final balance; this script verifies that the
metadata fields ``total_earned`` and ``total_spent`` also match history. A
corrupt ledger where both totals are inflated by the same amount can satisfy
the balance check but still fails here.

Computation rules
-----------------
``total_earned`` is the sum of:
- ``trajectory_mint`` — per_agent[i] for multi-agent format; ``amount`` for
  single-agent format (agent field, no agents[] list).
- ``payment`` — amount (positive only) when agent matches the event's ``agent``
  field.
- ``accept`` — amount when agent matches the event's ``agent`` field.
- ``escrow_return`` — amount when agent is the recipient AND the issue had a
  matching ``escrow_create`` (modern-format escrows only; old-format ``escrow``
  events that pre-date ``escrow_create`` are excluded from this accounting).

``total_spent`` is the sum of:
- ``escrow_create`` — amount debited from the ``author``.

Compatibility events (``economy_reset``, ``agent_removal``, ``reversal``,
``registration_confirmed``) affect the running balance tracked by T1S14 but
are NOT part of the earned/spent metadata spec; they are deliberately ignored
here.

Exclusions
----------
``agent0@system`` is excluded from divergence reporting (its balance accounting
requires full legacy escrow/escrow_batch history outside this spec).

Missing agents
--------------
Agents that appear in history (computed earned/spent > 0) but are absent from
``balances.json`` emit a warning; they do not cause FAIL.

Exit codes
----------
0 — PASS (no divergences)
1 — FAIL (one or more divergences, or fatal error)

Output: JSON to stdout with fields: status, divergences, warnings, summary.
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


def compute_earned_spent(
    events: list[dict[str, Any]],
) -> tuple[dict[str, int], dict[str, int]]:
    """Replay events and return (earned, spent) dicts per agent.

    Only processes primary event types per the spec.  Compatibility events
    that adjust the running balance (economy_reset, etc.) are ignored because
    they do not affect the ``total_earned``/``total_spent`` metadata fields.

    Returns two dicts mapping agent_id → computed integer value.
    """
    earned: dict[str, int] = defaultdict(int)
    spent: dict[str, int] = defaultdict(int)

    # Track (issue, agent, amount, balance_after) for payment dedup. Some
    # history files contain a duplicate payment write where all four fields
    # are identical; both rows post-state the same balance_after, so only
    # one mutation actually applied. Legitimate multi-payment per
    # (issue, agent) always advances balance_after, so this signature is safe.
    seen_payments: set[tuple[Any, str, int, int]] = set()

    # First pass: collect issues that have a modern escrow_create event.
    # Only escrow_return events for these issues are eligible to count toward
    # total_earned.  Old-format ``escrow`` events pre-date escrow_create and
    # must not influence the earned/spent metadata accounting.
    escrow_create_issues: set[int | None] = set()
    for e in events:
        if e.get("type") == "escrow_create":
            escrow_create_issues.add(e.get("issue"))

    # Second pass: compute earned and spent.
    for e in events:
        t = e.get("type", "")
        amount = int(e.get("amount", 0))

        # --- trajectory_mint ---
        if t == "trajectory_mint":
            agents_list: list[str] = e.get("agents", [])
            per_agent: list[int] = e.get("per_agent", [])
            if agents_list:
                # Multi-agent format: each slot has an explicit per-agent amount.
                for i, a in enumerate(agents_list):
                    if i < len(per_agent):
                        earned[a] += int(per_agent[i])
            else:
                # Single-agent format: agent + amount fields.
                a = e.get("agent", "") or e.get("to", "")
                if a:
                    earned[a] += amount

        # --- payment / accept ---
        elif t in ("payment", "accept"):
            a = e.get("agent", "")
            if a and amount > 0:
                if t == "payment" and "balance_after" in e:
                    key = (e.get("issue"), a, amount, int(e.get("balance_after", 0)))
                    if key in seen_payments:
                        continue
                    seen_payments.add(key)
                earned[a] += amount

        # --- escrow_return (modern escrows only) ---
        elif t == "escrow_return":
            issue = e.get("issue")
            if issue not in escrow_create_issues:
                # Old-format escrow — skip.
                continue
            # Recipient lookup: prefer recipient, fall back to author then agent.
            recip = e.get("recipient") or e.get("author") or e.get("agent", "")
            if recip:
                earned[recip] += amount

        # --- escrow_create ---
        elif t == "escrow_create":
            author = e.get("author", "")
            if author:
                spent[author] += amount

    return dict(earned), dict(spent)


def check_consistency(
    stored_agents: dict[str, Any],
    computed_earned: dict[str, int],
    computed_spent: dict[str, int],
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], str]:
    """Compare stored totals against history-computed totals.

    Returns (status, divergences, warnings, summary).

    A divergence is emitted when a stored agent's total_earned or total_spent
    does not match the computed value from history.

    A warning (not a divergence) is emitted when an agent appears in history
    with non-zero computed earned/spent but is absent from balances.json.
    """
    divergences: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    for agent_id in sorted(stored_agents):
        if agent_id in _SKIP_AGENTS:
            continue
        info = stored_agents[agent_id]
        if not isinstance(info, dict):
            continue

        stored_earned = int(info.get("total_earned", 0))
        stored_spent = int(info.get("total_spent", 0))
        hist_earned = computed_earned.get(agent_id, 0)
        hist_spent = computed_spent.get(agent_id, 0)

        if hist_earned != stored_earned:
            divergences.append(
                {
                    "agent": agent_id,
                    "field": "total_earned",
                    "computed": hist_earned,
                    "stored": stored_earned,
                }
            )
        if hist_spent != stored_spent:
            divergences.append(
                {
                    "agent": agent_id,
                    "field": "total_spent",
                    "computed": hist_spent,
                    "stored": stored_spent,
                }
            )

    # Warn about agents that appear in history but not in balances.json.
    all_hist_agents = set(computed_earned) | set(computed_spent)
    for agent_id in sorted(all_hist_agents):
        if agent_id in _SKIP_AGENTS:
            continue
        if agent_id in stored_agents:
            continue
        hist_earned = computed_earned.get(agent_id, 0)
        hist_spent = computed_spent.get(agent_id, 0)
        if hist_earned != 0 or hist_spent != 0:
            warnings.append(
                {
                    "agent": agent_id,
                    "computed_earned": hist_earned,
                    "computed_spent": hist_spent,
                    "note": "agent in history but absent from balances.json",
                }
            )

    n_stored = sum(1 for a in stored_agents if a not in _SKIP_AGENTS)
    n_history_only = len(warnings)
    n_div = len(divergences)
    status = "PASS" if n_div == 0 else "FAIL"
    summary = (
        f"Checked {n_stored} stored agent(s) "
        f"+ {n_history_only} history-only agent(s); "
        f"{n_div} divergence(s) found."
    )
    return status, divergences, warnings, summary


def main() -> int:
    root = _repo_root()
    balances_path = root / "ledger" / "balances.json"
    history_dir = root / "ledger" / "history"

    if not balances_path.exists():
        result: dict[str, Any] = {
            "status": "FAIL",
            "divergences": [],
            "warnings": [],
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
            "warnings": [],
            "summary": f"balances.json is not valid JSON: {exc}",
        }
        print(json.dumps(result, indent=2))
        return 1

    events = _iter_events(history_dir)
    computed_earned, computed_spent = compute_earned_spent(events)
    stored_agents: dict[str, Any] = balances.get("agents", {})

    status, divergences, warnings, summary = check_consistency(
        stored_agents, computed_earned, computed_spent
    )
    result = {
        "status": status,
        "divergences": divergences,
        "warnings": warnings,
        "summary": summary,
    }
    print(json.dumps(result, indent=2))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
