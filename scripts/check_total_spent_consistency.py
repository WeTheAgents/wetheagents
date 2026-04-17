#!/usr/bin/env python3
"""total_spent consistency check for WeTheAgents.

Verifies that the ``total_spent`` metadata field in ``ledger/balances.json``
matches what ``ledger/history/*.jsonl`` actually shows for each agent.

Computation rule
----------------
``total_spent`` is the sum of all ``escrow_create`` events where the
``author`` field matches the agent identifier.

All other event types are ignored.

Exclusions
----------
``agent0@system`` is excluded from divergence reporting.  Its
``total_spent`` accumulates spending from multiple history paths:
legacy ``escrow`` events (tide path, ``agent`` field), ``escrow_batch``
retroactive entries, and newer ``escrow_create`` events (``author``
field), none of which alone reconstructs the stored value.  This
mirrors the analogous exclusion in ``check_total_earned_consistency.py``.

Missing field handling
----------------------
Events where the ``author`` field is absent are silently skipped.
Agents that appear only in history (not in balances.json) are silently
skipped.

Exit codes
----------
0 — PASS (no divergences found)
1 — FAIL (one or more divergences, or fatal error)

Output: JSON to stdout with fields: status, divergences, summary.
  divergences entries: {"agent", "recorded", "computed", "delta"}
  delta = computed - recorded (negative means under-recorded, positive
  means over-recorded relative to recorded value).
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

    Handles lines that contain multiple concatenated JSON objects (e.g.
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


def compute_total_spent(
    events: list[dict[str, Any]],
) -> dict[str, int]:
    """Replay history events and return total_spent per agent.

    Only ``escrow_create`` events count.  The ``author`` field identifies
    the spending agent.  Events without an ``author`` field are skipped.

    Returns a dict mapping agent_id → computed total_spent (int).
    """
    spent: dict[str, int] = defaultdict(int)

    for e in events:
        if e.get("type") != "escrow_create":
            continue
        author = e.get("author", "")
        if not author:
            continue
        amount = int(e.get("amount", 0))
        spent[author] += amount

    return dict(spent)


def check_consistency(
    stored_agents: dict[str, Any],
    computed: dict[str, int],
) -> tuple[str, list[dict[str, Any]], str]:
    """Compare stored total_spent against history-computed values.

    Returns (status, divergences, summary).

    A divergence is emitted when a stored agent's total_spent does not match
    the computed value from history.  ``agent0@system`` is excluded because
    its total_spent accumulates spending from multiple history paths not
    captured by ``escrow_create`` events alone.

    Agents that appear in history but not in balances.json are silently
    skipped — they cannot cause a FAIL.
    """
    divergences: list[dict[str, Any]] = []

    for agent_id in sorted(stored_agents):
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
        1 for a, v in stored_agents.items()
        if a not in _SKIP_AGENTS and isinstance(v, dict)
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
    computed = compute_total_spent(events)
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
