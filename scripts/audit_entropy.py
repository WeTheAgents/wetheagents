#!/usr/bin/env python3
"""
Filesystem entropy audit for genomes/ and local git worktrees.

Checks:
1. Genome directories against ledger/balances.json registrations.
2. Genome metadata consistency and duplicate agent directories.
3. Registered git worktrees with missing paths or detached HEADs.
4. Local wetheagents* git directories that are not registered as worktrees.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


SKIP_GENOME_DIRS = {"base"}
SKIP_BALANCE_AGENTS = {"agent0@system"}


def _repo_root(override: str | None = None) -> Path:
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parent.parent


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _finding(kind: str, subject: str, detail: str) -> dict[str, str]:
    return {"kind": kind, "subject": subject, "detail": detail}


def _norm_path(path: Path | str) -> str:
    return str(Path(path).resolve(strict=False)).replace("\\", "/").lower()


def parse_worktree_porcelain(text: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    current: dict[str, str] = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            if current:
                entries.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value

    if current:
        entries.append(current)

    return entries


def audit_genomes(root: Path) -> list[dict[str, str]]:
    genomes_dir = root / "genomes"
    balances_path = root / "ledger" / "balances.json"
    balances = _load_json(balances_path)
    registered_agents = set(balances.get("agents", {})) - SKIP_BALANCE_AGENTS

    findings: list[dict[str, str]] = []
    seen_agent_dirs: dict[str, list[str]] = {}
    present_agents: set[str] = set()

    for genome_dir in sorted(genomes_dir.iterdir()):
        if not genome_dir.is_dir() or genome_dir.name in SKIP_GENOME_DIRS:
            continue

        rel_dir = str(genome_dir.relative_to(root)).replace("\\", "/")
        meta_path = genome_dir / "genome_meta.json"
        if not meta_path.exists():
            detail = "directory is missing genome_meta.json"
            if (genome_dir / "AGENTS.local.md").exists():
                detail += " but still contains AGENTS.local.md"
            findings.append(_finding("stale_genome_dir", rel_dir, detail))
            continue

        try:
            meta = _load_json(meta_path)
        except (OSError, json.JSONDecodeError) as exc:
            findings.append(
                _finding("invalid_genome_meta", rel_dir, f"cannot load genome_meta.json: {exc}")
            )
            continue

        agent_id = meta.get("agent_id")
        if not isinstance(agent_id, str) or not agent_id:
            findings.append(_finding("missing_agent_id", rel_dir, "genome_meta.json has no agent_id"))
            continue

        present_agents.add(agent_id)
        seen_agent_dirs.setdefault(agent_id, []).append(rel_dir)

        if genome_dir.name != agent_id:
            findings.append(
                _finding(
                    "genome_dir_agent_id_mismatch",
                    rel_dir,
                    f"directory name does not match genome_meta.json agent_id '{agent_id}'",
                )
            )

        if agent_id not in registered_agents:
            findings.append(
                _finding(
                    "unregistered_genome_agent",
                    rel_dir,
                    f"agent_id '{agent_id}' is not registered in ledger/balances.json",
                )
            )

    for agent_id, paths in sorted(seen_agent_dirs.items()):
        if len(paths) > 1:
            findings.append(
                _finding(
                    "duplicate_genome_agent",
                    agent_id,
                    "multiple genome directories declare the same agent_id: "
                    + ", ".join(sorted(paths)),
                )
            )

    for agent_id in sorted(registered_agents - present_agents):
        findings.append(
            _finding(
                "missing_genome_dir",
                agent_id,
                "agent is registered in ledger/balances.json but has no genome directory",
            )
        )

    return findings


def audit_worktrees(root: Path, porcelain: str | None = None) -> list[dict[str, str]]:
    if porcelain is None:
        proc = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        porcelain = proc.stdout

    entries = parse_worktree_porcelain(porcelain)
    findings: list[dict[str, str]] = []
    registered_paths = {_norm_path(entry["worktree"]) for entry in entries if "worktree" in entry}

    for entry in entries:
        worktree = entry.get("worktree")
        if not worktree:
            continue
        path = Path(worktree)
        if not path.exists():
            findings.append(
                _finding(
                    "missing_registered_worktree",
                    worktree,
                    "git tracks this worktree path but the directory does not exist",
                )
            )
        if "branch" not in entry:
            findings.append(
                _finding(
                    "detached_worktree",
                    worktree,
                    "worktree is registered with detached HEAD",
                )
            )

    parent = root.parent
    for candidate in sorted(parent.iterdir()):
        if not candidate.is_dir() or not candidate.name.startswith("wetheagents"):
            continue
        if not (candidate / ".git").exists():
            continue
        if _norm_path(candidate) in registered_paths:
            continue
        findings.append(
            _finding(
                "unregistered_worktree_dir",
                str(candidate).replace("\\", "/"),
                "filesystem contains a wetheagents* git directory that is not in git worktree list",
            )
        )

    return findings


def collect_report(root: Path, worktree_porcelain: str | None = None) -> dict[str, Any]:
    genome_findings = audit_genomes(root)
    worktree_findings = audit_worktrees(root, porcelain=worktree_porcelain)
    return {
        "root": str(root).replace("\\", "/"),
        "genome_findings": genome_findings,
        "worktree_findings": worktree_findings,
        "counts": {
            "genome_findings": len(genome_findings),
            "worktree_findings": len(worktree_findings),
            "total_findings": len(genome_findings) + len(worktree_findings),
        },
    }


def _print_text(report: dict[str, Any]) -> None:
    genome_findings = report["genome_findings"]
    worktree_findings = report["worktree_findings"]

    if genome_findings:
        print("Genome findings:")
        for finding in genome_findings:
            print(f"- [{finding['kind']}] {finding['subject']}: {finding['detail']}")
    else:
        print("Genome findings: none")

    if worktree_findings:
        print("\nWorktree findings:")
        for finding in worktree_findings:
            print(f"- [{finding['kind']}] {finding['subject']}: {finding['detail']}")
    else:
        print("\nWorktree findings: none")

    counts = report["counts"]
    print(
        f"\nSummary: {counts['genome_findings']} genome finding(s), "
        f"{counts['worktree_findings']} worktree finding(s), "
        f"{counts['total_findings']} total."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit repo filesystem entropy.")
    parser.add_argument("--root", default=None, help="Repository root (default: auto-detect)")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args()

    root = _repo_root(args.root)
    report = collect_report(root)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_text(report)

    return 0 if report["counts"]["total_findings"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
