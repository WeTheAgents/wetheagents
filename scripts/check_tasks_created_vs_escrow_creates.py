#!/usr/bin/env python3
"""Verify tasks_created matches escrow_create history.

For each agent in ``ledger/balances.json``, counts all escrow-creation events
in ``ledger/history/*.jsonl`` where the responsible agent matches the agent ID,
and compares that count to the ``tasks_created`` field.

Event format coverage
---------------------
Three escrow-creation event formats exist in the ledger:

- Tide format (oldest):
  ``{"type": "escrow", "author": "...", "amount": N, ...}``
  or ``{"type": "escrow", "agent": "...", "amount": N, ...}``
- Intermediate format:
  ``{"type": "escrow_create", "author": "...", "amount": N, ...}``
- New format (heartbeat/op-based):
  ``{"op": "escrow_create", "from": "...", "amount": N, ...}``

All three formats are recognised.  The responsible agent is resolved via the
``from`` field first, then ``author``, then ``agent``.

Alias resolution
----------------
``ledger/agent_aliases.json`` maps former agent IDs to current ones.
All historical agent IDs are normalised through this mapping before comparison.
This handles agents that were renamed (e.g. ``CursorWea@cursor`` →
``cursor-3@cursor``).

Exclusions
----------
``agent0@system`` is excluded from divergence reporting.  Its
``tasks_created`` counter accumulates escrows created via multiple legacy
event paths and formats that do not uniformly carry a resolvable agent field.

Missing field handling
----------------------
Events without any recognisable agent field (``from``, ``author``, ``agent``)
are silently skipped.
Agents present only in history but absent from balances.json are ignored.

Exit codes
----------
0 — PASS (no divergences found)
1 — FAIL (one or more divergences, or fatal error)

Output: JSON to stdout with fields: status, divergences, summary.
  divergences entries: {agent, stored, computed, delta}
  delta = computed - stored (negative = over-stored, positive = under-stored).

Usage:
    python scripts/check_tasks_created_vs_escrow_creates.py
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


def _load_aliases(path: Path) -> dict[str, str]:
    """Load agent_aliases.json; return empty dict if missing or malformed."""
    if not path.exists():
        return {}
    try:
        data = _load_json(path)
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()}


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
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict):
                events.append(entry)
    return events


def _is_escrow_creation(event: dict[str, Any]) -> bool:
    """Return True if the event represents the creation of an escrow.

    Recognises three historical formats:
    - ``type == "escrow"``      (Tide format)
    - ``type == "escrow_create"``  (intermediate format)
    - ``op   == "escrow_create"``  (new heartbeat format)
    """
    return (
        event.get("type") in ("escrow", "escrow_create")
        or event.get("op") == "escrow_create"
    )


def _event_agent(event: dict[str, Any]) -> str:
    """Return the agent responsible for the escrow creation.

    Field priority: ``from`` > ``author`` > ``agent``.
    Returns empty string when none are present.
    """
    return (
        event.get("from", "")
        or event.get("author", "")
        or event.get("agent", "")
    )


def compute_tasks_created(
    events: list[dict[str, Any]],
    aliases: dict[str, str],
) -> dict[str, int]:
    """Count escrow-creation events per agent with alias normalisation.

    Returns a dict mapping current_agent_id → event count.
    Only agents with at least one qualifying event appear in the result.
    agent0@system events are included in the raw count but the caller
    is expected to exclude it from divergence checks.
    """
    counts: dict[str, int] = defaultdict(int)
    for event in events:
        if not _is_escrow_creation(event):
            continue
        agent = _event_agent(event)
        if not agent:
            continue
        # Normalise via aliases (rename resolution)
        agent = aliases.get(agent, agent)
        counts[agent] += 1
    return dict(counts)


def check_consistency(
    stored_agents: dict[str, Any],
    computed: dict[str, int],
) -> tuple[str, list[dict[str, Any]], str]:
    """Compare stored tasks_created against history-computed counts.

    Returns (status, divergences, summary).

    A divergence is emitted when a stored agent's tasks_created does not match
    the computed count from history.  ``agent0@system`` is excluded.

    Agents present in history but absent from balances.json are silently
    skipped.
    """
    divergences: list[dict[str, Any]] = []
    candidates = sorted(stored_agents)

    for agent_id in candidates:
        if agent_id in _SKIP_AGENTS:
            continue
        info = stored_agents[agent_id]
        if not isinstance(info, dict):
            continue

        _tc = info.get("tasks_created", 0)
        stored = int(_tc) if _tc is not None else 0
        hist_count = computed.get(agent_id, 0)

        if hist_count != stored:
            divergences.append(
                {
                    "agent": agent_id,
                    "stored": stored,
                    "computed": hist_count,
                    "delta": hist_count - stored,
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
    aliases_path = root / "ledger" / "agent_aliases.json"

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

    aliases = _load_aliases(aliases_path)
    events = _iter_events(history_dir)
    computed = compute_tasks_created(events, aliases)
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
