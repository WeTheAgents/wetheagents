#!/usr/bin/env python3
"""Consistency check: total_earned / total_spent vs ledger history.

Verifies that each agent's ``total_earned`` and ``total_spent`` counter fields
in ``ledger/balances.json`` exactly match what can be computed by replaying
``ledger/history/*.jsonl``.

Computation model
-----------------
``computed_earned`` is the sum of WEA received:
  - ``payment`` — ``amount`` (positive only), keyed on ``agent``
  - ``accept``  — ``amount`` (positive only), keyed on ``agent``
  - ``trajectory_mint`` — per-agent values from ``per_agent[]`` (multi-agent
    format) or ``amount`` (single-agent format with ``agent`` or ``to`` field)
  - ``escrow_return`` — ``amount``, credited to the agent identified by the
    first of (``recipient``, ``author``, ``agent``) that is non-empty, BUT
    only when the ``issue`` matches a prior ``escrow_create`` event (modern
    escrow format only; legacy ``escrow`` events are excluded)

``computed_spent`` is the sum of WEA deducted:
  - ``escrow_create`` — ``amount`` debited from ``author``

Compatibility events (``economy_reset``, ``agent_removal``, ``reversal``,
``registration_confirmed``) are deliberately excluded; they affect the running
balance but are not part of the earned/spent metadata specification.

Exclusions
----------
``agent0@system`` is excluded — its accounting involves legacy escrow_batch
events that pre-date per-issue breakdown and cannot be reconciled here.

Missing agents
--------------
Agents that appear in history (computed earned/spent > 0) but are absent from
``balances.json`` emit a WARNING and do not cause exit code 1.  Full registry
completeness is the responsibility of ``check_agent_registry_completeness.py``.

Exit codes
----------
0 — PASS (no violations)
1 — FAIL (one or more violations, or fatal error reading ledger files)

Output: JSON to stdout with fields: status, violations, warnings, summary.
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


def _repo_root(override: str | None = None) -> Path:
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parent.parent


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _iter_events(history_dir: Path) -> list[dict[str, Any]]:
    """Return all events from .jsonl files in chronological (filename) order."""
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
    """Replay events and return (earned, spent) dicts keyed by agent_id.

    Only primary earned/spent event types are processed.  Compatibility events
    that adjust the running balance are ignored because they do not update the
    ``total_earned``/``total_spent`` metadata counters.
    """
    earned: dict[str, int] = defaultdict(int)
    spent: dict[str, int] = defaultdict(int)

    # Collect issues that have a modern escrow_create event.  Only
    # escrow_return events whose issue appears here count toward total_earned.
    escrow_create_issues: set[Any] = set()
    for e in events:
        if e.get("type") == "escrow_create":
            escrow_create_issues.add(e.get("issue"))

    for e in events:
        t = e.get("type", "")
        amount = int(e.get("amount", 0))

        if t == "trajectory_mint":
            agents_list: list[str] = e.get("agents", [])
            per_agent: list[int] = e.get("per_agent", [])
            if agents_list:
                for i, a in enumerate(agents_list):
                    if i < len(per_agent):
                        earned[a] += int(per_agent[i])
            else:
                a = e.get("agent", "") or e.get("to", "")
                if a and amount > 0:
                    earned[a] += amount

        elif t in ("payment", "accept"):
            a = e.get("agent", "")
            if a and amount > 0:
                earned[a] += amount

        elif t == "escrow_return":
            issue = e.get("issue")
            if issue not in escrow_create_issues:
                continue
            recip = e.get("recipient") or e.get("author") or e.get("agent", "")
            if recip and amount > 0:
                earned[recip] += amount

        elif t == "escrow_create":
            author = e.get("author", "")
            if author and amount > 0:
                spent[author] += amount

    return dict(earned), dict(spent)


def check_consistency(
    stored_agents: dict[str, Any],
    computed_earned: dict[str, int],
    computed_spent: dict[str, int],
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], str]:
    """Compare stored totals against history-computed totals.

    Returns (status, violations, warnings, summary).

    A VIOLATION is emitted when a stored agent's ``total_earned`` or
    ``total_spent`` does not exactly match the history-computed value.

    A WARNING (not a violation) is emitted for agents that appear in history
    with non-zero earned/spent but are absent from ``balances.json``.
    """
    violations: list[dict[str, Any]] = []
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
            violations.append(
                {
                    "agent": agent_id,
                    "field": "total_earned",
                    "stored": stored_earned,
                    "computed": hist_earned,
                    "delta": hist_earned - stored_earned,
                }
            )

        if hist_spent != stored_spent:
            violations.append(
                {
                    "agent": agent_id,
                    "field": "total_spent",
                    "stored": stored_spent,
                    "computed": hist_spent,
                    "delta": hist_spent - stored_spent,
                }
            )

    # Warn about agents in history but absent from balances.json.
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
                    "note": "agent present in history but absent from balances.json",
                }
            )

    n_checked = sum(1 for a in stored_agents if a not in _SKIP_AGENTS)
    n_history_only = len(warnings)
    n_viol = len(violations)
    status = "PASS" if n_viol == 0 else "FAIL"
    summary = (
        f"Checked {n_checked} stored agent(s) + {n_history_only} history-only; "
        f"{n_viol} VIOLATION(s)."
    )
    return status, violations, warnings, summary


def run(root: Path) -> tuple[dict[str, Any], bool]:
    """Execute the full check and return (result_dict, passed)."""
    balances_path = root / "ledger" / "balances.json"
    history_dir = root / "ledger" / "history"

    if not balances_path.exists():
        result: dict[str, Any] = {
            "status": "FAIL",
            "violations": [],
            "warnings": [],
            "summary": f"balances.json not found at {balances_path}",
        }
        return result, False

    try:
        balances = _load_json(balances_path)
    except json.JSONDecodeError as exc:
        result = {
            "status": "FAIL",
            "violations": [],
            "warnings": [],
            "summary": f"balances.json is not valid JSON: {exc}",
        }
        return result, False

    try:
        events = _iter_events(history_dir)
    except OSError as exc:
        result = {
            "status": "FAIL",
            "violations": [],
            "warnings": [],
            "summary": f"error reading history directory: {exc}",
        }
        return result, False

    stored_agents: dict[str, Any] = balances.get("agents", {})
    computed_earned, computed_spent = compute_earned_spent(events)
    status, violations, warnings, summary = check_consistency(
        stored_agents, computed_earned, computed_spent
    )

    result = {
        "status": status,
        "violations": violations,
        "warnings": warnings,
        "summary": summary,
    }
    return result, status == "PASS"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify total_earned and total_spent counters in balances.json "
            "match ledger history."
        )
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root (default: auto-detected from script location)",
    )
    args = parser.parse_args()

    root = _repo_root(args.root)
    result, passed = run(root)

    print(json.dumps(result, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
