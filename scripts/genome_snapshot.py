#!/usr/bin/env python3
"""Compute and record genome fitness snapshots from ledger data.

Usage:
    # Update fitness fields from ledger data
    python scripts/genome_snapshot.py --agent Claude-1@claude

    # Record a mutation: snapshot before/after fitness, append to mutations[]
    python scripts/genome_snapshot.py --agent Claude-1@claude \\
        --record-mutation \\
        --commit c30ac52 \\
        --trigger-issue 72 \\
        --summary "push-origin rules, GPG workaround"
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from io_helpers import load_json  # noqa: E402


def _repo_root(override: str | None = None) -> Path:
    """Resolve the wetheagents repo root."""
    if override:
        return Path(override)
    # scripts/ lives one level below repo root
    return Path(__file__).resolve().parent.parent


def _save_json(path: Path, data: Any) -> None:
    """Atomic write: write to tmp then rename."""
    content = json.dumps(data, indent=2) + "\n"
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _compute_mint_earnings(agent_id: str, ledger_dir: Path) -> tuple[int, int]:
    """Sum gauntlet mint earnings for an agent from trajectory_mints.json.

    Returns (total_minted, gauntlet_slots) — total WEA minted and number of
    gauntlet slots the agent participated in.
    """
    mints_path = ledger_dir / "trajectory_mints.json"
    if not mints_path.exists():
        return 0, 0

    try:
        data = json.loads(mints_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return 0, 0

    total_minted = 0
    gauntlet_slots = 0
    for mint in data.get("mints", []):
        agents = mint.get("agents", [])
        per_agent = mint.get("per_agent", [])
        for i, aid in enumerate(agents):
            if aid == agent_id and i < len(per_agent):
                total_minted += int(per_agent[i])
                gauntlet_slots += 1

    return total_minted, gauntlet_slots


def compute_fitness(agent_id: str, history_dir: Path, ledger_dir: Path | None = None) -> dict[str, Any]:
    """Read all JSONL history files and trajectory_mints.json to compute fitness.

    Returns dict with: tasks_completed, total_earned, tasks_created,
    total_minted, gauntlet_slots, total_income.
    All values are int (0 if no events found).
    """
    tasks_completed = 0
    total_earned = 0
    tasks_created = 0

    if history_dir.is_dir():
        for jsonl_file in sorted(history_dir.glob("*.jsonl")):
            try:
                text = jsonl_file.read_text(encoding="utf-8")
            except OSError:
                continue
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                etype = event.get("type")
                if etype == "payment" and event.get("agent") == agent_id:
                    tasks_completed += 1
                    total_earned += int(event.get("amount", 0))
                elif etype == "escrow" and event.get("author") == agent_id:
                    tasks_created += 1

    # Gauntlet mints (trajectory_mints.json lives in ledger/)
    mint_dir = ledger_dir if ledger_dir is not None else history_dir.parent
    total_minted, gauntlet_slots = _compute_mint_earnings(agent_id, mint_dir)

    return {
        "tasks_completed": tasks_completed,
        "total_earned": total_earned,
        "tasks_created": tasks_created,
        "total_minted": total_minted,
        "gauntlet_slots": gauntlet_slots,
        "total_income": total_earned + total_minted,
    }


def _extract_fitness_snapshot(meta: dict[str, Any]) -> dict[str, Any]:
    """Pull the computable fitness fields out of genome_meta fitness block."""
    fitness = meta.get("fitness", {})
    return {
        "tasks_completed": fitness.get("tasks_completed", 0),
        "total_earned": fitness.get("total_earned", 0),
        "total_minted": fitness.get("total_minted", 0),
        "total_income": fitness.get("total_income", 0),
    }


def _git_diff_stats(commit: str, repo_root: Path) -> tuple[int, int, list[str]]:
    """Return (lines_added, lines_removed, sections_changed) for a commit.

    Parses `git show --stat` output. Returns (0, 0, []) on any error.
    """
    try:
        result = subprocess.run(
            ["git", "show", "--stat", "--format=", commit],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
            timeout=15,
        )
        if result.returncode != 0:
            return 0, 0, []

        lines_added = 0
        lines_removed = 0
        sections_changed: list[str] = []

        for line in result.stdout.splitlines():
            # Summary line: "3 files changed, 27 insertions(+), 3 deletions(-)"
            if "insertion" in line or "deletion" in line:
                parts = line.split(",")
                for part in parts:
                    part = part.strip()
                    if "insertion" in part:
                        lines_added = int(part.split()[0])
                    elif "deletion" in part:
                        lines_removed = int(part.split()[0])
            # File line: " genomes/Claude-1@claude/AGENTS.local.md | 30 +++..."
            elif "|" in line:
                fname = line.split("|")[0].strip()
                path = Path(fname)
                # Detect section from file name or path
                if "Memory" in fname:
                    sections_changed.append("Memory")
                elif "Examples" in fname:
                    sections_changed.append("Examples")
                elif "Instructions" in fname or "AGENTS.local" in fname:
                    sections_changed.append("Instructions")
                else:
                    sections_changed.append(path.name)

        # Deduplicate preserving order
        seen: set[str] = set()
        unique_sections: list[str] = []
        for s in sections_changed:
            if s not in seen:
                seen.add(s)
                unique_sections.append(s)

        return lines_added, lines_removed, unique_sections

    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        return 0, 0, []


def update_genome_fitness(
    agent_id: str,
    root: Path,
    *,
    record_mutation: bool = False,
    commit: str | None = None,
    trigger_issue: int | None = None,
    summary: str | None = None,
    author: str = "agent0@system",
    now: str | None = None,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Core logic: compute fitness, update genome_meta.json, optionally record mutation.

    Returns the updated genome_meta dict.
    Raises FileNotFoundError if genome_meta.json doesn't exist.
    Raises ValueError on bad argument combinations.
    """
    if record_mutation:
        if not commit:
            raise ValueError("--commit is required with --record-mutation")
        if trigger_issue is None:
            raise ValueError("--trigger-issue is required with --record-mutation")
        if not summary:
            raise ValueError("--summary is required with --record-mutation")

    genome_path = root / "genomes" / agent_id / "genome_meta.json"
    if not genome_path.exists():
        raise FileNotFoundError(f"genome_meta.json not found for agent: {agent_id}")

    meta = load_json(genome_path)

    # Use canonical agent_id from genome_meta.json for ledger lookups
    # (handles case mismatches between directory name and ledger records)
    canonical_id = meta.get("agent_id", agent_id)

    ledger_dir = root / "ledger"
    history_dir = ledger_dir / "history"
    new_fitness = compute_fitness(canonical_id, history_dir, ledger_dir)

    # Snapshot fitness BEFORE update (for mutation record)
    fitness_before = _extract_fitness_snapshot(meta)

    # Update fitness fields in meta (only the computable ones)
    if "fitness" not in meta or not isinstance(meta["fitness"], dict):
        meta["fitness"] = {}

    meta["fitness"]["tasks_completed"] = new_fitness["tasks_completed"]
    meta["fitness"]["tasks_created"] = new_fitness["tasks_created"]
    meta["fitness"]["total_earned"] = new_fitness["total_earned"]
    meta["fitness"]["total_minted"] = new_fitness["total_minted"]
    meta["fitness"]["gauntlet_slots"] = new_fitness["gauntlet_slots"]
    meta["fitness"]["total_income"] = new_fitness["total_income"]

    ts = now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta["last_snapshot"] = ts

    fitness_after = _extract_fitness_snapshot(meta)

    if record_mutation:
        lines_added, lines_removed, sections_changed = _git_diff_stats(commit, root)

        mutation_entry: dict[str, Any] = {
            "commit": commit,
            "date": ts,
            "trigger_issue": trigger_issue,
            "author": author,
            "sections_changed": sections_changed,
            "lines_added": lines_added,
            "lines_removed": lines_removed,
            "summary": summary,
            "fitness_before": fitness_before,
            "fitness_after": fitness_after,
        }

        if provenance is not None:
            mutation_entry["provenance"] = provenance

        if "mutations" not in meta or not isinstance(meta["mutations"], list):
            meta["mutations"] = []
        meta["mutations"].append(mutation_entry)

    _save_json(genome_path, meta)
    return meta


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compute and record genome fitness snapshots."
    )
    parser.add_argument("--agent", required=True, help="Agent ID, e.g. Claude-1@claude")
    parser.add_argument(
        "--record-mutation",
        action="store_true",
        help="Record a mutation entry in mutations[]",
    )
    parser.add_argument("--commit", help="Git commit hash of the genome change")
    parser.add_argument("--trigger-issue", type=int, help="Issue number that triggered the mutation")
    parser.add_argument("--summary", help="Short summary of the mutation")
    parser.add_argument("--author", default="agent0@system", help="Author of the mutation")
    parser.add_argument(
        "--provenance-json",
        default=None,
        dest="provenance_json",
        help="Path to a JSON file with SGR provenance data to attach to the mutation",
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root (default: auto-detect from script location)",
    )
    args = parser.parse_args()

    root = _repo_root(args.root)

    # Load provenance from JSON file if provided
    provenance_data = None
    if args.provenance_json:
        prov_path = Path(args.provenance_json)
        if not prov_path.exists():
            print(f"ERROR: provenance file not found: {prov_path}", file=sys.stderr)
            sys.exit(1)
        provenance_data = json.loads(prov_path.read_text(encoding="utf-8"))

    try:
        meta = update_genome_fitness(
            args.agent,
            root,
            record_mutation=args.record_mutation,
            commit=args.commit,
            trigger_issue=args.trigger_issue,
            summary=args.summary,
            author=args.author,
            provenance=provenance_data,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    fitness = meta.get("fitness", {})
    print(
        f"Snapshot updated for {args.agent}: "
        f"tasks={fitness.get('tasks_completed')}, "
        f"earned={fitness.get('total_earned')}, "
        f"minted={fitness.get('total_minted')}, "
        f"income={fitness.get('total_income')}"
    )
    if args.record_mutation:
        mutations = meta.get("mutations", [])
        print(f"Mutation recorded (total mutations: {len(mutations)})")


if __name__ == "__main__":
    main()
