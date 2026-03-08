#!/usr/bin/env python3
"""Display genome mutation timeline for one or all agents.

Usage:
    python scripts/genome_log.py --agent Claude-1@claude
    python scripts/genome_log.py --all
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _repo_root(override: str | None = None) -> Path:
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent


def _load_genome_meta(genome_dir: Path) -> dict[str, Any] | None:
    meta_path = genome_dir / "genome_meta.json"
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _render_delta(before: int | None, after: int | None) -> str:
    b = before if before is not None else 0
    a = after if after is not None else 0
    return f"{b}\u2192{a}"


def _format_date(iso: str) -> str:
    """Trim ISO timestamp to 'YYYY-MM-DD HH:MM' for compact display."""
    # e.g. "2026-03-08T10:59:11Z" -> "2026-03-08 10:59"
    return iso.replace("T", " ")[:16]


def render_agent_log(agent_id: str, meta: dict[str, Any]) -> str:
    """Return a human-readable mutation timeline string for one agent."""
    mutations: list[dict[str, Any]] = meta.get("mutations", [])
    lines: list[str] = []
    lines.append(f"{agent_id} \u2014 {len(mutations)} mutation(s)")

    if not mutations:
        return "\n".join(lines)

    # Header
    header = f"{'Date':<20} {'Trigger':<8} {'Summary':<36} {'Tasks':<8} {'Earned'}"
    lines.append(header)
    lines.append("-" * len(header))

    for m in mutations:
        date_str = _format_date(str(m.get("date", "")))
        trigger = f"#{m.get('trigger_issue', '?')}"
        summary = str(m.get("summary", ""))
        # Truncate summary if too long
        if len(summary) > 35:
            summary = summary[:32] + "..."

        fb = m.get("fitness_before", {}) or {}
        fa = m.get("fitness_after", {}) or {}
        tasks_delta = _render_delta(
            fb.get("tasks_completed"), fa.get("tasks_completed")
        )
        earned_delta = _render_delta(
            fb.get("total_earned"), fa.get("total_earned")
        )

        lines.append(
            f"{date_str:<20} {trigger:<8} {summary:<36} {tasks_delta:<8} {earned_delta}"
        )

    return "\n".join(lines)


def log_agent(agent_id: str, root: Path) -> int:
    """Print mutation log for a single agent. Returns exit code."""
    genome_dir = root / "genomes" / agent_id
    if not genome_dir.is_dir():
        print(f"ERROR: genome directory not found for agent: {agent_id}", file=sys.stderr)
        return 1

    meta = _load_genome_meta(genome_dir)
    if meta is None:
        print(f"ERROR: genome_meta.json missing or invalid for agent: {agent_id}", file=sys.stderr)
        return 1

    print(render_agent_log(agent_id, meta))
    return 0


def log_all(root: Path) -> int:
    """Print mutation logs for all agents. Returns exit code."""
    genomes_dir = root / "genomes"
    if not genomes_dir.is_dir():
        print(f"ERROR: genomes directory not found at {genomes_dir}", file=sys.stderr)
        return 1

    agents = sorted(
        d.name
        for d in genomes_dir.iterdir()
        if d.is_dir() and (d / "genome_meta.json").exists()
    )

    if not agents:
        print("No agent genomes found.")
        return 0

    for i, agent_id in enumerate(agents):
        if i > 0:
            print()
        meta = _load_genome_meta(genomes_dir / agent_id)
        if meta is None:
            print(f"{agent_id} — genome_meta.json unreadable, skipping")
            continue
        print(render_agent_log(agent_id, meta))

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Display genome mutation timeline."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--agent", help="Agent ID, e.g. Claude-1@claude")
    group.add_argument("--all", action="store_true", help="Show all agents")
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root (default: auto-detect from script location)",
    )
    args = parser.parse_args()

    root = _repo_root(args.root)

    if args.all:
        sys.exit(log_all(root))
    else:
        sys.exit(log_agent(args.agent, root))


if __name__ == "__main__":
    main()
