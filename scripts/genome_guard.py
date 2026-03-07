#!/usr/bin/env python3
"""
Genome Guard — validates AGENTS.local.md files across all agents.

Two checks:
1. Line limit: each AGENTS.local.md must be ≤120 lines.
2. Constitution integrity: the first N lines (determined by template)
   must match the template exactly.

Constitution changes are NOT failures — they are amendment signals.
If an agent proposes a change, this script blocks the commit and
reports the diff so Agent0 can initiate a discussion.
"""

import argparse
import os
import sys
from pathlib import Path

MAX_LINES = 120


def get_constitution_length(template_lines: list[str]) -> int:
    """Count lines before first --- in the template.

    The template is the single source of truth for constitution length.
    """
    for i, line in enumerate(template_lines):
        if line.strip() == "---":
            return i
    return len(template_lines)


def check_line_limit(filepath: Path, lines: list[str]) -> str | None:
    """Return error message if file exceeds MAX_LINES."""
    count = len(lines)
    if count > MAX_LINES:
        return (
            f"FAIL: {filepath.name} has {count} lines (max {MAX_LINES})\n"
            f"  Agent: {filepath.parent.name}\n"
            f"  Reduce genome content. Only the most valuable survives."
        )
    return None


def check_constitution(
    filepath: Path,
    agent_lines: list[str],
    template_lines: list[str],
    const_len: int,
) -> str | None:
    """Compare first const_len lines of agent file to template."""
    agent_zone = agent_lines[:const_len]
    template_zone = template_lines[:const_len]

    if agent_zone == template_zone:
        return None

    # Find specific differences
    diffs = []
    max_len = max(len(agent_zone), len(template_zone))
    for i in range(max_len):
        tpl = template_zone[i] if i < len(template_zone) else "<missing>"
        agt = agent_zone[i] if i < len(agent_zone) else "<missing>"
        if tpl != agt:
            diffs.append(
                f"  Line {i + 1}:\n"
                f"    template: {tpl.rstrip()}\n"
                f"    agent:    {agt.rstrip()}"
            )

    diff_text = "\n".join(diffs)
    return (
        f"AMENDMENT SIGNAL: {filepath.parent.name} proposes constitutional change\n"
        f"  File: {filepath}\n"
        f"  Differences:\n{diff_text}\n"
        "\n"
        "  This is valuable signal — not an error.\n"
        "  But constitution changes require community discussion.\n"
        "\n"
        "  Next steps:\n"
        "    1. Open an issue describing WHY you want this change\n"
        "    2. Agent0 will facilitate the discussion\n"
        "    3. If approved, the change applies to ALL agents"
    )


def main():
    parser = argparse.ArgumentParser(description="Genome Guard — AGENTS.local.md validator")
    parser.add_argument(
        "--root",
        help="Root directory of the wetheagents repository",
        default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    parser.add_argument(
        "--files",
        nargs="*",
        help="Specific files to check (for pre-commit). If not given, checks all genomes.",
    )
    args = parser.parse_args()

    base_dir = Path(args.root)
    genomes_dir = base_dir / "genomes"
    template_path = genomes_dir / "base" / "AGENTS.local.template.md"

    # Load base template
    if not template_path.exists():
        print(f"FAIL: Base template not found: {template_path}")
        sys.exit(1)

    template_lines = template_path.read_text(encoding="utf-8").splitlines()
    const_len = get_constitution_length(template_lines)

    # Find agent genome files
    if args.files:
        genome_files = [
            Path(f) for f in args.files
            if f.endswith("AGENTS.local.md") and "genomes/base" not in f.replace("\\", "/")
        ]
    else:
        genome_files = sorted(genomes_dir.glob("*/AGENTS.local.md"))
        genome_files = [f for f in genome_files if f.parent.name != "base"]

    if not genome_files:
        print("No agent genome files found.")
        sys.exit(0)

    errors = []

    for filepath in genome_files:
        lines = filepath.read_text(encoding="utf-8").splitlines()

        err = check_line_limit(filepath, lines)
        if err:
            errors.append(err)

        err = check_constitution(filepath, lines, template_lines, const_len)
        if err:
            errors.append(err)

    # Report
    print(f"Genome Guard: checked {len(genome_files)} agent(s), constitution={const_len} lines")

    if not errors:
        print("Status: PASS")
        sys.exit(0)

    for e in errors:
        print()
        print(e)
        print()

    sys.exit(1)


if __name__ == "__main__":
    main()
