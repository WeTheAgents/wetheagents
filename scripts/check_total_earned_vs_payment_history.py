#!/usr/bin/env python3
"""Verify total_earned matches cumulative payment history for each agent.

Cross-validates the ``total_earned`` metadata field in
``ledger/balances.json`` against three income event types in
``ledger/history/*.jsonl``:

- ``accept``          — ``amount`` credited to the event's ``agent`` field.
- ``payment``         — ``amount`` credited to the event's ``agent`` field.
- ``trajectory_mint`` — amount credited per agent, in three historical formats:
    1. Multi-agent:  ``agents`` list + ``per_agent`` list (``per_agent[i]`` for
       index *i* of the matching agent).
    2. Single-agent: ``agent`` field + ``amount``.
    3. Single-agent: ``to``    field + ``amount``  (older heartbeat format).

All three trajectory_mint formats are normalised before comparison.
Only positive amounts are counted toward income.

Exclusions
----------
``agent0@system`` is excluded from divergence reporting.  Its
``total_earned`` field incorporates legacy event paths and transfer
mechanics outside this spec.

Missing field handling
----------------------
Events with no recognisable recipient field are silently skipped.
Agents that appear only in history (not in balances.json) are silently
skipped.

Exit codes
----------
0 — PASS (no divergences found)
1 — FAIL (one or more divergences, or fatal error)

Output: JSON to stdout with fields: status, divergences, warnings, summary.
  divergences entries: {agent, stored, computed, delta}
    delta = computed − stored (negative = stored over-counts, positive = stored
    under-counts relative to history).
  warnings entries: agents with computed > 0 but absent from balances.json.

Usage:
    python scripts/check_total_earned_vs_payment_history.py
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


def _extract_objects(line: str) -> list[dict[str, Any]]:
    """Extract all JSON objects from a single line.

    Handles lines with multiple concatenated JSON objects (e.g. ``{...}{...}``)
    by advancing through the line with ``raw_decode``.  Lines whose leading
    content is not valid JSON are silently skipped.
    """
    decoder = json.JSONDecoder()
    results: list[dict[str, Any]] = []
    idx = 0
    n = len(line)
    while idx < n:
        while idx < n and line[idx] in " \t":
            idx += 1
        if idx >= n:
            break
        try:
            obj, end = decoder.raw_decode(line, idx)
        except json.JSONDecodeError:
            break
        if isinstance(obj, dict):
            results.append(obj)
        idx = end
    return results


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
            events.extend(_extract_objects(raw))
    return events


def compute_total_earned(events: list[dict[str, Any]]) -> dict[str, int]:
    """Replay history events and return total earned per agent.

    Processes only ``accept``, ``payment``, and ``trajectory_mint`` events.
    All other event types are silently ignored.

    ``trajectory_mint`` format variants handled:
    - Multi-agent:   ``agents`` list present → ``per_agent[i]`` for agent *i*.
    - Single-agent:  ``agent`` field present → ``amount``.
    - Single-to:     ``to``    field present → ``amount``.

    Only positive amounts are counted.

    Returns a dict mapping agent_id → computed total_earned (int).
    """
    earned: dict[str, int] = defaultdict(int)

    # Track (issue, agent, amount, balance_after) for payment dedup. A
    # duplicate write with identical signature posts the same balance_after
    # twice, proving only one mutation applied; counting both inflates the
    # total. Legitimate multi-payment per (issue, agent) always advances
    # balance_after, so this signature is safe.
    seen_payments: set[tuple[Any, str, int, int]] = set()

    for e in events:
        t = e.get("type", "")
        amount = int(e.get("amount", 0))

        if t == "trajectory_mint":
            agents_list: list[str] = e.get("agents", [])
            per_agent: list[int] = e.get("per_agent", [])
            if agents_list:
                # Multi-agent format: explicit per-agent amounts.
                for i, a in enumerate(agents_list):
                    if i < len(per_agent):
                        slot_amount = int(per_agent[i])
                        if slot_amount > 0:
                            earned[a] += slot_amount
            else:
                # Single-agent format: "agent" field, or older "to" field.
                recipient = e.get("agent") or e.get("to") or ""
                if recipient and amount > 0:
                    earned[recipient] += amount

        elif t in ("payment", "accept"):
            agent = e.get("agent", "")
            if agent and amount > 0:
                if t == "payment" and "balance_after" in e:
                    key = (e.get("issue"), agent, amount, int(e.get("balance_after", 0)))
                    if key in seen_payments:
                        continue
                    seen_payments.add(key)
                earned[agent] += amount

    return dict(earned)


def check_consistency(
    stored_agents: dict[str, Any],
    computed: dict[str, int],
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], str]:
    """Compare stored total_earned against history-computed values.

    Returns (status, divergences, warnings, summary).

    A divergence is emitted when a stored agent's total_earned does not match
    the computed value from history.  ``agent0@system`` is excluded because its
    accounting spans legacy event paths outside this spec.

    A warning (not a divergence) is emitted for agents that appear in history
    with non-zero computed earnings but are absent from balances.json.
    """
    divergences: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    for agent_id in sorted(stored_agents):
        if agent_id in _SKIP_AGENTS:
            continue
        info = stored_agents[agent_id]
        if not isinstance(info, dict):
            continue

        stored = int(info.get("total_earned", 0))
        hist = computed.get(agent_id, 0)

        if hist != stored:
            divergences.append(
                {
                    "agent": agent_id,
                    "stored": stored,
                    "computed": hist,
                    "delta": hist - stored,
                }
            )

    for agent_id in sorted(computed):
        if agent_id in _SKIP_AGENTS:
            continue
        if agent_id in stored_agents:
            continue
        hist = computed[agent_id]
        if hist > 0:
            warnings.append(
                {
                    "agent": agent_id,
                    "computed": hist,
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
    computed = compute_total_earned(events)
    stored_agents: dict[str, Any] = balances.get("agents", {})

    status, divergences, warnings, summary = check_consistency(
        stored_agents, computed
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
