#!/usr/bin/env python3
"""total_earned consistency check for WeTheAgents.

Verifies that the ``total_earned`` metadata field in ``ledger/balances.json``
matches what ``ledger/history/*.jsonl`` actually shows for each agent.

Computation rule
----------------
``total_earned`` is the sum of:

- ``payment`` — ``amount`` when the event's ``agent`` field matches and
  ``amount`` > 0.
- ``accept`` — ``amount`` when the event's ``agent`` field matches and
  ``amount`` > 0.
- ``trajectory_mint`` — ``per_agent[i]`` for multi-agent format (``agents``
  list present); ``amount`` for single-agent format (``agent`` field, no
  ``agents`` list).
- ``escrow_return`` — ``amount`` credited to the agent identified by the
  ``recipient`` field, falling back to the ``agent`` field if ``recipient``
  is absent.

Do NOT count:
- ``escrow_create`` events (debits, not income).
- All other event types (``verification``, ``claim``, ``escrow``,
  ``economy_reset``, ``reversal``, etc.).

Exclusions
----------
``agent0@system`` is excluded from divergence reporting.  Its accounting
involves legacy escrow events outside this spec.

Missing agents
--------------
Agents that appear in history with computed ``total_earned`` > 0 but are
absent from ``balances.json`` emit a warning; they do not cause FAIL.

Exit codes
----------
0 — PASS (no divergences found)
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


def _extract_objects(line: str) -> list[dict[str, Any]]:
    """Extract all JSON objects from a single line.

    Handles lines that contain multiple concatenated JSON objects (e.g.
    ``{...}{...}``) by advancing through the line with ``raw_decode``.
    Lines with a leading invalid escape or other decode error are skipped
    silently, just as a malformed single-object line would be.
    """
    decoder = json.JSONDecoder()
    results: list[dict[str, Any]] = []
    idx = 0
    n = len(line)
    while idx < n:
        # Skip any ASCII whitespace between objects.
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
    """Load events from all .jsonl files in chronological (filename) order.

    Each physical line may contain one *or more* concatenated JSON objects.
    ``_extract_objects`` handles both forms transparently.
    """
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


def compute_total_earned(
    events: list[dict[str, Any]],
) -> dict[str, int]:
    """Replay history events and return total_earned per agent.

    Only processes income event types per the spec.  All other event types
    are silently ignored.

    Returns a dict mapping agent_id → computed total_earned (int).
    """
    earned: dict[str, int] = defaultdict(int)

    # Track (issue, agent, amount, balance_after) for payment dedup. A
    # duplicate write where all four fields are identical posts the same
    # balance_after twice, proving only one mutation applied; counting
    # both inflates the computed total. Legitimate multi-payment to the
    # same (issue, agent) always advances balance_after.
    seen_payments: set[tuple[Any, str, int, int]] = set()

    for e in events:
        t = e.get("type", "")
        amount = int(e.get("amount", 0))

        # --- trajectory_mint ---
        if t == "trajectory_mint":
            agents_list: list[str] = e.get("agents", [])
            per_agent: list[int] = e.get("per_agent", [])
            if agents_list:
                # Multi-agent format: each position has an explicit per-agent amount.
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

        # --- escrow_return ---
        elif t == "escrow_return":
            # Prefer recipient field; fall back to agent field.
            recip = e.get("recipient") or e.get("agent", "")
            if recip:
                earned[recip] += amount

    return dict(earned)


def check_consistency(
    stored_agents: dict[str, Any],
    computed: dict[str, int],
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], str]:
    """Compare stored total_earned against history-computed values.

    Returns (status, divergences, warnings, summary).

    A divergence is emitted when a stored agent's total_earned does not match
    the computed value from history.

    A warning (not a divergence) is emitted when an agent appears in history
    with non-zero computed total_earned but is absent from balances.json.
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
        hist_earned = computed.get(agent_id, 0)

        if hist_earned != stored_earned:
            divergences.append(
                {
                    "agent": agent_id,
                    "field": "total_earned",
                    "computed": hist_earned,
                    "stored": stored_earned,
                }
            )

    # Warn about agents that appear in history but not in balances.json.
    for agent_id in sorted(computed):
        if agent_id in _SKIP_AGENTS:
            continue
        if agent_id in stored_agents:
            continue
        hist_earned = computed[agent_id]
        if hist_earned > 0:
            warnings.append(
                {
                    "agent": agent_id,
                    "computed_total_earned": hist_earned,
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
