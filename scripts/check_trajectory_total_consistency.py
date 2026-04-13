#!/usr/bin/env python3
"""Verify trajectory mint running totals in ledger/trajectory_mints.json.

Checks:
  1. Each trajectory's ``total_minted`` matches the sum of mint ``amount``
     values for that trajectory.
  2. Top-level ``total_minted`` matches the sum of all declared
     trajectory-level ``total_minted`` counters.

The script always prints JSON with top-level ``status``, ``mismatches``, and
``summary`` fields, then exits 0 on PASS and 1 on FAIL.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def load_trajectory_mints(root: Path) -> dict[str, Any]:
    """Load ``ledger/trajectory_mints.json`` from the repository root."""
    path = root / "ledger" / "trajectory_mints.json"
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def sum_mint_amounts_by_trajectory(mints: list[dict[str, Any]]) -> dict[str, int]:
    """Return summed mint amounts grouped by trajectory."""
    totals: dict[str, int] = {}
    for entry in mints:
        trajectory = entry.get("trajectory")
        amount = entry.get("amount", 0)
        if not isinstance(trajectory, str):
            continue
        totals[trajectory] = totals.get(trajectory, 0) + amount
    return totals


def find_mismatches(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Return machine-readable mismatch records for running-total drift."""
    mismatches: list[dict[str, Any]] = []
    trajectories = data.get("trajectories", {})
    mints = data.get("mints", [])
    computed_totals = sum_mint_amounts_by_trajectory(mints)

    for trajectory, info in sorted(trajectories.items()):
        declared_total = info.get("total_minted", 0)
        computed_total = computed_totals.get(trajectory, 0)
        if declared_total != computed_total:
            mismatches.append(
                {
                    "type": "trajectory_total_mismatch",
                    "trajectory": trajectory,
                    "declared_total_minted": declared_total,
                    "computed_total_minted": computed_total,
                }
            )

    for trajectory in sorted(computed_totals):
        if trajectory not in trajectories:
            mismatches.append(
                {
                    "type": "unknown_trajectory_in_mints",
                    "trajectory": trajectory,
                    "computed_total_minted": computed_totals[trajectory],
                }
            )

    declared_top_level_total = data.get("total_minted", 0)
    summed_trajectory_totals = sum(
        info.get("total_minted", 0) for info in trajectories.values()
    )
    if declared_top_level_total != summed_trajectory_totals:
        mismatches.append(
            {
                "type": "top_level_total_mismatch",
                "declared_total_minted": declared_top_level_total,
                "summed_trajectory_total_minted": summed_trajectory_totals,
            }
        )

    return mismatches


def build_summary(data: dict[str, Any]) -> dict[str, Any]:
    """Build a compact summary for reporting and tests."""
    trajectories = data.get("trajectories", {})
    mints = data.get("mints", [])
    computed_totals = sum_mint_amounts_by_trajectory(mints)

    return {
        "trajectory_count": len(trajectories),
        "mint_count": len(mints),
        "top_level_total_minted": data.get("total_minted", 0),
        "summed_trajectory_total_minted": sum(
            info.get("total_minted", 0) for info in trajectories.values()
        ),
        "summed_mint_amounts": sum(computed_totals.values()),
    }


def run_check(root: Path) -> dict[str, Any]:
    """Run the consistency check and return the JSON payload."""
    data = load_trajectory_mints(root)
    mismatches = find_mismatches(data)
    payload = {
        "status": "PASS" if not mismatches else "FAIL",
        "mismatches": mismatches,
        "summary": build_summary(data),
    }
    payload["summary"]["mismatch_count"] = len(mismatches)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify trajectory running totals in trajectory_mints.json."
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
            "mismatches": [
                {
                    "type": "load_error",
                    "message": str(exc),
                }
            ],
            "summary": {
                "trajectory_count": 0,
                "mint_count": 0,
                "top_level_total_minted": 0,
                "summed_trajectory_total_minted": 0,
                "summed_mint_amounts": 0,
                "mismatch_count": 1,
            },
        }
    print(json.dumps(payload, indent=2))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
