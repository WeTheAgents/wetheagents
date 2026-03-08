"""Display mutation timeline for agent genomes.

Usage:
    # One agent
    python scripts/genome_log.py --agent Claude-1@claude

    # All agents
    python scripts/genome_log.py --all
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent

_HEADER = f"{'Date':<20} {'Trigger':<8} {'Summary':<36} {'Tasks':<8} {'Earned'}"
_SEP = "-" * 90


def find_agents(repo_root: Path) -> list[str]:
    genomes_dir = repo_root / "genomes"
    if not genomes_dir.exists():
        return []
    return sorted(
        p.parent.name
        for p in genomes_dir.glob("*/genome_meta.json")
    )


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def format_delta(before: int | None, after: int | None) -> str:
    b = before if before is not None else 0
    a = after if after is not None else 0
    return f"{b}→{a}"


def render_agent(agent: str, repo_root: Path) -> None:
    meta_path = repo_root / "genomes" / agent / "genome_meta.json"
    if not meta_path.exists():
        print(f"{agent} — genome_meta.json not found", file=sys.stderr)
        return

    meta = load_json(meta_path)
    mutations: list[dict[str, Any]] = meta.get("mutations", [])
    count = len(mutations)
    print(f"\n{agent} — {count} mutation(s)")

    if not mutations:
        return

    print(_HEADER)
    print(_SEP)
    for m in mutations:
        date_raw = m.get("date", "")
        # Trim to 'YYYY-MM-DD HH:MM' (16 chars)
        date_display = date_raw.replace("T", " ").replace("Z", "")[:16]

        trigger = f"#{m.get('trigger_issue', '?')}"
        summary = str(m.get("summary", ""))[:35]

        fb = m.get("fitness_before", {})
        fa = m.get("fitness_after", {})
        tasks_delta = format_delta(fb.get("tasks_completed"), fa.get("tasks_completed"))
        earned_delta = format_delta(fb.get("total_earned"), fa.get("total_earned"))

        print(f"{date_display:<20} {trigger:<8} {summary:<36} {tasks_delta:<8} {earned_delta}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Display genome mutation timeline.")
    parser.add_argument("--agent", help="Agent ID, e.g. Claude-1@claude")
    parser.add_argument("--all", action="store_true", help="Show all agents.")
    parser.add_argument("--repo-root", help="Override repo root path (for testing).")
    args = parser.parse_args()

    repo_root = Path(args.repo_root) if args.repo_root else REPO_ROOT

    if args.all:
        agents = find_agents(repo_root)
        if not agents:
            print("No agents found.", file=sys.stderr)
            return 1
        for agent in agents:
            render_agent(agent, repo_root)
    elif args.agent:
        render_agent(args.agent, repo_root)
    else:
        print("ERROR: specify --agent <id> or --all", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
