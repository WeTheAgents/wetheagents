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

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from wea_cli.config import resolve_agent  # noqa: E402
from wea_cli.genome_context import (  # noqa: E402
    _canonical_context,
    _canonical_path_ever_existed,
    _metadata,
)

RELEASE_TRAILER = re.compile(r"^Release-Session:\s*#(\d+)", re.MULTILINE)
AMENDMENT_TRAILER = re.compile(r"^Constitution-Amendment:\s*#(\d+)", re.MULTILINE)
GENESIS_TRAILER = re.compile(r"^Genome-Genesis:\s*(\S+)\s*$", re.MULTILINE)

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


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        capture_output=True,
        check=True,
        encoding="utf-8",
        text=True,
    )
    return result.stdout


def _canonical_json(value: object) -> str:
    """Serialize JSON with value types preserved for exact comparisons."""
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _is_valid_self_genesis(commit_msg: str) -> bool:
    """Allow one create-only, canonical, self-owned generation-zero genome."""
    matches = GENESIS_TRAILER.findall(commit_msg)
    actor = resolve_agent(None) or ""
    if len(matches) != 1 or not actor or matches[0] != actor:
        return False
    agent_id = actor
    prefix = f"genomes/{agent_id}/"
    expected = {
        prefix + "AGENTS.local.md",
        prefix + "genome_meta.json",
    }
    try:
        root = Path(_git("rev-parse", "--show-toplevel").strip())
        context = _canonical_context(root)
        target = context.targets.get(agent_id)
        if target is None:
            return False
        staged = {
            path.replace("\\", "/")
            for path in _git(
                "diff", "--cached", "--name-only", "--", "genomes"
            ).splitlines()
        }
        added = {
            path.replace("\\", "/")
            for path in _git(
                "diff", "--cached", "--diff-filter=A", "--name-only", "--", "genomes"
            ).splitlines()
        }
        if staged != expected or added != expected:
            return False
        if _canonical_path_ever_existed(root, context.commit, prefix):
            return False
        meta = json.loads(_git("show", f":{prefix}genome_meta.json"))
        genome = _git("show", f":{prefix}AGENTS.local.md")
    except (OSError, subprocess.CalledProcessError, ValueError):
        return False
    return (
        _canonical_json(meta) == _canonical_json(_metadata(target))
        and genome == context.template
    )


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

    # Existing genome changes need a release. One canonical create-only self-genesis
    # can instead carry a Genome-Genesis trailer matching the configured identity.
    if (
        agent_genomes
        and not _is_valid_self_genesis(commit_msg)
        and not RELEASE_TRAILER.search(commit_msg)
    ):
        files_list = ", ".join(agent_genomes)
        errors.append(
            f"GENOME DRIFT BLOCKED: commit modifies agent genome(s):\n"
            f"  {files_list}\n"
            f"\n"
            f"  Existing genome changes are only allowed during Release sessions.\n"
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
