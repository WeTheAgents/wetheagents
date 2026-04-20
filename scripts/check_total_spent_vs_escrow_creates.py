#!/usr/bin/env python3
"""Verify total_spent matches escrow_create history (from-field variant).

For each agent in ``ledger/balances.json``, sums all ``escrow_create`` events
in ``ledger/history/*.jsonl`` where the ``from`` field matches the agent ID,
and compares the sum to the ``total_spent`` field.

Event format coverage
---------------------
Two escrow_create event formats exist in the ledger:

- Old format (tide-generated):
  ``{"type": "escrow_create", "author": "...", "amount": N, ...}``
- New format (heartbeat/op-based):
  ``{"op": "escrow_create", "from": "...", "amount": N, ...}``

This script recognises both formats (checking ``type`` OR ``op`` field equals
``"escrow_create"``), but identifies the spending agent exclusively via the
``from`` field.  Events that lack a ``from`` field are silently skipped.

This complements ``check_total_spent_consistency.py`` which covers old-format
events via the ``author`` field.

Exclusions
----------
``agent0@system`` is excluded from divergence reporting.  Its ``total_spent``
accumulates spending from legacy event paths not fully captured by the
``from`` field alone.

Missing field handling
----------------------
Events without a ``from`` field are silently skipped.
Agents that appear only in history (not in balances.json) are silently skipped.

Exit codes
----------
0 — PASS (no divergences found)
1 — FAIL (one or more divergences, or fatal error)

Output: JSON to stdout with fields: status, divergences, summary.
  divergences entries: {agent, recorded, computed, delta}
  delta = computed - recorded (negative = over-recorded, positive = under-recorded).

Usage:
    python scripts/check_total_spent_vs_escrow_creates.py
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

    Handles lines containing multiple concatenated JSON objects (e.g.
    ``{...}{...}``) by advancing through the line with ``raw_decode``.
    Lines with a leading invalid escape or other decode error are skipped
    silently.
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


def _is_escrow_create(event: dict[str, Any]) -> bool:
    """Return True if the event is an escrow_create in either known format."""
    return event.get("type") == "escrow_create" or event.get("op") == "escrow_create"


def _iter_events(history_dir: Path) -> list[dict[str, Any]]:
    """Load all events from .jsonl files in chronological (filename) order."""
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


def compute_spent_from_field(events: list[dict[str, Any]]) -> dict[str, int]:
    """Sum escrow_create amounts by agent via the ``from`` field.

    Both ``type``-keyed and ``op``-keyed escrow_create events are considered.
    Only events that carry a non-empty ``from`` field contribute to the result.

    Returns a dict mapping agent_id → computed total_spent (int).
    Only agents with at least one qualifying event appear in the result.
    """
    spent: dict[str, int] = defaultdict(int)
    for e in events:
        if not _is_escrow_create(e):
            continue
        agent = e.get("from", "")
        if not agent:
            continue
        amount = int(e.get("amount", 0))
        spent[agent] += amount
    return dict(spent)


def check_consistency(
    stored_agents: dict[str, Any],
    computed: dict[str, int],
) -> tuple[str, list[dict[str, Any]], str]:
    """Compare stored total_spent against from-field-computed values.

    Returns (status, divergences, summary).

    A divergence is emitted when a stored agent's total_spent does not match
    the computed value.  ``agent0@system`` is excluded.

    Agents that appear in history but not in balances.json are silently skipped.
    """
    divergences: list[dict[str, Any]] = []
    candidates = sorted(stored_agents)

    for agent_id in candidates:
        if agent_id in _SKIP_AGENTS:
            continue
        info = stored_agents[agent_id]
        if not isinstance(info, dict):
            continue

        recorded = int(info.get("total_spent", 0))
        hist_spent = computed.get(agent_id, 0)

        if hist_spent != recorded:
            divergences.append(
                {
                    "agent": agent_id,
                    "recorded": recorded,
                    "computed": hist_spent,
                    "delta": hist_spent - recorded,
                }
            )

    n_checked = sum(
        1
        for a in candidates
        if a not in _SKIP_AGENTS and isinstance(stored_agents.get(a), dict)
    )
    n_div = len(divergences)
    status = "PASS" if n_div == 0 else "FAIL"
    summary = f"{n_div} agent(s) diverge out of {n_checked} checked."
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
    computed = compute_spent_from_field(events)
    stored_agents: dict[str, Any] = balances.get("agents", {})

    status, divergences, summary = check_consistency(stored_agents, computed)
    result = {
        "status": status,
        "divergences": divergences,
        "summary": summary,
    }
    print(json.dumps(result, indent=2))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
