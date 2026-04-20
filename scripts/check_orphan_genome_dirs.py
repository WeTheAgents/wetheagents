#!/usr/bin/env python3
"""Detect orphan genome directories and missing required genome directories.

Rules:
  - Any directory directly under genomes/ whose name is not present in
    ledger/balances.json is an orphan genome directory.
  - Any agent in ledger/balances.json with tasks_completed > 0 or
    total_earned > 0 must have a matching directory under genomes/.

Outputs JSON to stdout.
Exits 0 on PASS, 1 on FAIL.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SKIP_GENOME_DIRS = frozenset({"base"})
EXEMPT_AGENTS = frozenset({"agent0@system"})


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


def get_agents(balances_payload: Any) -> dict[str, Any]:
    """Extract balances.json agents mapping."""
    if not isinstance(balances_payload, dict):
        raise ValueError("balances.json must contain a top-level JSON object")

    agents = balances_payload.get("agents")
    if not isinstance(agents, dict):
        raise ValueError("balances.json must contain an object at key 'agents'")

    return {str(agent_id): agent_data for agent_id, agent_data in agents.items()}


def list_genome_dirs(genomes_dir: Path) -> list[str]:
    """Return sorted genome directory names, excluding known non-agent dirs."""
    if not genomes_dir.exists():
        return []
    if not genomes_dir.is_dir():
        raise ValueError("genomes path exists but is not a directory")

    try:
        entries = sorted(genomes_dir.iterdir(), key=lambda entry: entry.name)
    except OSError as exc:
        raise ValueError(f"Could not read genomes directory: {exc}") from exc

    return [
        entry.name
        for entry in entries
        if entry.is_dir() and entry.name not in SKIP_GENOME_DIRS
    ]


def _is_positive_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def requires_genome_dir(agent_payload: Any) -> bool:
    """Return True when an agent should have a genome directory."""
    if not isinstance(agent_payload, dict):
        return False
    return _is_positive_number(agent_payload.get("tasks_completed", 0)) or _is_positive_number(
        agent_payload.get("total_earned", 0)
    )


def find_orphan_genome_dirs(agent_ids: set[str], genome_dirs: list[str]) -> list[str]:
    """Return genome directories not present in balances.json."""
    return [genome_dir for genome_dir in genome_dirs if genome_dir not in agent_ids]


def find_missing_genome_dirs(
    agents: dict[str, Any], genome_dirs: set[str]
) -> list[dict[str, int | float | str]]:
    """Return agents that require a genome directory but do not have one."""
    missing: list[dict[str, int | float | str]] = []
    for agent_id in sorted(agents):
        agent_payload = agents[agent_id]
        if agent_id in EXEMPT_AGENTS:
            continue
        if not requires_genome_dir(agent_payload) or agent_id in genome_dirs:
            continue

        tasks_completed = (
            agent_payload.get("tasks_completed", 0) if isinstance(agent_payload, dict) else 0
        )
        total_earned = agent_payload.get("total_earned", 0) if isinstance(agent_payload, dict) else 0
        missing.append(
            {
                "agent": agent_id,
                "expected_path": f"genomes/{agent_id}",
                "tasks_completed": tasks_completed,
                "total_earned": total_earned,
            }
        )
    return missing


def build_report(
    *,
    agents: dict[str, Any],
    genome_dirs: list[str],
    orphan_genome_dirs: list[str],
    missing_genome_dirs: list[dict[str, int | float | str]],
    error: str | None = None,
) -> dict[str, Any]:
    """Build the JSON report emitted by the CLI."""
    required_agents = [
        agent_id
        for agent_id, payload in agents.items()
        if agent_id not in EXEMPT_AGENTS and requires_genome_dir(payload)
    ]

    report = {
        "status": "FAIL" if orphan_genome_dirs or missing_genome_dirs or error else "PASS",
        "summary": {
            "registered_agents": len(agents),
            "genome_dirs_scanned": len(genome_dirs),
            "agents_requiring_genomes": len(required_agents),
            "orphan_genome_dirs": len(orphan_genome_dirs),
            "missing_genome_dirs": len(missing_genome_dirs),
            "exempt_agents": sorted(EXEMPT_AGENTS),
            "skipped_genome_dirs": sorted(SKIP_GENOME_DIRS),
        },
        "orphan_genome_dirs": [
            {"agent_dir": genome_dir, "path": f"genomes/{genome_dir}"}
            for genome_dir in orphan_genome_dirs
        ],
        "missing_genome_dirs": missing_genome_dirs,
    }

    if error is not None:
        report["errors"] = [{"reason": error}]

    return report


def run_check(root: Path) -> tuple[dict[str, Any], int]:
    """Run the orphan genome directory checks for a repository root."""
    balances_path = root / "ledger" / "balances.json"
    genomes_dir = root / "genomes"

    try:
        balances_payload = load_json(balances_path)
        agents = get_agents(balances_payload)
        genome_dirs = list_genome_dirs(genomes_dir)
    except ValueError as exc:
        report = build_report(
            agents={},
            genome_dirs=[],
            orphan_genome_dirs=[],
            missing_genome_dirs=[],
            error=str(exc),
        )
        return report, 1

    orphan_genome_dirs = find_orphan_genome_dirs(set(agents), genome_dirs)
    missing_genome_dirs = find_missing_genome_dirs(agents, set(genome_dirs))
    report = build_report(
        agents=agents,
        genome_dirs=genome_dirs,
        orphan_genome_dirs=orphan_genome_dirs,
        missing_genome_dirs=missing_genome_dirs,
    )
    return report, 1 if orphan_genome_dirs or missing_genome_dirs else 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect orphan genome directories and missing required genomes."
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
