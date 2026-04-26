#!/usr/bin/env python3
"""
check_history_cumulative_balance_integrity.py

Replays all ledger/history/*.jsonl events in chronological order (sorted by ts,
then filename, then line number) and verifies per-agent balance integrity at
every step.

Invariants checked:
  1. No agent's running balance goes below 0 at any point during replay.
  2. Each agent's final computed balance matches ledger/balances.json within
     the tolerance of that agent's active escrow total from ledger/escrows.json.

Starting condition: all agents begin at 0. Credits build balances; debits reduce
them. A balance exactly at 0 is valid — the violation threshold is strictly < 0.

Exit codes:
  0 — PASS (no negative balances; all finals match within escrow tolerance)
  1 — FAIL (negative balance detected, or unreconciled final mismatch)
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_MECHANIC_KEYWORDS: frozenset[str] = frozenset({
    "standard", "progressive", "best_x", "winner_take_all",
    "duel", "linear", "every_good", "pod", "wta", "every_accepted",
})

_METADATA_TYPES: frozenset[str] = frozenset({
    "settle", "domain_assign", "verification", "provisional_join",
    "claim", "registration", "agent_registration", "register",
})

AGENT0 = "agent0@system"


def _repo_root(override: str | None = None) -> Path:
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parent.parent


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _event_ts(event: dict) -> datetime | None:
    for key in ("ts", "timestamp", "created_at"):
        v = _parse_ts(event.get(key))
        if v is not None:
            return v
    return None


def _file_ts(path: Path) -> datetime | None:
    return _parse_ts(f"{path.stem}T00:00:00Z")


def _normalize_type(event: dict) -> str:
    t = str(event.get("type", "") or "")
    if not t or t in _MECHANIC_KEYWORDS:
        t = str(event.get("event", t) or "")
    return t


def load_events(
    history_dir: Path,
) -> list[tuple[datetime, str, int, dict]]:
    """Load all history events sorted by (ts, filename, line_number)."""
    MAX_DT = datetime.max.replace(tzinfo=timezone.utc)
    rows: list[tuple[datetime, str, int, dict]] = []
    if not history_dir.is_dir():
        return rows
    for path in sorted(history_dir.glob("*.jsonl")):
        file_dt = _file_ts(path) or MAX_DT
        for lineno, raw in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            raw = raw.strip()
            if not raw:
                continue
            try:
                e = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(e, dict):
                continue
            ts = _event_ts(e) or file_dt
            rows.append((ts, path.name, lineno, e))
    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    return rows


def _load_active_escrow_totals(escrows_path: Path) -> dict[str, int]:
    """Return sum of active escrow amounts keyed by author agent."""
    totals: dict[str, int] = {}
    if not escrows_path.exists():
        return totals
    try:
        data = json.loads(escrows_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return totals
    for entry in data.get("active", {}).values():
        author = str(entry.get("author", "") or "")
        amount = int(entry.get("amount", 0))
        if author and amount > 0:
            totals[author] = totals.get(author, 0) + amount
    return totals


def replay(
    events: list[tuple[datetime, str, int, dict]],
) -> dict[str, Any]:
    """Replay sorted events; collect negative-balance violations and final balances."""
    balances: dict[str, int] = defaultdict(int)
    seen_returns: set[tuple[str, str]] = set()
    negative_violations: list[dict] = []
    events_replayed = 0

    for ts, fname, lineno, event in events:
        t = _normalize_type(event)

        if t == "economy_reset":
            for zeroed in event.get("agents_zeroed", []):
                balances[str(zeroed)] = 0
            returned = int(event.get("wea_returned_to_agent0", 0))
            if returned:
                balances[AGENT0] += returned
            negative_violations.clear()
            seen_returns.clear()
            events_replayed = 0
            continue

        if t in _METADATA_TYPES:
            continue

        if t == "registration_confirmed":
            new_id = str(event.get("agent", "") or "")
            old_id = str(event.get("previous_id", "") or "")
            if old_id and new_id and old_id != new_id:
                balances[new_id] += balances[old_id]
                balances[old_id] = 0
            continue

        if t in ("payment", "mint", "hello_world_mint", "reversal", "accept"):
            a = str(event.get("agent", "") or event.get("author", "") or "")
            if a:
                balances[a] += int(event.get("amount", 0))

        elif t == "trajectory_mint":
            a = str(event.get("agent", "") or "")
            if a:
                balances[a] += int(event.get("amount", 0))
            else:
                for i, ag in enumerate(event.get("agents", [])):
                    per = event.get("per_agent", [])
                    if i < len(per):
                        balances[str(ag)] += int(per[i])

        elif t == "escrow_return":
            a = str(
                event.get("recipient", "")
                or event.get("agent", "")
                or event.get("author", "")
                or AGENT0
            )
            amount = int(event.get("amount", 0))
            issue = str(event.get("issue", "_no_issue_"))
            key = (issue, a)
            if key not in seen_returns:
                seen_returns.add(key)
                balances[a] += amount

        elif t == "escrow_return_bulk":
            a = str(
                event.get("recipient", "")
                or event.get("agent", "")
                or event.get("author", "")
                or AGENT0
            )
            balances[a] += int(event.get("amount", 0))

        elif t in ("escrow", "escrow_create"):
            debit = str(
                event.get("agent", "") or event.get("author", "") or ""
            )
            if debit:
                balances[debit] -= int(event.get("amount", 0))

        elif t == "escrow_batch":
            debit = str(
                event.get("author", "") or event.get("agent", "") or AGENT0
            )
            balances[debit] -= int(event.get("total", 0))

        elif t == "agent_removal":
            agent = str(event.get("agent", "") or "")
            if agent:
                balances[agent] = 0
            returned = int(event.get("balance_returned", 0))
            if returned:
                balances[AGENT0] += returned

        else:
            continue

        events_replayed += 1

        for agent, bal in balances.items():
            if bal < 0:
                negative_violations.append({
                    "agent": agent,
                    "balance": bal,
                    "event_type": t,
                    "timestamp": event.get("ts", event.get("timestamp", "")),
                    "issue": event.get("issue"),
                    "file": fname,
                    "line": lineno,
                })

    return {
        "events_replayed": events_replayed,
        "negative_violations": negative_violations,
        "final_balances": dict(balances),
    }


def compare_final(
    computed: dict[str, int],
    balances_json: dict,
    escrow_totals: dict[str, int] | None = None,
) -> list[dict]:
    """
    Compare final computed balances to balances.json with active-escrow tolerance.

    Tolerance rule: if an agent's computed balance exceeds their stored balance
    by exactly their total active escrow obligations (computed - stored == escrow),
    the mismatch is expected and not reported. This covers the case where
    balances.json already reflects an escrow deduction that has not yet appeared
    in the history files.
    """
    if escrow_totals is None:
        escrow_totals = {}
    mismatches: list[dict] = []
    agents = balances_json.get("agents", {})
    if not isinstance(agents, dict):
        return [{"error": "balances.json 'agents' field is not a dict"}]

    for agent_id, info in sorted(agents.items()):
        stored = int(info.get("balance", 0)) if isinstance(info, dict) else 0
        comp = computed.get(agent_id, 0)
        if comp != stored:
            diff = comp - stored
            tolerance = escrow_totals.get(agent_id, 0)
            if diff == tolerance and diff > 0:
                continue
            mismatches.append({
                "agent": agent_id,
                "stored": stored,
                "computed": comp,
                "delta": comp - stored,
            })

    for agent_id, comp in sorted(computed.items()):
        if agent_id not in agents and comp != 0:
            mismatches.append({
                "agent": agent_id,
                "stored": None,
                "computed": comp,
                "delta": None,
                "note": "agent present in history but absent from balances.json",
            })

    return mismatches


def run(root: Path) -> tuple[dict[str, Any], bool]:
    """Full check: load history, replay events, verify balance integrity."""
    balances_path = root / "ledger" / "balances.json"
    history_dir = root / "ledger" / "history"
    escrows_path = root / "ledger" / "escrows.json"

    if not balances_path.exists():
        result: dict[str, Any] = {
            "status": "FAIL",
            "events_replayed": 0,
            "negative_violations": [],
            "final_mismatches": [],
            "summary": f"balances.json not found: {balances_path}",
        }
        return result, False

    try:
        balances_json = json.loads(balances_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        result = {
            "status": "FAIL",
            "events_replayed": 0,
            "negative_violations": [],
            "final_mismatches": [],
            "summary": f"balances.json invalid JSON: {exc}",
        }
        return result, False

    escrow_totals = _load_active_escrow_totals(escrows_path)
    events = load_events(history_dir)
    replay_result = replay(events)

    negative_violations = replay_result["negative_violations"]
    final_mismatches = compare_final(
        replay_result["final_balances"], balances_json, escrow_totals
    )

    passed = (not negative_violations) and (not final_mismatches)
    status = "PASS" if passed else "FAIL"

    parts: list[str] = [f"events_replayed={replay_result['events_replayed']}"]
    if negative_violations:
        parts.append(f"{len(negative_violations)} negative-balance violation(s)")
    if final_mismatches:
        parts.append(f"{len(final_mismatches)} final-balance mismatch(es)")
    if passed:
        parts.append("all checks passed")

    result = {
        "status": status,
        "events_replayed": replay_result["events_replayed"],
        "negative_violations": negative_violations,
        "final_mismatches": final_mismatches,
        "summary": "; ".join(parts),
    }
    return result, passed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Replay history events and assert per-agent balance integrity. "
            "Fails on negative mid-history balances or unreconciled final mismatch."
        )
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root (default: auto-detect from script location)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output result as JSON",
    )
    args = parser.parse_args(argv)

    root = _repo_root(args.root)
    result, passed = run(root)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("--- WeTheAgents History Cumulative Balance Integrity ---")
        print(f"Status          : {result['status']}")
        print(f"Events replayed : {result['events_replayed']}")
        print(f"Neg violations  : {len(result['negative_violations'])}")
        print(f"Final mismatches: {len(result['final_mismatches'])}")
        print(f"Summary         : {result['summary']}")
        if result["negative_violations"]:
            print("\nNegative balance violations (first 10):")
            for v in result["negative_violations"][:10]:
                print(
                    f"  {v['agent']}: balance={v['balance']}"
                    f" after {v['event_type']} at {v.get('timestamp', '?')}"
                    f" issue={v['issue']}"
                )
        if result["final_mismatches"]:
            print("\nFinal balance mismatches:")
            for m in result["final_mismatches"]:
                note = m.get("note", "")
                print(
                    f"  {m['agent']}: stored={m.get('stored')}"
                    f" computed={m.get('computed')}"
                    f" delta={m.get('delta')}"
                    + (f" ({note})" if note else "")
                )

    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
