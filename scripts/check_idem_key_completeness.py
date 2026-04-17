#!/usr/bin/env python3
"""check_idem_key_completeness.py

Verify that every payment, escrow, trajectory_mint, and escrow_return event
in ledger/history/*.jsonl has a corresponding entry in ledger/idem_keys.json.

For each history event with type in {payment, escrow, trajectory_mint, escrow_return}:
  - VIOLATION if no matching idem key exists.

For each idem key in a financial namespace with no matching history event:
  - WARNING (orphan key — key written but operation not recorded in history).

idem key formats observed in ledger/idem_keys.json:
  escrow         escrow|{issue}|{agent}  or  escrow|{issue}
  escrow_return  escrow_return|{issue}|{agent}  or  escrow_return|{issue}
  payment        payment|{issue}|{agent}[|{suffix}]  OR  sha256-hash → dict
  trajectory_mint  trajectory_mint|{trajectory}|{slot}

Special handling:
  - escrow_create history events are treated as escrow (alternate type name).
  - escrow_batch history events are expanded per-issue so that individual
    escrow|N keys can match.
  - escrow_return_bulk history events are expanded per-issue.
  - Some financial keys are stored at the top level of idem_keys.json (not
    inside data["keys"]); both locations are checked.
  - Agent aliases from ledger/agent_aliases.json are applied when reading
    history and idem keys, normalising old names to canonical replacements.

Output: JSON written to stdout.
Exit codes:
  0  no violations
  1  one or more violations found
  2  required files missing (SKIP for ledger_health_report.py)

Usage:
    python scripts/check_idem_key_completeness.py [--root PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, DefaultDict, TypedDict


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Namespace prefixes that represent financial operations
FINANCIAL_PREFIXES: frozenset[str] = frozenset(
    {"payment", "escrow", "escrow_return", "trajectory_mint"}
)

# Hash-key dict actions that are financial
FINANCIAL_HASH_ACTIONS: frozenset[str] = frozenset({"payment"})

# History event types checked for VIOLATION
TARGET_HISTORY_TYPES: frozenset[str] = frozenset(
    {"payment", "escrow", "escrow_create", "trajectory_mint", "escrow_return"}
)

IssueActorKey = tuple[str, str]
TrajectorySlotKey = tuple[str, str]


class ClassifiedIdemKeys(TypedDict):
    escrow: DefaultDict[str, list[str]]
    escrow_return: DefaultDict[str, list[str]]
    payment_string: DefaultDict[IssueActorKey, list[str]]
    payment_hash: DefaultDict[IssueActorKey, list[str]]
    trajectory_mint: DefaultDict[TrajectorySlotKey, list[str]]


class HistoryIndex(TypedDict):
    escrow_issues: set[str]
    escrow_return_issues: set[str]
    payments: set[IssueActorKey]
    trajectory_mints: set[TrajectorySlotKey]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize(actor: str, aliases: dict[str, str]) -> str:
    return aliases.get(actor, actor)


# ---------------------------------------------------------------------------
# Load functions (injectable paths → deterministic tests)
# ---------------------------------------------------------------------------


def load_aliases(path: Path) -> dict[str, str]:
    """Load ledger/agent_aliases.json → {old: canonical}. Returns {} on error."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def load_idem_keys(path: Path) -> dict[str, object]:
    """Load all idem keys from idem_keys.json.

    Merges data["keys"] with any top-level financial keys (some old keys were
    written directly at the root level).  Returns {} if the file is missing.
    Exits 2 on parse error (SKIP for ledger_health_report.py).
    """
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        print(f"ERROR: idem_keys.json corrupted: {exc}", file=sys.stderr)
        sys.exit(2)
    except OSError as exc:
        print(f"ERROR: cannot read idem_keys.json: {exc}", file=sys.stderr)
        sys.exit(2)

    if not isinstance(data, dict):
        return {}

    # Primary store: data["keys"]
    merged: dict[str, object] = {}
    nested = data.get("keys", {})
    if isinstance(nested, dict):
        merged.update(nested)

    # Secondary: top-level financial keys (don't overwrite nested values)
    for k, v in data.items():
        if k in ("keys", "version"):
            continue
        prefix = k.split("|")[0]
        if prefix in FINANCIAL_PREFIXES:
            merged.setdefault(k, v)

    return merged


def load_history_events(history_dir: Path) -> list[dict[str, Any]]:
    """Load all history events from history/*.jsonl, in filename (date) order."""
    events: list[dict[str, Any]] = []
    if not history_dir.is_dir():
        return events
    for jsonl_file in sorted(history_dir.glob("*.jsonl")):
        try:
            text = jsonl_file.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


# ---------------------------------------------------------------------------
# Idem key classification
# ---------------------------------------------------------------------------


