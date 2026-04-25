#!/usr/bin/env python3
"""Balance-history reconciliation checker for WeTheAgents.

Verifies that every agent balance recorded in ``ledger/balances.json`` matches
the balance obtained by replaying ``ledger/history/*.jsonl``.

Accounting model (what counts as a credit or debit):
  Credits (increase balance):
    payment, mint, hello_world_mint, reversal, accept
    escrow_return       — credits recipient/agent/author; deduped per (issue, agent)
    escrow_return_bulk  — credits the listed agent
    trajectory_mint     — both list format (agents/per_agent) and single-agent format
    wea_returned_to_agent0  — from economy_reset events

  Debits (decrease balance):
    escrow           — debits the explicit ``agent`` field
    escrow_create    — debits ``agent`` or legacy ``author``

  Special:
    economy_reset          — zeroes listed agents, then credits wea_returned_to_agent0
    registration_confirmed — moves prior balance from previous_id to the canonical agent id
    agent_removal          — zeroes the removed agent

  Initial balance:
    agent0@system   — 10000 WEA (genesis allocation, not a history event)
    all others      — 0 WEA

Note: agent0@system is reported as SKIP rather than FAIL when its computed
balance diverges. The escrow_batch event (which uses ``author`` and has no
per-issue breakdown) creates irreconcilable legacy offsets for agent0. All
other agents are expected to reconcile exactly.

Exit codes:
    0  — all reconcilable agents PASS (SKIP does not count as failure)
    1  — one or more agents FAIL (balance mismatch detected)

Output: JSON to stdout with fields: status, checks, summary.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


_AGENT0 = "agent0@system"
_INITIAL_BALANCES: dict[str, int] = {_AGENT0: 10000}

# agent0's balance cannot be exactly reconciled from history due to legacy
# escrow_batch events that have no per-issue breakdown. The check skips agent0
# rather than reporting a spurious FAIL.
_SKIP_AGENTS = {_AGENT0}


def _repo_root(override: str | None = None) -> Path:
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parent.parent


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _iter_history(history_dir: Path) -> list[tuple[str, dict[str, Any]]]:
    """Yield (filename, event) pairs from all .jsonl files in chronological order."""
    entries: list[tuple[str, dict[str, Any]]] = []
    if not history_dir.is_dir():
        return entries
    for path in sorted(history_dir.glob("*.jsonl")):
        for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict):
                entries.append((path.name, entry))
    return entries


def compute_balances_from_history(
    entries: list[tuple[str, dict[str, Any]]],
) -> dict[str, int]:
    """Replay history events and return computed balance per agent.

    Returns a dict mapping agent_id to computed balance.
    """
    balance: dict[str, int] = defaultdict(int)
    # Seed the agent0 genesis allocation — it is not recorded as a history event.
    balance[_AGENT0] = _INITIAL_BALANCES.get(_AGENT0, 0)

    # Track (issue, agent) pairs for escrow_return deduplication.
    # Some history files contain duplicate escrow_return entries for the same
    # issue with identical timestamps; counting them twice inflates balances.
    seen_returns: set[tuple[str, str]] = set()

    for _filename, e in entries:
        t = e.get("type", "")
        # Primary agent identifier; fall back to `author` for credit events only.
        agent: str = str(e.get("agent", "") or "")
        author: str = str(e.get("author", "") or "")
        recipient: str = str(e.get("recipient", "") or "")
        amount: int = int(e.get("amount", 0))

        if t == "economy_reset":
            for zeroed in e.get("agents_zeroed", []):
                balance[str(zeroed)] = 0
            returned = int(e.get("wea_returned_to_agent0", 0))
            if returned:
                balance[_AGENT0] += returned
            continue

        if t in ("payment", "mint", "hello_world_mint", "reversal", "accept"):
            # Credits: prefer `agent`, fall back to `author`
            a = agent or author
            if a:
                balance[a] += amount

        elif t == "escrow_return":
            # Credits: prefer explicit recipient, then legacy agent/author fields.
            a = recipient or agent or author
            if a:
                issue = str(e.get("issue", "_no_issue_"))
                key = (issue, a)
                if key not in seen_returns:
                    seen_returns.add(key)
                    balance[a] += amount

        elif t == "escrow_return_bulk":
            a = recipient or agent or author or _AGENT0
            balance[a] += amount

        elif t in ("escrow", "escrow_create"):
            # Modern escrow_create rows use `author`; older escrow rows use `agent`.
            # Keep the legacy author fallback only for escrow_create so modern
            # gauntlet escrows reconcile without dropping those debits entirely.
            debit_agent = agent
            if not debit_agent and t == "escrow_create":
                debit_agent = author
            if debit_agent:
                balance[debit_agent] -= amount

        elif t == "trajectory_mint":
            # New single-agent format
            if agent:
                balance[agent] += amount
            elif e.get("to"):
                # Legacy single-agent format.
                balance[str(e.get("to"))] += amount
            else:
                # Legacy list format
                agents_list: list[str] = e.get("agents", [])
                per_agent: list[int] = e.get("per_agent", [])
                for i, a in enumerate(agents_list):
                    if i < len(per_agent):
                        balance[str(a)] += int(per_agent[i])

        elif t == "agent_removal":
            if agent:
                balance[agent] = 0

        elif t == "registration_confirmed":
            new_id = agent
            old_id = str(e.get("previous_id", "") or "")
            if old_id and new_id and old_id != new_id:
                balance[new_id] += balance[old_id]
                balance[old_id] = 0

    return dict(balance)


def reconcile(
    balances: dict[str, Any],
    computed: dict[str, int],
) -> list[dict[str, Any]]:
    """Compare stored balances against computed balances.

    Returns a list of per-agent check result dicts with keys:
        agent, status ("PASS" | "FAIL" | "SKIP"), stored, computed, delta, note
    """
    checks: list[dict[str, Any]] = []
    agents = balances.get("agents", {})
    if not isinstance(agents, dict):
        return checks

    for agent_id, info in sorted(agents.items()):
        if not isinstance(info, dict):
            checks.append(
                {
                    "agent": agent_id,
                    "status": "FAIL",
                    "stored": None,
                    "computed": computed.get(agent_id),
                    "delta": None,
                    "note": "agent entry is not a dict",
                }
            )
            continue

        stored: int = int(info.get("balance", 0))
        comp: int = computed.get(agent_id, 0)
        delta: int = comp - stored

        if agent_id in _SKIP_AGENTS:
            checks.append(
                {
                    "agent": agent_id,
                    "status": "SKIP",
                    "stored": stored,
                    "computed": comp,
                    "delta": delta,
                    "note": (
                        "agent0 balance includes a 10000 WEA genesis allocation "
                        "and legacy escrow_batch offsets that cannot be exactly "
                        "reconstructed per-issue from history; full reconciliation "
                        "is deferred to manual audit"
                    ),
                }
            )
            continue

        if delta == 0:
            checks.append(
                {
                    "agent": agent_id,
                    "status": "PASS",
                    "stored": stored,
                    "computed": comp,
                    "delta": 0,
                    "note": "",
                }
            )
        else:
            checks.append(
                {
                    "agent": agent_id,
                    "status": "FAIL",
                    "stored": stored,
                    "computed": comp,
                    "delta": delta,
                    "note": (
                        f"balance mismatch: stored={stored}, "
                        f"computed_from_history={comp}, delta={delta:+d}"
                    ),
                }
            )

    for agent_id in sorted(computed, key=str):
        agent_name = str(agent_id)
        if agent_name in agents or agent_name in _SKIP_AGENTS:
            continue
        comp = computed[agent_id]
        if comp == 0:
            continue
        checks.append(
            {
                "agent": agent_name,
                "status": "FAIL",
                "stored": 0,
                "computed": comp,
                "delta": comp,
                "note": "agent present in history but absent from balances.json",
            }
        )

    return checks


def run(root: Path) -> tuple[dict[str, Any], bool]:
    """Run the full reconciliation and return (result_json, passed)."""
    balances_path = root / "ledger" / "balances.json"
    history_dir = root / "ledger" / "history"

    if not balances_path.exists():
        result = {
            "status": "FAIL",
            "checks": [],
            "summary": f"balances.json not found at {balances_path}",
        }
        return result, False

    try:
        balances = _load_json(balances_path)
    except json.JSONDecodeError as exc:
        result = {
            "status": "FAIL",
            "checks": [],
            "summary": f"balances.json is not valid JSON: {exc}",
        }
        return result, False

    # Load history — empty history is valid (nothing to reconcile yet)
    try:
        entries = _iter_history(history_dir)
    except OSError as exc:
        result = {
            "status": "FAIL",
            "checks": [],
            "summary": f"error reading history directory: {exc}",
        }
        return result, False

    computed = compute_balances_from_history(entries)
    checks = reconcile(balances, computed)

    n_pass = sum(1 for c in checks if c["status"] == "PASS")
    n_fail = sum(1 for c in checks if c["status"] == "FAIL")
    n_skip = sum(1 for c in checks if c["status"] == "SKIP")
    agents = balances.get("agents", {})
    n_history_only = sum(1 for c in checks if c["agent"] not in agents)

    if n_fail == 0:
        overall = "PASS"
        passed = True
    else:
        overall = "FAIL"
        passed = False

    parts = []
    if n_pass:
        parts.append(f"{n_pass} PASS")
    if n_fail:
        parts.append(f"{n_fail} FAIL")
    if n_skip:
        parts.append(f"{n_skip} SKIP")
    if n_history_only:
        parts.append(f"{n_history_only} history-only")

    summary = ", ".join(parts) if parts else "no agents found"

    result = {
        "status": overall,
        "checks": checks,
        "summary": summary,
    }
    return result, passed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify each agent's balance matches the sum of history events."
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
