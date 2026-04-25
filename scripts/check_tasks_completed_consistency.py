#!/usr/bin/env python3
"""tasks_completed and tasks_created counter integrity check for WeTheAgents.

Verifies that the ``tasks_completed`` and ``tasks_created`` metadata fields
in ``ledger/balances.json`` match what ``ledger/history/*.jsonl`` actually
shows for each agent, within a tolerance of ±5.

Computation rules
-----------------
``tasks_completed`` is the count of distinct issue numbers for which an agent
has at least one ``payment`` or ``accept`` event with a positive amount.

``tasks_created`` is the count of ``escrow_create`` events where the ``author``
field matches the agent's ID.

Qualifying events for tasks_completed:
  - ``type`` is ``"payment"`` or ``"accept"``
  - ``agent`` field matches the agent's ID
  - ``amount`` > 0
  - ``issue`` field is present and not ``None``

An agent may receive multiple payment/accept events for the same issue
(e.g., multi-slot progressive tasks or both a payment and an accept).  Only
the *issue* is counted once, not each event.

Non-qualifying event types (``trajectory_mint``, ``escrow_create``,
``escrow_return``, ``verification``, and compatibility events) do not
contribute to ``tasks_completed``.

Tolerance
---------
A divergence is only flagged when ``abs(stored - computed) > 5``.  This
tolerance accounts for historical formatting differences and gauntlet mints
that are recorded as ``trajectory_mint`` events rather than ``payment``.

Exclusions
----------
``agent0@system`` is excluded from divergence reporting; its counters are
maintained separately and are not subject to these invariants.

Missing agents
--------------
Agents that appear in payment/accept history but are absent from
``balances.json`` emit a warning; they do not cause FAIL.

Exit codes
----------
0 — PASS (no divergences found)
1 — FAIL (one or more divergences, or fatal error)

Output: JSON to stdout with fields: status, divergences, warnings, summary.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

_AGENT0 = "agent0@system"
_SKIP_AGENTS: frozenset[str] = frozenset({_AGENT0})
_TOLERANCE = 5


def _repo_root(override: str | None = None) -> Path:
    if override:
        return Path(override).resolve()
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


def compute_tasks_completed(
    events: list[dict[str, Any]],
) -> dict[str, int]:
    """Replay events and return tasks_completed count per agent.

    Counts distinct issue numbers per agent where that agent received at least
    one ``payment`` or ``accept`` event with a positive amount.  Trajectory
    mints, escrows, and compatibility events are not counted.

    Returns a dict mapping agent_id → computed integer count.
    """
    agent_issues: dict[str, set[int]] = defaultdict(set)

    for e in events:
        t = e.get("type", "")
        if t not in ("payment", "accept"):
            continue

        agent = e.get("agent", "")
        if not agent:
            continue

        amount = int(e.get("amount", 0))
        if amount <= 0:
            continue

        issue = e.get("issue")
        if issue is None:
            continue

        try:
            issue_int = int(issue)
        except (TypeError, ValueError):
            continue

        agent_issues[agent].add(issue_int)

    return {agent: len(issues) for agent, issues in agent_issues.items()}


def compute_tasks_created(
    events: list[dict[str, Any]],
) -> dict[str, int]:
    """Replay events and return tasks_created count per agent.

    Counts ``escrow_create`` events where the ``author`` field matches
    the agent's ID.

    Returns a dict mapping agent_id → computed integer count.
    """
    counts: dict[str, int] = defaultdict(int)

    for e in events:
        if e.get("type") != "escrow_create":
            continue
        author = e.get("author", "")
        if author:
            counts[author] += 1

    return dict(counts)


def check_consistency(
    stored_agents: dict[str, Any],
    computed_completed: dict[str, int],
    computed_created: dict[str, int],
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], str]:
    """Compare stored counter fields against history-computed values.

    Checks both ``tasks_completed`` and ``tasks_created`` for each stored
    agent.  A divergence is emitted when
    ``abs(stored - computed) > _TOLERANCE``.

    Returns (status, divergences, warnings, summary).

    A warning (not a divergence) is emitted when an agent appears in history
    with a non-zero computed tasks_completed but is absent from balances.json.
    """
    divergences: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    for agent_id in sorted(stored_agents):
        if agent_id in _SKIP_AGENTS:
            continue
        info = stored_agents[agent_id]
        if not isinstance(info, dict):
            continue

        stored_completed = int(info.get("tasks_completed", 0))
        hist_completed = computed_completed.get(agent_id, 0)
        if abs(hist_completed - stored_completed) > _TOLERANCE:
            divergences.append(
                {
                    "agent": agent_id,
                    "field": "tasks_completed",
                    "computed": hist_completed,
                    "stored": stored_completed,
                    "diff": abs(hist_completed - stored_completed),
                }
            )

        stored_created = int(info.get("tasks_created", 0))
        hist_created = computed_created.get(agent_id, 0)
        if abs(hist_created - stored_created) > _TOLERANCE:
            divergences.append(
                {
                    "agent": agent_id,
                    "field": "tasks_created",
                    "computed": hist_created,
                    "stored": stored_created,
                    "diff": abs(hist_created - stored_created),
                }
            )

    for agent_id in sorted(computed_completed):
        if agent_id in _SKIP_AGENTS:
            continue
        if agent_id in stored_agents:
            continue
        hist_count = computed_completed[agent_id]
        if hist_count > 0:
            warnings.append(
                {
                    "agent": agent_id,
                    "computed_tasks_completed": hist_count,
                    "note": "agent in payment history but absent from balances.json",
                }
            )

    n_stored = sum(1 for a in stored_agents if a not in _SKIP_AGENTS)
    n_history_only = len(warnings)
    n_div = len(divergences)
    status = "PASS" if n_div == 0 else "FAIL"
    summary = (
        f"Checked {n_stored} stored agent(s) "
        f"+ {n_history_only} history-only agent(s); "
        f"{n_div} divergence(s) found (tolerance ±{_TOLERANCE})."
    )
    return status, divergences, warnings, summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check tasks_completed and tasks_created counter consistency."
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Path to the repo root (default: derived from script location).",
    )
    args, _ = parser.parse_known_args()

    root = _repo_root(args.root)
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
    computed_completed = compute_tasks_completed(events)
    computed_created = compute_tasks_created(events)
    stored_agents: dict[str, Any] = balances.get("agents", {})

    status, divergences, warnings, summary = check_consistency(
        stored_agents, computed_completed, computed_created
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
