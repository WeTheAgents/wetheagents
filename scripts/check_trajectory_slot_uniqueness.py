#!/usr/bin/env python3
"""Detect double-mints and next_slot drift in gauntlet trajectory history.

Two checks performed against ledger/history/*.jsonl and
ledger/trajectory_mints.json:

  1. Double-mints  — each (trajectory, slot) pair must appear at most once
     across all history JSONL files.  A duplicate means the same slot was
     minted twice and two agents were paid for the same work.

  2. next_slot coherence — for each trajectory the declared next_slot in
     trajectory_mints.json must equal max(minted_slots) + 1.  If no slots
     have been minted yet the expected value is 1.  Drift in either direction
     (too high = next_slot skipped ahead past unminted slots, too low =
     next_slot points at an already-minted slot) is reported.

Output: JSON with keys status (PASS/FAIL), double_mints, next_slot_drift.
Exits 0 on PASS, 1 on FAIL.

Usage:
    python scripts/check_trajectory_slot_uniqueness.py [--root PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_history_mint_events(root: Path) -> list[dict[str, Any]]:
    """Return all trajectory_mint events from ledger/history/*.jsonl."""
    events: list[dict[str, Any]] = []
    history_dir = root / "ledger" / "history"
    for path in sorted(history_dir.glob("*.jsonl")):
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "trajectory_mint":
                    events.append(event)
    return events


def load_trajectory_mints(root: Path) -> dict[str, Any]:
    """Return parsed ledger/trajectory_mints.json."""
    path = root / "ledger" / "trajectory_mints.json"
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def find_double_mints(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a record for every (trajectory, slot) pair seen more than once.

    Each returned record contains trajectory, slot, and count.
    """
    counts: dict[tuple[str, int], int] = {}
    for ev in events:
        traj = ev.get("trajectory")
        slot = ev.get("slot")
        if traj is None or slot is None:
            continue
        key = (str(traj), int(slot))
        counts[key] = counts.get(key, 0) + 1

    return [
        {"trajectory": traj, "slot": slot, "count": count}
        for (traj, slot), count in sorted(counts.items())
        if count > 1
    ]


def find_next_slot_drift(
    events: list[dict[str, Any]],
    trajectories: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return a record for every trajectory whose declared next_slot is wrong.

    Expected next_slot = max(history_slots) + 1, or 1 if no history exists.

    Also flags trajectories present in history but absent from
    trajectory_mints.json (declared_next_slot will be null).
    """
    # Compute max minted slot per trajectory from history
    max_slot_by_traj: dict[str, int] = {}
    for ev in events:
        traj = ev.get("trajectory")
        slot = ev.get("slot")
        if traj is None or slot is None:
            continue
        traj = str(traj)
        slot = int(slot)
        if traj not in max_slot_by_traj or slot > max_slot_by_traj[traj]:
            max_slot_by_traj[traj] = slot

    drift: list[dict[str, Any]] = []

    # Check trajectories that appear in history
    for traj in sorted(max_slot_by_traj):
        expected = max_slot_by_traj[traj] + 1
        if traj not in trajectories:
            # Trajectory exists in history but is missing from mints JSON
            drift.append(
                {
                    "trajectory": traj,
                    "history_max_slot": max_slot_by_traj[traj],
                    "expected_next_slot": expected,
                    "declared_next_slot": None,
                }
            )
            continue
        declared = trajectories[traj].get("next_slot")
        if declared != expected:
            drift.append(
                {
                    "trajectory": traj,
                    "history_max_slot": max_slot_by_traj[traj],
                    "expected_next_slot": expected,
                    "declared_next_slot": declared,
                }
            )

    # Check trajectories in mints JSON that have no history events yet
    for traj in sorted(trajectories):
        if traj in max_slot_by_traj:
            continue  # already handled above
        declared = trajectories[traj].get("next_slot")
        if declared != 1:
            drift.append(
                {
                    "trajectory": traj,
                    "history_max_slot": None,
                    "expected_next_slot": 1,
                    "declared_next_slot": declared,
                }
            )

    return drift


# ---------------------------------------------------------------------------
# Main check runner
# ---------------------------------------------------------------------------


def run_check(root: Path) -> dict[str, Any]:
    """Run both checks and return the JSON payload."""
    events = load_history_mint_events(root)
    mints_data = load_trajectory_mints(root)
    trajectories: dict[str, dict[str, Any]] = mints_data.get("trajectories", {})

    double_mints = find_double_mints(events)
    next_slot_drift = find_next_slot_drift(events, trajectories)

    status = "PASS" if not double_mints and not next_slot_drift else "FAIL"
    return {
        "status": status,
        "double_mints": double_mints,
        "next_slot_drift": next_slot_drift,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Detect double-mints and next_slot drift in trajectory history."
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Repository root (default: current directory)",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    try:
        payload = run_check(root)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        payload = {
            "status": "FAIL",
            "double_mints": [],
            "next_slot_drift": [],
            "error": str(exc),
        }
    print(json.dumps(payload, indent=2))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
