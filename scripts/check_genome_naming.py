#!/usr/bin/env python3
"""
Genome Naming Guard — validates directory-to-metadata consistency across all agent genomes.

Checks:
1. Each genome directory name matches its genome_meta.json agent_id field.
2. Each genome_meta.json agent_id exists in ledger/balances.json.
3. parent, donor_lineage, and lineage references use agent_ids that exist in balances.json.

Usage:
    python scripts/check_genome_naming.py
    python scripts/check_genome_naming.py --root /path/to/repo
    python scripts/check_genome_naming.py --strict   # also fail on missing genome_meta.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    from genome_registry import registered_agent_ids
except ModuleNotFoundError:  # Imported as scripts.check_genome_naming.
    from scripts.genome_registry import registered_agent_ids


_SKIP_DIRS = {"base", "code-stylist"}
_REF_FIELDS = ("parent", "donor_lineage", "lineage")


def _repo_root(override: str | None = None) -> Path:
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _collect_refs(meta: dict[str, Any]) -> list[str]:
    """Extract all agent ID references from parent, donor_lineage, lineage."""
    refs: list[str] = []
    parent = meta.get("parent")
    if parent:
        refs.append(parent)
    for field in ("donor_lineage", "lineage"):
        val = meta.get(field)
        if isinstance(val, list):
            refs.extend(v for v in val if isinstance(v, str))
    return refs


def run(root: Path, strict: bool = False) -> int:
    """Run all naming checks. Returns number of errors found."""
    genomes_dir = root / "genomes"
    if not genomes_dir.is_dir():
        print(f"ERROR: genomes/ directory not found at {genomes_dir}", file=sys.stderr)
        return 1

    balances_path = root / "ledger" / "balances.json"
    balances = _load_json(balances_path)
    if balances is None:
        print(f"ERROR: cannot load {balances_path}", file=sys.stderr)
        return 1
    known_agents = registered_agent_ids(root, balances)

    errors: list[str] = []
    warnings: list[str] = []

    for genome_dir in sorted(genomes_dir.iterdir()):
        if not genome_dir.is_dir():
            continue
        dir_name = genome_dir.name
        if dir_name in _SKIP_DIRS:
            continue

        meta_path = genome_dir / "genome_meta.json"
        if not meta_path.exists():
            msg = f"[WARN] {dir_name}: no genome_meta.json"
            if strict:
                errors.append(msg.replace("[WARN]", "[ERROR]"))
            else:
                warnings.append(msg)
            continue

        meta = _load_json(meta_path)
        if meta is None:
            errors.append(f"[ERROR] {dir_name}: genome_meta.json is not valid JSON")
            continue

        meta_agent_id = meta.get("agent_id", "")

        # Check 1: directory name == agent_id
        if dir_name != meta_agent_id:
            errors.append(
                f"[ERROR] {dir_name}: directory name != genome_meta.json agent_id "
                f"(got '{meta_agent_id}')"
            )

        # Check 2: agent_id exists in balances.json
        if meta_agent_id and meta_agent_id not in known_agents:
            errors.append(
                f"[ERROR] {dir_name}: agent_id '{meta_agent_id}' not found in balances.json"
            )

        # Check 3: parent/donor_lineage/lineage refs exist in balances.json
        for ref in _collect_refs(meta):
            if ref not in known_agents:
                errors.append(
                    f"[ERROR] {dir_name}: references unknown agent '{ref}' "
                    f"(not in balances.json)"
                )

    for w in warnings:
        print(w)
    for e in errors:
        print(e)

    if errors:
        print(f"\n{len(errors)} error(s) found.")
    else:
        checked = sum(
            1
            for d in genomes_dir.iterdir()
            if d.is_dir() and d.name not in _SKIP_DIRS and (d / "genome_meta.json").exists()
        )
        print(f"OK — {checked} genome(s) checked, all naming consistent.")

    return len(errors)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate genome directory naming consistency.")
    parser.add_argument("--root", default=None, help="Repository root (default: auto-detect)")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat missing genome_meta.json as an error",
    )
    args = parser.parse_args()

    root = _repo_root(args.root)
    error_count = run(root, strict=args.strict)
    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
