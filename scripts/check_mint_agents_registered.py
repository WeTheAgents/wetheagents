#!/usr/bin/env python3
"""Check that every trajectory mint agent is registered in balances.json.

Reads:
  - ledger/trajectory_mints.json
  - ledger/balances.json

Rule:
  - Every agent ID listed in each mint entry's agents[] array must exist in
    balances["agents"].

Outputs JSON to stdout.
Exits 0 on PASS, 1 on FAIL.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    """Load a JSON file or raise ValueError with a stable message."""
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise ValueError(f"{path.name} not found") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path.name} contains invalid JSON: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"Could not read {path.name}: {exc}") from exc


def get_registered_agent_ids(balances_payload: Any) -> set[str]:
    """Extract registered agent IDs from balances.json payload."""
    if not isinstance(balances_payload, dict):
        raise ValueError("balances.json must contain a top-level JSON object")

    agents = balances_payload.get("agents")
    if not isinstance(agents, dict):
        raise ValueError("balances.json must contain an object at key 'agents'")

    return {str(agent_id) for agent_id in agents}


def get_mints(trajectory_payload: Any) -> list[Any]:
    """Extract mint entries from trajectory_mints.json payload."""
    if not isinstance(trajectory_payload, dict):
        raise ValueError("trajectory_mints.json must contain a top-level JSON object")

    mints = trajectory_payload.get("mints")
    if not isinstance(mints, list):
        raise ValueError("trajectory_mints.json must contain a list at key 'mints'")

    return mints


def _mint_context(mint: dict[str, Any], index: int) -> dict[str, Any]:
    """Return stable identifying details for a mint entry."""
    return {
        "mint_index": index,
        "trajectory": mint.get("trajectory", "(unknown)"),
        "slot": mint.get("slot", "(unknown)"),
        "idem_key": mint.get("idem_key", "(missing idem_key)"),
    }


def find_unregistered_mint_agents(
    mints: list[Any],
    registered_agent_ids: set[str],
) -> tuple[list[dict[str, Any]], int]:
    """Return violations for unknown mint agents plus checked agent count."""
    violations: list[dict[str, Any]] = []
    agent_refs_checked = 0

    for mint_index, mint in enumerate(mints):
        if not isinstance(mint, dict):
            violations.append(
                {
                    "mint_index": mint_index,
                    "reason": f"trajectory_mints.json mints[{mint_index}] must be an object",
                }
            )
            continue

        context = _mint_context(mint, mint_index)
        agents = mint.get("agents")
        if not isinstance(agents, list):
            violations.append(
                {
                    **context,
                    "reason": (
                        f"trajectory_mints.json mints[{mint_index}].agents must be a list"
                    ),
                }
            )
            continue

        for agent_index, agent_id in enumerate(agents):
            agent_refs_checked += 1

            if not isinstance(agent_id, str):
                violations.append(
                    {
                        **context,
                        "agent_index": agent_index,
                        "agent": agent_id,
                        "reason": (
                            f"trajectory_mints.json mints[{mint_index}].agents[{agent_index}] "
                            "must be a string"
                        ),
                    }
                )
                continue

            if not agent_id.strip():
                violations.append(
                    {
                        **context,
                        "agent_index": agent_index,
                        "agent": agent_id,
                        "reason": (
                            f"trajectory_mints.json mints[{mint_index}].agents[{agent_index}] "
                            "must be a non-empty string"
                        ),
                    }
                )
                continue

            if not agent_id.strip():
                violations.append(
                    {
                        **context,
                        "agent_index": agent_index,
                        "agent": agent_id,
                        "reason": (
                            f"trajectory_mints.json mints[{mint_index}].agents[{agent_index}] "
                            "must be a non-empty string"
                        ),
                    }
                )
                continue

            if agent_id not in registered_agent_ids:
                violations.append(
                    {
                        **context,
                        "agent_index": agent_index,
                        "agent": agent_id,
                        "reason": "agent not found in balances.json",
                    }
                )

    return violations, agent_refs_checked


def build_report(
    *,
    registered_agents: int,
    mints_checked: int,
    agent_refs_checked: int,
    violations: list[dict[str, Any]],
    error: str | None = None,
) -> dict[str, Any]:
    """Build the JSON report emitted by the CLI."""
    output_violations = list(violations)
    if error is not None:
        output_violations.append({"reason": error})

    unregistered_agent_refs = sum(
        1 for violation in violations if violation.get("reason") == "agent not found in balances.json"
    )
    structural_violations = len(violations) - unregistered_agent_refs

    return {
        "status": "FAIL" if output_violations else "PASS",
        "summary": {
            "registered_agents": registered_agents,
            "mints_checked": mints_checked,
            "agent_refs_checked": agent_refs_checked,
            "unregistered_agent_refs": unregistered_agent_refs,
            "structural_violations": structural_violations,
            "input_errors": 1 if error is not None else 0,
            "violations": len(output_violations),
        },
        "violations": output_violations,
    }


def run_check(root: Path) -> tuple[dict[str, Any], int]:
    """Run the mint-agent registration check for a repository root."""
    balances_path = root / "ledger" / "balances.json"
    trajectory_mints_path = root / "ledger" / "trajectory_mints.json"

    try:
        balances_payload = load_json(balances_path)
        trajectory_payload = load_json(trajectory_mints_path)
        registered_agent_ids = get_registered_agent_ids(balances_payload)
        mints = get_mints(trajectory_payload)
    except ValueError as exc:
        report = build_report(
            registered_agents=0,
            mints_checked=0,
            agent_refs_checked=0,
            violations=[],
            error=str(exc),
        )
        return report, 1

    violations, agent_refs_checked = find_unregistered_mint_agents(
        mints,
        registered_agent_ids,
    )
    report = build_report(
        registered_agents=len(registered_agent_ids),
        mints_checked=len(mints),
        agent_refs_checked=agent_refs_checked,
        violations=violations,
    )
    return report, 1 if violations else 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Check that every mint agent is registered in balances.json."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Repository root directory (default: auto-detected from this script)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    args = parse_args(argv)
    root = args.root or Path(__file__).resolve().parent.parent
    report, exit_code = run_check(root)
    print(json.dumps(report, indent=2))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
