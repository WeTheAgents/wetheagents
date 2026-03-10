#!/usr/bin/env python3
"""
Genome Drift Guard — blocks genome commits without authorization trailers.

Pipeline v3 requires genome mutations only during Release sessions.
This script runs as a commit-msg hook and enforces:

- Agent genome changes require: `Release-Session: #<issue>`
- Base template changes require: `Constitution-Amendment: #<issue>`
- Agent0 (agent0@system) bypasses both checks.

Usage (called by .githooks/commit-msg):
  python scripts/check_genome_trailer.py <commit-msg-file>
"""

import os
import re
import subprocess
import sys
from pathlib import Path

RELEASE_TRAILER = re.compile(r"^Release-Session:\s*#(\d+)", re.MULTILINE)
AMENDMENT_TRAILER = re.compile(r"^Constitution-Amendment:\s*#(\d+)", re.MULTILINE)

AGENT0_IDENTITIES = {"agent0@system"}


def _get_staged_genome_files() -> tuple[list[str], list[str]]:
    """Return (agent_genome_files, template_files) from staged changes."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        capture_output=True,
        text=True,
    )
    files = result.stdout.strip().splitlines()

    agent_genomes = []
    templates = []
    for f in files:
        normalized = f.replace("\\", "/")
        if normalized.endswith("AGENTS.local.template.md"):
            templates.append(f)
        elif normalized.endswith("AGENTS.local.md") and "genomes/" in normalized:
            agent_genomes.append(f)
    return agent_genomes, templates


def _is_agent0() -> bool:
    """Check if current committer is Agent0."""
    # Check WEA_AGENT env var first
    wea_agent = os.environ.get("WEA_AGENT", "")
    if wea_agent in AGENT0_IDENTITIES:
        return True

    # Check git config user.email
    result = subprocess.run(
        ["git", "config", "user.email"],
        capture_output=True,
        text=True,
    )
    email = result.stdout.strip()
    if email in AGENT0_IDENTITIES:
        return True

    return False


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: check_genome_trailer.py <commit-msg-file>")
        return 2

    msg_file = Path(sys.argv[1])
    if not msg_file.exists():
        return 0

    commit_msg = msg_file.read_text(encoding="utf-8")

    agent_genomes, templates = _get_staged_genome_files()

    # No genome files staged — nothing to check
    if not agent_genomes and not templates:
        return 0

    # Agent0 bypass
    if _is_agent0():
        return 0

    errors = []

    # Check agent genome files → need Release-Session trailer
    if agent_genomes and not RELEASE_TRAILER.search(commit_msg):
        files_list = ", ".join(agent_genomes)
        errors.append(
            f"GENOME DRIFT BLOCKED: commit modifies agent genome(s):\n"
            f"  {files_list}\n"
            f"\n"
            f"  Genome changes are only allowed during Release sessions.\n"
            f"  Add this trailer to your commit message:\n"
            f"\n"
            f"    Release-Session: #<issue_number>\n"
            f"\n"
            f"  where <issue_number> is the Release session issue."
        )

    # Check template files → need Constitution-Amendment trailer
    if templates and not AMENDMENT_TRAILER.search(commit_msg):
        files_list = ", ".join(templates)
        errors.append(
            f"CONSTITUTION CHANGE BLOCKED: commit modifies base template:\n"
            f"  {files_list}\n"
            f"\n"
            f"  Constitution changes require a governance vote.\n"
            f"  Add this trailer to your commit message:\n"
            f"\n"
            f"    Constitution-Amendment: #<issue_number>\n"
            f"\n"
            f"  where <issue_number> is the governance issue."
        )

    if errors:
        for e in errors:
            print()
            print(e)
            print()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
