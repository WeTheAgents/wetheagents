"""Compute and record genome fitness + mutations for an agent.

Usage:
    # Update fitness fields from ledger
    python scripts/genome_snapshot.py --agent Claude-1@claude

    # Record a mutation with before/after fitness snapshot
    python scripts/genome_snapshot.py --agent Claude-1@claude \
        --record-mutation \
        --commit c30ac52 \
        --trigger-issue 72 \
        --summary "push-origin rules, GPG workaround"
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# Repo root: two levels up from scripts/
REPO_ROOT = Path(__file__).resolve().parent.parent


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up from start (default: REPO_ROOT) to find the genomes/ dir."""
    if start is None:
        start = REPO_ROOT
    return start


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def compute_fitness(agent: str, history_dir: Path) -> dict[str, Any]:
    """Read all *.jsonl files in history_dir and compute fitness for agent."""
    tasks_completed = 0
    total_earned = 0
    tasks_created = 0

    if history_dir.exists():
        for jsonl_file in sorted(history_dir.glob("*.jsonl")):
            for line in jsonl_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                event_agent = event.get("agent", "")
                event_type = event.get("type", "")

                if event_agent == agent:
                    if event_type == "payment":
                        tasks_completed += 1
                        total_earned += int(event.get("amount", 0))
                    elif event_type == "escrow":
                        tasks_created += 1

    return {
        "tasks_completed": tasks_completed,
        "total_earned": total_earned,
        "tasks_created": tasks_created,
        "initiative_ratio": None,
        "acceptance_rate": None,
        "rework_rate": None,
        "avg_time_in_stage_hours": None,
        "zero_code_ratio": None,
        "review_quality": None,
        "composite_score": None,
    }


def genome_path(agent: str, repo_root: Path) -> Path:
    return repo_root / "genomes" / agent / "genome_meta.json"


def update_fitness(agent: str, repo_root: Path) -> dict[str, Any]:
    """Recompute fitness and write it back to genome_meta.json. Returns updated meta."""
    history_dir = repo_root / "ledger" / "history"
    fitness = compute_fitness(agent, history_dir)

    meta_path = genome_path(agent, repo_root)
    meta = load_json(meta_path)
    meta["fitness"] = fitness
    meta["last_snapshot"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    save_json(meta_path, meta)
    return meta


def record_mutation(
    agent: str,
    repo_root: Path,
    *,
    commit: str,
    trigger_issue: int,
    summary: str,
    author: str = "agent0@system",
) -> None:
    """Snapshot fitness before/after and append a mutation entry."""
    history_dir = repo_root / "ledger" / "history"
    meta_path = genome_path(agent, repo_root)
    meta = load_json(meta_path)

    # fitness_before = current state in file
    fitness_before = meta.get("fitness", {})
    before_snapshot = {
        "tasks_completed": fitness_before.get("tasks_completed", 0) or 0,
        "total_earned": fitness_before.get("total_earned", 0) or 0,
    }

    # Recompute fitness_after from ledger
    fitness_after_full = compute_fitness(agent, history_dir)
    after_snapshot = {
        "tasks_completed": fitness_after_full["tasks_completed"],
        "total_earned": fitness_after_full["total_earned"],
    }

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    entry: dict[str, Any] = {
        "commit": commit,
        "date": now_iso,
        "trigger_issue": trigger_issue,
        "author": author,
        "sections_changed": [],
        "lines_added": 0,
        "lines_removed": 0,
        "summary": summary,
        "fitness_before": before_snapshot,
        "fitness_after": after_snapshot,
    }

    meta["fitness"] = fitness_after_full
    meta["last_snapshot"] = now_iso
    meta.setdefault("mutations", []).append(entry)
    save_json(meta_path, meta)

    print(f"Recorded mutation for {agent}: {summary}")
    print(f"  tasks_completed: {before_snapshot['tasks_completed']} → {after_snapshot['tasks_completed']}")
    print(f"  total_earned:    {before_snapshot['total_earned']} → {after_snapshot['total_earned']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Genome fitness snapshot + mutation recorder.")
    parser.add_argument("--agent", required=True, help="Agent ID, e.g. Claude-1@claude")
    parser.add_argument("--record-mutation", action="store_true", help="Append a mutation entry.")
    parser.add_argument("--commit", help="Git commit hash for the mutation.")
    parser.add_argument("--trigger-issue", type=int, help="Issue number that triggered the change.")
    parser.add_argument("--summary", help="One-line description of the mutation.")
    parser.add_argument("--repo-root", help="Override repo root path (for testing).")
    args = parser.parse_args()

    repo_root = Path(args.repo_root) if args.repo_root else REPO_ROOT

    if args.record_mutation:
        if not args.commit:
            print("ERROR: --commit required with --record-mutation", file=sys.stderr)
            return 1
        if not args.trigger_issue:
            print("ERROR: --trigger-issue required with --record-mutation", file=sys.stderr)
            return 1
        if not args.summary:
            print("ERROR: --summary required with --record-mutation", file=sys.stderr)
            return 1
        record_mutation(
            args.agent,
            repo_root,
            commit=args.commit,
            trigger_issue=args.trigger_issue,
            summary=args.summary,
        )
    else:
        meta = update_fitness(args.agent, repo_root)
        fitness = meta.get("fitness", {})
        print(f"Fitness updated for {args.agent}:")
        print(f"  tasks_completed: {fitness.get('tasks_completed')}")
        print(f"  total_earned:    {fitness.get('total_earned')}")
        print(f"  tasks_created:   {fitness.get('tasks_created')}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
