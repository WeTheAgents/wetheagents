#!/usr/bin/env python3
"""Detect zombie genome directories.

A zombie genome is a directory directly under genomes/ whose directory name does
not match any registered agent in ledger/balances.json.

This checker is intentionally narrow:
  - It validates directory names against the registration ledger
  - It skips known non-agent directories like genomes/base/
  - It ignores plain files under genomes/

Output: JSON to stdout with fields: status, zombies, summary.

Exit codes:
    0 — no zombie genome directories found
    1 — one or more zombie genome directories found, or ledger is unreadable
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    from genome_registry import registered_agent_ids
except ModuleNotFoundError:  # Imported as scripts.check_zombie_genomes.
    from scripts.genome_registry import registered_agent_ids

SKIP_GENOME_DIRS: set[str] = {"base"}


def _repo_root(override: str | None = None) -> Path:
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parent.parent


def _load_balances(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not path.exists():
        return None, f"balances.json not found at {path}"
    try:
        with path.open(encoding="utf-8") as fh:
            payload = json.load(fh)
    except OSError as exc:
        return None, f"balances.json is unreadable: {exc}"
    except json.JSONDecodeError:
        return None, "balances.json is not valid JSON"
    if not isinstance(payload, dict):
        return None, "balances.json top-level value is not an object"
    return payload, None


def run(root: Path) -> tuple[dict[str, Any], bool]:
    balances_path = root / "ledger" / "balances.json"
    genomes_dir = root / "genomes"

    balances, load_error = _load_balances(balances_path)
    if balances is None:
        return {
            "status": "FAIL",
            "zombies": [],
            "summary": load_error,
        }, False

    agents = balances.get("agents", {})
    if not isinstance(agents, dict):
        return {
            "status": "FAIL",
            "zombies": [],
            "summary": "balances.json 'agents' is not a dictionary",
        }, False

    if not genomes_dir.is_dir():
        return {
            "status": "PASS",
            "zombies": [],
            "summary": "genomes/ directory not found",
        }, True

    registered_agents = registered_agent_ids(root, balances)
    zombies: list[dict[str, str]] = []

    try:
        entries = sorted(genomes_dir.iterdir(), key=lambda item: item.name)
    except OSError as exc:
        return {
            "status": "FAIL",
            "zombies": [],
            "summary": f"genomes/ directory is unreadable: {exc}",
        }, False

    for entry in entries:
        if not entry.is_dir() or entry.name in SKIP_GENOME_DIRS:
            continue
        if entry.name in registered_agents:
            continue
        zombies.append({
            "agent_dir": entry.name,
            "path": str(entry.relative_to(root)).replace("\\", "/"),
            "detail": (
                f"genomes/{entry.name}/ exists but '{entry.name}' "
                "is not registered in ledger/balances.json"
            ),
        })

    if zombies:
        names = ", ".join(zombie["agent_dir"] for zombie in zombies)
        count = len(zombies)
        return {
            "status": "FAIL",
            "zombies": zombies,
            "summary": (
                f"{count} zombie genome dir{'s' if count != 1 else ''} "
                f"found: {names}"
            ),
        }, False

    checked = sum(
        1
        for entry in entries
        if entry.is_dir() and entry.name not in SKIP_GENOME_DIRS
    )
    return {
        "status": "PASS",
        "zombies": [],
        "summary": (
            f"{checked} genome dir{'s' if checked != 1 else ''} checked, "
            "no zombies found"
        ),
    }, True


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Detect genomes/ directories that do not belong to registered agents."
        )
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root (default: auto-detected from script location)",
    )
    args = parser.parse_args()

    result, passed = run(_repo_root(args.root))
    print(json.dumps(result, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
