#!/usr/bin/env python3
"""Check that every balanced agent has a register idem key.

Reads:
  - ledger/balances.json
  - ledger/idem_keys.json

Rule:
  - Every agent listed in balances["agents"] must have a
    register|{agent_id} entry inside idem_keys["keys"].
  - agent0@system is exempt.

Outputs JSON to stdout.
Exits 0 on PASS, 1 on FAIL.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

EXEMPT_AGENT = "agent0@system"


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


def get_agent_ids(balances_payload: Any) -> list[str]:
    """Extract agent IDs from balances.json payload."""
    if not isinstance(balances_payload, dict):
        raise ValueError("balances.json must contain a top-level JSON object")

    agents = balances_payload.get("agents")
    if not isinstance(agents, dict):
        raise ValueError("balances.json must contain an object at key 'agents'")

    return sorted(str(agent_id) for agent_id in agents)


def get_nested_idem_keys(idem_payload: Any) -> dict[str, Any]:
    """Extract nested idem keys from idem_keys.json payload."""
    if not isinstance(idem_payload, dict):
        raise ValueError("idem_keys.json must contain a top-level JSON object")

    keys = idem_payload.get("keys")
    if not isinstance(keys, dict):
        raise ValueError("idem_keys.json must contain an object at key 'keys'")

    return keys


def find_missing_register_keys(
    agent_ids: list[str],
    idem_keys: dict[str, Any],
    *,
    exempt_agent: str = EXEMPT_AGENT,
) -> list[str]:
    """Return sorted agent IDs whose register idem key is missing."""
    missing = [
        agent_id
        for agent_id in agent_ids
        if agent_id != exempt_agent and f"register|{agent_id}" not in idem_keys
    ]
    return sorted(missing)


def build_report(
    *,
    agent_ids: list[str],
    missing_agents: list[str],
    error: str | None = None,
) -> dict[str, Any]:
    """Build the JSON report emitted by the CLI."""
    checked_agents = [agent_id for agent_id in agent_ids if agent_id != EXEMPT_AGENT]
    violations = [
        {"agent": agent_id, "missing_key": f"register|{agent_id}"}
        for agent_id in missing_agents
    ]

    if error is not None:
        violations.append({"reason": error})

    return {
        "status": "FAIL" if missing_agents or error else "PASS",
        "summary": {
            "agents_in_balances": len(agent_ids),
            "agents_checked": len(checked_agents),
            "missing_register_keys": len(missing_agents),
            "exempt_agents": [EXEMPT_AGENT],
        },
        "violations": violations,
    }


def run_check(root: Path) -> tuple[dict[str, Any], int]:
    """Run the registry completeness check for a repository root."""
    balances_path = root / "ledger" / "balances.json"
    idem_keys_path = root / "ledger" / "idem_keys.json"

    try:
        balances_payload = load_json(balances_path)
        idem_payload = load_json(idem_keys_path)
        agent_ids = get_agent_ids(balances_payload)
        idem_keys = get_nested_idem_keys(idem_payload)
    except ValueError as exc:
        report = build_report(agent_ids=[], missing_agents=[], error=str(exc))
        return report, 1

    missing_agents = find_missing_register_keys(agent_ids, idem_keys)
    report = build_report(agent_ids=agent_ids, missing_agents=missing_agents)
    return report, 1 if missing_agents else 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check that every agent in balances has a register idem key."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Repository root directory (default: auto-detected from this script)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.root or Path(__file__).resolve().parent.parent
    report, exit_code = run_check(root)
    print(json.dumps(report, indent=2))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
