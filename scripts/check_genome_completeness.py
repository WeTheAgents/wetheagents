#!/usr/bin/env python3
"""Agent genome completeness checker.

For each agent registered in ledger/balances.json (except agent0@system):
  - Verifies genomes/{agent_id}/ directory exists
  - Verifies genomes/{agent_id}/genome_meta.json is present, valid JSON,
    top-level dict, and contains all required fields
  - Verifies genomes/{agent_id}/AGENTS.local.md is present and non-empty

Also reports orphan genomes: directories in genomes/ that have no matching
entry in balances.json (reported as WARN, not FAIL).

Closes the gap found in T6S10: genome_meta.json corruption (non-dict structure,
mangled JSON) was not caught by the pre-commit hook.

Exit codes:
    0  — all agent checks PASS (WARN entries do not count as failures)
    1  — one or more agents FAIL

Output: JSON to stdout with fields: status, checks, summary.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# agent0@system is the system operator — exempt from genome tracking.
# It has no genomes/ directory and that is expected behaviour.
_SKIP_AGENTS: set[str] = {"agent0@system"}

# Fields that every genome_meta.json must contain at the top level.
REQUIRED_META_FIELDS: tuple[str, ...] = ("agent_id", "fitness", "mutations")


def _repo_root(override: str | None = None) -> Path:
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parent.parent


def _load_balances(balances_path: Path) -> dict[str, Any] | None:
    if not balances_path.exists():
        return None
    try:
        with balances_path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError:
        return None


def _check_agent(agent_id: str, genomes_dir: Path) -> list[dict[str, Any]]:
    """Return a list of check result dicts for a single agent."""
    results: list[dict[str, Any]] = []
    agent_dir = genomes_dir / agent_id

    # 1. genome directory must exist
    if not agent_dir.is_dir():
        results.append({
            "agent": agent_id,
            "check": "genome_dir",
            "status": "FAIL",
            "detail": f"genomes/{agent_id}/ directory not found",
        })
        # Without the directory, remaining checks are meaningless
        return results
    else:
        results.append({
            "agent": agent_id,
            "check": "genome_dir",
            "status": "PASS",
            "detail": f"genomes/{agent_id}/ exists",
        })

    # 2. genome_meta.json must exist
    meta_path = agent_dir / "genome_meta.json"
    if not meta_path.exists():
        results.append({
            "agent": agent_id,
            "check": "genome_meta_present",
            "status": "FAIL",
            "detail": f"genomes/{agent_id}/genome_meta.json not found",
        })
    else:
        results.append({
            "agent": agent_id,
            "check": "genome_meta_present",
            "status": "PASS",
            "detail": "genome_meta.json exists",
        })

        # 3. genome_meta.json must be valid JSON
        try:
            raw = meta_path.read_text(encoding="utf-8")
            meta = json.loads(raw)
        except json.JSONDecodeError as exc:
            results.append({
                "agent": agent_id,
                "check": "genome_meta_valid_json",
                "status": "FAIL",
                "detail": f"genome_meta.json is not valid JSON: {exc}",
            })
            meta = None
        else:
            results.append({
                "agent": agent_id,
                "check": "genome_meta_valid_json",
                "status": "PASS",
                "detail": "genome_meta.json is valid JSON",
            })

            # 4. top-level value must be a dict (not list, string, etc.)
            if not isinstance(meta, dict):
                results.append({
                    "agent": agent_id,
                    "check": "genome_meta_is_dict",
                    "status": "FAIL",
                    "detail": (
                        f"genome_meta.json top-level value is {type(meta).__name__}, "
                        "expected object/dict"
                    ),
                })
                meta = None
            else:
                results.append({
                    "agent": agent_id,
                    "check": "genome_meta_is_dict",
                    "status": "PASS",
                    "detail": "genome_meta.json top-level is a dict",
                })

        # 5. required fields must all be present
        if isinstance(meta, dict):
            missing = [f for f in REQUIRED_META_FIELDS if f not in meta]
            if missing:
                results.append({
                    "agent": agent_id,
                    "check": "genome_meta_required_fields",
                    "status": "FAIL",
                    "detail": f"genome_meta.json missing required fields: {missing}",
                })
            else:
                results.append({
                    "agent": agent_id,
                    "check": "genome_meta_required_fields",
                    "status": "PASS",
                    "detail": f"all required fields present: {list(REQUIRED_META_FIELDS)}",
                })

    # 6. AGENTS.local.md must exist and be non-empty
    local_md = agent_dir / "AGENTS.local.md"
    if not local_md.exists():
        results.append({
            "agent": agent_id,
            "check": "agents_local_md",
            "status": "FAIL",
            "detail": f"genomes/{agent_id}/AGENTS.local.md not found",
        })
    elif local_md.stat().st_size == 0:
        results.append({
            "agent": agent_id,
            "check": "agents_local_md",
            "status": "FAIL",
            "detail": f"genomes/{agent_id}/AGENTS.local.md is empty",
        })
    else:
        results.append({
            "agent": agent_id,
            "check": "agents_local_md",
            "status": "PASS",
            "detail": "AGENTS.local.md present and non-empty",
        })

    return results


def _find_orphans(
    agent_ids: set[str],
    genomes_dir: Path,
) -> list[dict[str, Any]]:
    """Return WARN entries for genome directories with no balances.json entry."""
    orphans: list[dict[str, Any]] = []
    if not genomes_dir.is_dir():
        return orphans
    for entry in sorted(genomes_dir.iterdir()):
        if not entry.is_dir():
            continue
        name = entry.name
        if name not in agent_ids and name not in _SKIP_AGENTS:
            orphans.append({
                "agent": name,
                "check": "orphan_genome",
                "status": "WARN",
                "detail": (
                    f"genomes/{name}/ exists but '{name}' "
                    "has no entry in balances.json"
                ),
            })
    return orphans


def run(root: Path) -> tuple[dict[str, Any], bool]:
    balances_path = root / "ledger" / "balances.json"
    genomes_dir = root / "genomes"

    if not balances_path.exists():
        return {
            "status": "FAIL",
            "checks": [],
            "summary": f"balances.json not found at {balances_path}",
        }, False

    balances = _load_balances(balances_path)
    if balances is None:
        return {
            "status": "FAIL",
            "checks": [],
            "summary": "balances.json is not valid JSON",
        }, False

    agents_data: dict[str, Any] = balances.get("agents", {})
    agent_ids = {aid for aid in agents_data if aid not in _SKIP_AGENTS}

    all_checks: list[dict[str, Any]] = []

    for agent_id in sorted(agent_ids):
        all_checks.extend(_check_agent(agent_id, genomes_dir))

    all_checks.extend(_find_orphans(agent_ids | _SKIP_AGENTS, genomes_dir))

    n_pass = sum(1 for c in all_checks if c["status"] == "PASS")
    n_fail = sum(1 for c in all_checks if c["status"] == "FAIL")
    n_warn = sum(1 for c in all_checks if c["status"] == "WARN")

    passed = n_fail == 0
    overall = "PASS" if passed else "FAIL"

    parts: list[str] = []
    if n_pass:
        parts.append(f"{n_pass} PASS")
    if n_fail:
        parts.append(f"{n_fail} FAIL")
    if n_warn:
        parts.append(f"{n_warn} WARN")

    summary = ", ".join(parts) if parts else "no agents found"

    return {
        "status": overall,
        "checks": all_checks,
        "summary": summary,
    }, passed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify each agent has a complete genome directory."
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root (default: auto-detected from script location)",
    )
    args = parser.parse_args()

    root = _repo_root(args.root)
    result, passed = run(root)

    print(json.dumps(result, indent=2))

    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