def classify_idem_keys(
    all_keys: dict[str, object],
    aliases: dict[str, str],
) -> ClassifiedIdemKeys:
    """Break idem keys into lookup structures for fast matching.

    Returns a dict with keys:
      "escrow"         : {issue_str: [raw_key, ...]}
      "escrow_return"  : {issue_str: [raw_key, ...]}
      "payment_string" : {(issue_str, actor_str): [raw_key, ...]}
      "payment_hash"   : {(issue_str, actor_str): [raw_key, ...]}
      "trajectory_mint": {(trajectory, slot_str): [raw_key, ...]}
    Actors are normalised via aliases.
    """
    classified: ClassifiedIdemKeys = {
        "escrow": defaultdict(list),
        "escrow_return": defaultdict(list),
        "payment_string": defaultdict(list),
        "payment_hash": defaultdict(list),
        "trajectory_mint": defaultdict(list),
    }

    for raw_key, value in all_keys.items():
        if isinstance(value, dict):
            # Hash-based key
            action = value.get("action", "")
            if action in FINANCIAL_HASH_ACTIONS:
                issue = str(value.get("issue", ""))
                actor = _normalize(str(value.get("agent", "")), aliases)
                classified["payment_hash"][(issue, actor)].append(raw_key)
        else:
            # String-based key
            parts = raw_key.split("|")
            if not parts:
                continue
            prefix = parts[0]

            if prefix == "escrow" and len(parts) >= 2:
                issue = parts[1]
                classified["escrow"][issue].append(raw_key)

            elif prefix == "escrow_return" and len(parts) >= 2:
                issue = parts[1]
                classified["escrow_return"][issue].append(raw_key)

            elif prefix == "payment" and len(parts) >= 3:
                issue = parts[1]
                actor = _normalize(parts[2], aliases)
                classified["payment_string"][(issue, actor)].append(raw_key)

            elif prefix == "trajectory_mint" and len(parts) >= 3:
                trajectory = parts[1]
                slot = parts[2]
                classified["trajectory_mint"][(trajectory, slot)].append(raw_key)

    return classified


# ---------------------------------------------------------------------------
# History indexing
# ---------------------------------------------------------------------------


def build_history_index(
    events: list[dict[str, Any]],
    aliases: dict[str, str],
) -> HistoryIndex:
    """Index history events for fast lookup.

    Returns a dict with keys:
      "escrow_issues"        : {issue_str}  (set — escrow/escrow_create/escrow_batch)
      "escrow_return_issues" : {issue_str}  (escrow_return/escrow_return_bulk)
      "payments"             : {(issue_str, actor_str)}  (payment events)
      "trajectory_mints"     : {(trajectory, slot_str)}  (trajectory_mint events)
    Actors are normalised via aliases.
    """
    index: HistoryIndex = {
        "escrow_issues": set(),
        "escrow_return_issues": set(),
        "payments": set(),
        "trajectory_mints": set(),
    }

    for event in events:
        t = event.get("type", "")

        if t in ("escrow", "escrow_create"):
            issue = str(event.get("issue", ""))
            index["escrow_issues"].add(issue)

        elif t == "escrow_batch":
            for issue_n in event.get("issues", []):
                index["escrow_issues"].add(str(issue_n))

        elif t == "escrow_return":
            issue = str(event.get("issue", ""))
            index["escrow_return_issues"].add(issue)

        elif t == "escrow_return_bulk":
            for issue_n in event.get("issues", []):
                index["escrow_return_issues"].add(str(issue_n))

        elif t == "payment":
            issue = str(event.get("issue", ""))
            raw_actor = event.get("agent") or event.get("author") or ""
            actor = _normalize(str(raw_actor), aliases)
            index["payments"].add((issue, actor))

        elif t == "trajectory_mint":
            trajectory = str(event.get("trajectory", ""))
            slot = str(event.get("slot", ""))
            index["trajectory_mints"].add((trajectory, slot))

    return index


# ---------------------------------------------------------------------------
# Core check
# ---------------------------------------------------------------------------


