#!/usr/bin/env python3
"""Verify that every complete gauntlet cycle contains mints for all T1-T5 trajectories.

Each trajectory's slot number equals its cycle number (all trajectories start at slot 1,
so cycle N = slot N for each trajectory). A cycle is *complete* when all five mandatory
trajectories (T1-T5) have minted that slot. T6 is intentionally excluded.

A *violation* occurs when a trajectory has a gap in its slot sequence: it minted a higher
slot (proving it passed the cycle) but never minted the cycle in question. This indicates
a skipped slot, which should never happen under the sequential-slot rule.

The highest observed cycle number is treated as *in-progress* (warning only), because the
heartbeat may be mid-cycle when this script runs.

Exit code: 0 (PASS) if no violations exist, 1 (FAIL) if any trajectory skipped a slot.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

MANDATORY_TRAJECTORIES = frozenset({"T1", "T2", "T3", "T4", "T5"})


def _load_trajectory_mints(root: Path) -> dict[str, Any]:
    path = root / "ledger" / "trajectory_mints.json"
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def run_check(root: Path) -> dict[str, Any]:
    """Run the cycle-completeness check and return a machine-readable payload."""
    data = _load_trajectory_mints(root)
    if not isinstance(data, dict):
        raise ValueError("trajectory_mints.json is not a JSON object")

    mints: list[dict[str, Any]] = data.get("mints", [])
    if not isinstance(mints, list):
        raise ValueError("trajectory_mints.json.mints is not a list")

    # Build per-trajectory max slots and per-slot trajectory sets (T1-T5 only)
    traj_max_slots: dict[str, int] = {}
    cycle_map: dict[int, set[str]] = {}

    for mint in mints:
        trajectory = mint.get("trajectory")
        if not isinstance(trajectory, str):
            continue
        if trajectory not in MANDATORY_TRAJECTORIES:
            continue

        slot = mint.get("slot")
        if isinstance(slot, bool) or not isinstance(slot, int) or slot <= 0:
            continue

        cycle_map.setdefault(slot, set()).add(trajectory)
        if slot > traj_max_slots.get(trajectory, 0):
            traj_max_slots[trajectory] = slot

    if not cycle_map:
        return {
            "status": "PASS",
            "violations": [],
            "warnings": [],
            "summary": {
                "total_cycles_checked": 0,
                "complete_cycles": 0,
                "partial_cycles": 0,
                "in_progress_cycle": None,
                "total_violations": 0,
            },
        }

    max_cycle = max(cycle_map.keys())

    violations: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    complete_count = 0

    for cycle in range(1, max_cycle + 1):
        present = cycle_map.get(cycle, set())
        all_missing = sorted(MANDATORY_TRAJECTORIES - present)

        if not all_missing:
            complete_count += 1
            continue

        # Determine which missing trajectories have MOVED PAST this cycle
        # (max_slot > cycle) — these skipped the slot and are genuine violations.
        # Trajectories with max_slot <= cycle simply haven't reached it yet (in-progress).
        skipped = [t for t in all_missing if traj_max_slots.get(t, 0) > cycle]

        if not skipped:
            # All missing trajectories are still approaching this cycle.
            # Only report as in-progress warning if this is the highest cycle seen.
            if cycle == max_cycle:
                warnings.append({
                    "cycle": cycle,
                    "present": sorted(present),
                    "missing": all_missing,
                })
        else:
            # At least one trajectory skipped this cycle — genuine violation.
            record: dict[str, Any] = {
                "cycle": cycle,
                "present": sorted(present),
                "missing": all_missing,
                "skipped_by": skipped,
            }
            if cycle == max_cycle:
                # Even a skipped-slot at max_cycle is a warning, not a violation,
                # because no trajectory can have max_slot > max_cycle by definition.
                # (This branch is unreachable in practice but kept for completeness.)
                warnings.append(record)
            else:
                violations.append(record)

    return {
        "status": "PASS" if not violations else "FAIL",
        "violations": violations,
        "warnings": warnings,
        "summary": {
            "total_cycles_checked": max_cycle,
            "complete_cycles": complete_count,
            "partial_cycles": len(violations) + len(warnings),
            "in_progress_cycle": max_cycle if warnings else None,
            "total_violations": len(violations),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify T1-T5 all minted in every complete gauntlet cycle."
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Repository root (default: current directory)",
    )
    args = parser.parse_args(argv)

    try:
        result = run_check(Path(args.root).resolve())
    except (FileNotFoundError, json.JSONDecodeError, ValueError, TypeError) as exc:
        result = {
            "status": "FAIL",
            "violations": [],
            "warnings": [],
            "summary": {
                "total_cycles_checked": 0,
                "complete_cycles": 0,
                "partial_cycles": 0,
                "in_progress_cycle": None,
                "total_violations": 1,
                "error": str(exc),
            },
        }

    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
