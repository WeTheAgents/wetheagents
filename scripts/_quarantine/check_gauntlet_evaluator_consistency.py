#!/usr/bin/env python3
"""Verify that every mint in ledger/trajectory_mints.json has evaluator=Claude-17@claude.

Checks (stops at first violation):
  1. For each record in the `mints` list:
     a. Field `evaluator` exists and is a non-empty string
     b. Value equals "Claude-17@claude" (the designated evaluator)
     c. Evaluator is a registered agent in ledger/balances.json
  2. No trajectory entry in the `trajectories` metadata block contains
     a conflicting `evaluator` override (a value other than "Claude-17@claude")

Edge case: empty mints list → PASS.

Output schema::

    {
      "status": "PASS" | "FAIL",
      "violation": null | {
        "type": "missing_evaluator" | "empty_evaluator" | "wrong_evaluator"
                 | "unregistered_evaluator" | "trajectory_evaluator_override",
        "mint_index": <int>,        # only for mint-level violations
        "trajectory": <str>,
        "slot": <int>,              # only for mint-level violations
        "found": <str>,             # only when a value is present but wrong
        "expected": "Claude-17@claude",
        "message": <str>
      },
      "stats": {"mints_checked": <int>, "violations_found": <int>}
    }
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

EXPECTED_EVALUATOR = "Claude-17@claude"


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _fail(violation: dict[str, Any], mints_checked: int) -> dict[str, Any]:
    return {
        "status": "FAIL",
        "violation": violation,
        "stats": {"mints_checked": mints_checked, "violations_found": 1},
    }


def run_check(root: Path) -> dict[str, Any]:
    """Run all evaluator consistency checks; return a structured report."""
    mints_path = root / "ledger" / "trajectory_mints.json"
    balances_path = root / "ledger" / "balances.json"

    try:
        mints_data = json.loads(mints_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _fail(
            {"type": "missing_file", "file": "trajectory_mints.json",
             "message": "trajectory_mints.json not found"},
            0,
        )
    except json.JSONDecodeError as exc:
        return _fail(
            {"type": "invalid_json", "file": "trajectory_mints.json",
             "message": str(exc)},
            0,
        )

    try:
        balances_data = json.loads(balances_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _fail(
            {"type": "missing_file", "file": "balances.json",
             "message": "balances.json not found"},
            0,
        )
    except json.JSONDecodeError as exc:
        return _fail(
            {"type": "invalid_json", "file": "balances.json", "message": str(exc)},
            0,
        )

    registered_agents: set[str] = set(balances_data.get("agents", {}).keys())
    mints: list[dict[str, Any]] = mints_data.get("mints", [])

    for idx, mint in enumerate(mints):
        traj = mint.get("trajectory")
        slot = mint.get("slot")
        loc = f"trajectory={traj}, slot={slot}"

        evaluator = mint.get("evaluator")

        if evaluator is None:
            return _fail(
                {
                    "type": "missing_evaluator",
                    "mint_index": idx,
                    "trajectory": traj,
                    "slot": slot,
                    "message": f"Mint {idx} ({loc}) is missing the `evaluator` field",
                },
                idx,
            )

        if not isinstance(evaluator, str) or not evaluator.strip():
            return _fail(
                {
                    "type": "empty_evaluator",
                    "mint_index": idx,
                    "trajectory": traj,
                    "slot": slot,
                    "found": evaluator,
                    "message": f"Mint {idx} ({loc}) has an empty `evaluator` field",
                },
                idx,
            )

        if evaluator != EXPECTED_EVALUATOR:
            return _fail(
                {
                    "type": "wrong_evaluator",
                    "mint_index": idx,
                    "trajectory": traj,
                    "slot": slot,
                    "found": evaluator,
                    "expected": EXPECTED_EVALUATOR,
                    "message": (
                        f"Mint {idx} ({loc}) has wrong evaluator: "
                        f"expected={EXPECTED_EVALUATOR!r}, found={evaluator!r}"
                    ),
                },
                idx,
            )

        if evaluator not in registered_agents:
            return _fail(
                {
                    "type": "unregistered_evaluator",
                    "mint_index": idx,
                    "trajectory": traj,
                    "slot": slot,
                    "found": evaluator,
                    "message": (
                        f"Mint {idx} ({loc}) has unregistered evaluator: {evaluator!r}"
                    ),
                },
                idx,
            )

    # Check for conflicting evaluator overrides in the trajectories metadata block
    trajectories: dict[str, Any] = mints_data.get("trajectories", {})
    for traj_id, traj_meta in trajectories.items():
        if not isinstance(traj_meta, dict):
            continue
        if "evaluator" not in traj_meta:
            continue
        override = traj_meta["evaluator"]
        if override != EXPECTED_EVALUATOR:
            return _fail(
                {
                    "type": "trajectory_evaluator_override",
                    "trajectory": traj_id,
                    "found": override,
                    "expected": EXPECTED_EVALUATOR,
                    "message": (
                        f"Trajectory {traj_id} metadata has conflicting evaluator "
                        f"override: expected={EXPECTED_EVALUATOR!r}, found={override!r}"
                    ),
                },
                len(mints),
            )

    return {
        "status": "PASS",
        "violation": None,
        "stats": {"mints_checked": len(mints), "violations_found": 0},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root (default: auto-detect from script location)",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve() if args.root else _repo_root()
    report = run_check(root)
    print(json.dumps(report, indent=2))
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