def run_completeness_check(
    all_idem_keys: dict[str, object],
    events: list[dict[str, Any]],
    aliases: dict[str, str],
) -> tuple[list[dict], list[dict]]:
    """Return (violations, warnings).

    violations — history events with no corresponding idem key (VIOLATION).
    warnings   — financial idem keys with no corresponding history event (WARNING).
    """
    classified = classify_idem_keys(all_idem_keys, aliases)
    history = build_history_index(events, aliases)

    violations: list[dict] = []
    warnings: list[dict] = []

    # -----------------------------------------------------------------------
    # Direction 1: every target history event must have an idem key (VIOLATION)
    # -----------------------------------------------------------------------
    for event in events:
        t = event.get("type", "")
        if t not in TARGET_HISTORY_TYPES:
            continue

        ts = event.get("timestamp") or event.get("event_at") or ""

        if t == "trajectory_mint":
            trajectory = str(event.get("trajectory", ""))
            slot = str(event.get("slot", ""))
            if (trajectory, slot) not in classified["trajectory_mint"]:
                violations.append({
                    "event_type": "trajectory_mint",
                    "trajectory": trajectory,
                    "slot": slot,
                    "timestamp": ts,
                    "detail": f"No idem key trajectory_mint|{trajectory}|{slot}",
                })

        elif t in ("escrow", "escrow_create"):
            issue = str(event.get("issue", ""))
            if issue not in classified["escrow"]:
                raw_actor = event.get("author") or event.get("agent") or ""
                actor = _normalize(str(raw_actor), aliases)
                violations.append({
                    "event_type": "escrow",
                    "issue": issue,
                    "actor": actor,
                    "timestamp": ts,
                    "detail": f"No idem key matching escrow|{issue}",
                })

        elif t == "escrow_return":
            issue = str(event.get("issue", ""))
            if issue not in classified["escrow_return"]:
                raw_actor = event.get("author") or event.get("agent") or ""
                actor = _normalize(str(raw_actor), aliases)
                violations.append({
                    "event_type": "escrow_return",
                    "issue": issue,
                    "actor": actor,
                    "timestamp": ts,
                    "detail": f"No idem key matching escrow_return|{issue}",
                })

        elif t == "payment":
            issue = str(event.get("issue", ""))
            raw_actor = event.get("agent") or event.get("author") or ""
            actor = _normalize(str(raw_actor), aliases)
            if (
                (issue, actor) not in classified["payment_hash"]
                and (issue, actor) not in classified["payment_string"]
            ):
                violations.append({
                    "event_type": "payment",
                    "issue": issue,
                    "actor": actor,
                    "timestamp": ts,
                    "detail": f"No idem key for payment issue={issue} agent={actor}",
                })

    # -----------------------------------------------------------------------
    # Direction 2: every financial idem key should have a history event (WARNING)
    # -----------------------------------------------------------------------

    # trajectory_mint orphan keys
    for (trajectory, slot), keys in classified["trajectory_mint"].items():
        if (trajectory, slot) not in history["trajectory_mints"]:
            for k in keys:
                warnings.append({
                    "idem_key": k,
                    "namespace": "trajectory_mint",
                    "detail": f"No trajectory_mint event for trajectory={trajectory} slot={slot}",
                })

    # escrow orphan keys
    for issue, keys in classified["escrow"].items():
        if issue not in history["escrow_issues"]:
            for k in keys:
                warnings.append({
                    "idem_key": k,
                    "namespace": "escrow",
                    "detail": f"No escrow event for issue={issue}",
                })

    # escrow_return orphan keys
    for issue, keys in classified["escrow_return"].items():
        if issue not in history["escrow_return_issues"]:
            for k in keys:
                warnings.append({
                    "idem_key": k,
                    "namespace": "escrow_return",
                    "detail": f"No escrow_return event for issue={issue}",
                })

    # payment_string orphan keys
    for (issue, actor), keys in classified["payment_string"].items():
        if (issue, actor) not in history["payments"]:
            for k in keys:
                warnings.append({
                    "idem_key": k,
                    "namespace": "payment",
                    "detail": f"No payment event for issue={issue} agent={actor}",
                })

    # payment_hash orphan keys
    for (issue, actor), keys in classified["payment_hash"].items():
        if (issue, actor) not in history["payments"]:
            for k in keys:
                warnings.append({
                    "idem_key": k,
                    "namespace": "payment",
                    "detail": f"No payment event for issue={issue} agent={actor}",
                })

    return violations, warnings


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Check idem key completeness for all ledger mutations"
    )
    p.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Repo root directory (default: two levels up from this script)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = args.root or Path(__file__).resolve().parent.parent

    idem_path = repo_root / "ledger" / "idem_keys.json"
    history_dir = repo_root / "ledger" / "history"
    aliases_path = repo_root / "ledger" / "agent_aliases.json"

    if not idem_path.exists():
        print(f"SKIP: idem_keys.json not found at {idem_path}", file=sys.stderr)
        return 2

    if not history_dir.is_dir():
        print(f"SKIP: history directory not found at {history_dir}", file=sys.stderr)
        return 2

    aliases = load_aliases(aliases_path)
    all_idem_keys = load_idem_keys(idem_path)
    events = load_history_events(history_dir)

    violations, warnings = run_completeness_check(all_idem_keys, events, aliases)

    events_checked = sum(
        1 for e in events if e.get("type") in TARGET_HISTORY_TYPES
    )

    status = "FAIL" if violations else "PASS"

    report = {
        "status": status,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "events_checked": events_checked,
            "violations": len(violations),
            "warnings": len(warnings),
        },
        "violations": violations,
        "warnings": warnings,
    }

    print(json.dumps(report, indent=2))
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
