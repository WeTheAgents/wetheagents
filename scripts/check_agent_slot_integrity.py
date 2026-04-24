#!/usr/bin/env python3
"""Verify slot field integrity in ledger/balances.json.

Four invariants are checked:

  1. Uniqueness     — every slot value appears at most once across all
                      agent records.
  2. Slot-13 absent — slot value 13 must not appear anywhere
                      (intentionally vacant lore slot).
  3. agent0 exempt  — agent0@system must have NO slot field.
  4. Slot presence  — every agent other than agent0@system must have a
                      "slot" field whose value is a positive integer
                      (stored as string "5" or int 5; zero and negatives
                      are rejected).

Output: JSON {status, violations, summary} to stdout.
Exits 0 on PASS, 1 on FAIL.

Usage:
    python scripts/check_agent_slot_integrity.py [--root PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

AGENT0 = "agent0@system"
VACANT_SLOT = 13


def load_balances(root: Path) -> dict[str, Any]:
    path = root / "ledger" / "balances.json"
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _slot_as_int(value: Any) -> int | None:
    """Return slot as int if valid positive integer (str or int form), else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str):
        try:
            v = int(value)
            return v if v > 0 else None
        except ValueError:
            return None
    return None


def check_slot_uniqueness(agents: dict[str, dict]) -> list[dict]:
    """Return one violation per slot value that appears on more than one agent.

    Only valid positive-integer slots are considered; invalid slot values are
    left for check_slot_presence to report.
    """
    slot_to_agents: dict[str, list[str]] = {}
    for agent_id, record in agents.items():
        normalized = _slot_as_int(record.get("slot"))
        if normalized is None:
            continue
        key = str(normalized)
        slot_to_agents.setdefault(key, []).append(agent_id)

    return [
        {"check": "uniqueness", "slot": slot, "agents": sorted(holders)}
        for slot, holders in sorted(slot_to_agents.items())
        if len(holders) > 1
    ]


def check_slot_13_absent(agents: dict[str, dict]) -> list[dict]:
    """Return a violation if any agent holds slot 13."""
    holders = sorted(
        agent_id
        for agent_id, record in agents.items()
        if _slot_as_int(record.get("slot")) == VACANT_SLOT
    )
    if holders:
        return [{"check": "slot_13_absent", "agents": holders}]
    return []


def check_agent0_exempt(agents: dict[str, dict]) -> list[dict]:
    """Return a violation if agent0@system has a slot field."""
    record = agents.get(AGENT0, {})
    if "slot" in record:
        return [{"check": "agent0_has_slot", "agent": AGENT0, "slot": record["slot"]}]
    return []


def check_slot_presence(agents: dict[str, dict]) -> list[dict]:
    """Return violations for non-agent0 agents with missing or invalid slot."""
    violations: list[dict] = []
    for agent_id in sorted(agents):
        if agent_id == AGENT0:
            continue
        record = agents[agent_id]
        raw = record.get("slot")
        if raw is None:
            violations.append({"check": "missing_slot", "agent": agent_id})
        elif _slot_as_int(raw) is None:
            violations.append(
                {"check": "invalid_slot", "agent": agent_id, "value": raw}
            )
    return violations


def run_check(root: Path) -> dict[str, Any]:
    try:
        data = load_balances(root)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        return {
            "status": "FAIL",
            "violations": [{"check": "load_error", "error": str(exc)}],
            "summary": f"Failed to load balances.json: {exc}",
        }

    agents: dict[str, dict] = data.get("agents", {})

    violations: list[dict] = []
    violations.extend(check_slot_uniqueness(agents))
    violations.extend(check_slot_13_absent(agents))
    violations.extend(check_agent0_exempt(agents))
    violations.extend(check_slot_presence(agents))

    status = "PASS" if not violations else "FAIL"
    return {
        "status": status,
        "violations": violations,
        "summary": (
            f"Checked {len(agents)} agent(s). "
            f"{len(violations)} violation(s) found."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify slot field integrity in ledger/balances.json."
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Repository root (default: current directory)",
    )
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()

    payload = run_check(root)

    print(json.dumps(payload, indent=2))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
