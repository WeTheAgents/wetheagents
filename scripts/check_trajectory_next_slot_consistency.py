#!/usr/bin/env python3
"""Validate trajectory mint continuity and next-slot declarations.

Loads `ledger/trajectory_mints.json` and scans
`ledger/history/*.jsonl` for mint events. For each trajectory T1-T6:

1. Verify `next_slot` equals `max_minted_slot + 1` based on the history.
2. If there are no mints for that trajectory, `next_slot` must be `20`.
3. Detect duplicate mint slots (`trajectory` + `slot` appears twice).

Exits 0 if checks pass, 1 if any violation is found.

Usage:
    python scripts/check_trajectory_next_slot_consistency.py [--root PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

TARGET_TRAJECTORIES = [f"T{i}" for i in range(1, 7)]
NO_MINT_NEXT_SLOT = 20


def load_trajectory_mints(root: Path) -> dict[str, Any]:
    """Return parsed `ledger/trajectory_mints.json`."""
    with (root / "ledger" / "trajectory_mints.json").open(encoding="utf-8") as fh:
        return json.load(fh)


def load_mint_events(root: Path) -> list[dict[str, Any]]:
    """Read all trajectory-like mint events from `ledger/history/*.jsonl`."""
    events: list[dict[str, Any]] = []
    history_dir = root / "ledger" / "history"
    for path in sorted(history_dir.glob("*.jsonl")):
        with path.open(encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                event_type = event.get("type")
                if event_type in {"trajectory_mint", "gauntlet_mint"}:
                    events.append(event)
    return events


def _coerce_slot(slot: Any) -> int | None:
    """Coerce slot values to int, returning None if conversion fails."""
    try:
        return int(slot)
    except (TypeError, ValueError):
        return None


def find_duplicate_slots(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return duplicate `(trajectory, slot)` pairs for target trajectories."""
    counts: dict[tuple[str, int], int] = {}
    for ev in events:
        traj = ev.get("trajectory")
        slot = _coerce_slot(ev.get("slot"))
        if traj is None or slot is None:
            continue
        if traj not in TARGET_TRAJECTORIES:
            continue
        key = (str(traj), slot)
        counts[key] = counts.get(key, 0) + 1

    return [
        {"trajectory": traj, "slot": slot, "count": count}
        for (traj, slot), count in sorted(counts.items())
        if count > 1
    ]


def find_next_slot_violations(
    events: list[dict[str, Any]],
    trajectory_info: dict[str, Any],
) -> list[dict[str, Any]]:
    """Compare declared `next_slot` against expected values for T1-T6."""
    max_slot: dict[str, int] = {}
    for ev in events:
        traj = ev.get("trajectory")
        slot = _coerce_slot(ev.get("slot"))
        if traj is None or slot is None:
            continue
        if traj not in TARGET_TRAJECTORIES:
            continue
        if traj not in max_slot or slot > max_slot[traj]:
            max_slot[traj] = slot

    violations: list[dict[str, Any]] = []
    for traj in TARGET_TRAJECTORIES:
        declared = trajectory_info.get(traj, {}).get("next_slot")
        if traj in max_slot:
            expected = max_slot[traj] + 1
            history_max_slot = max_slot[traj]
        else:
            expected = NO_MINT_NEXT_SLOT
            history_max_slot = None

        if traj not in trajectory_info:
            violations.append(
                {
                    "trajectory": traj,
                    "history_max_slot": history_max_slot,
                    "expected_next_slot": expected,
                    "declared_next_slot": None,
                }
            )
            continue

        if declared != expected:
            violations.append(
                {
                    "trajectory": traj,
                    "history_max_slot": history_max_slot,
                    "expected_next_slot": expected,
                    "declared_next_slot": declared,
                }
            )

    return violations


def run_check(root: Path) -> dict[str, Any]:
    """Run the duplicate-slot and next-slot checks."""
    events = load_mint_events(root)
    mints_data = load_trajectory_mints(root)
    trajectories: dict[str, Any] = mints_data.get("trajectories", {})

    duplicate_slots = find_duplicate_slots(events)
    next_slot_violations = find_next_slot_violations(events, trajectories)

    return {
        "status": "PASS"
        if not duplicate_slots and not next_slot_violations
        else "FAIL",
        "duplicate_slots": duplicate_slots,
        "next_slot_violations": next_slot_violations,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate trajectory mint next-slot consistency."
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Repository root (default: current directory).",
    )
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()

    try:
        payload = run_check(root)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        payload = {
            "status": "FAIL",
            "duplicate_slots": [],
            "next_slot_violations": [],
            "error": str(exc),
        }

    print(json.dumps(payload, indent=2))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
