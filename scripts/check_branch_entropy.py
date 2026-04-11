#!/usr/bin/env python3
"""Audit remote agent branches against task_index.json to flag stale work."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from io_helpers import load_json  # noqa: E402


def _repo_root_from(root: str | None) -> Path:
    if root:
        return Path(root).resolve()
    return Path(__file__).resolve().parent.parent


def load_task_index(root: Path) -> dict[str, Any]:
    return load_json(
        root / "ledger" / "task_index.json",
        default={"tasks": {}},
        encoding="utf-8-sig",
    )


def list_remote_branches(remote: str = "origin") -> tuple[list[str], str | None]:
    """Return remote branch names from git ls-remote --heads."""
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--heads", remote],
            capture_output=True,
            check=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        if isinstance(exc, subprocess.CalledProcessError):
            detail = (exc.stderr or exc.stdout or str(exc)).strip()
        else:
            detail = str(exc)
        return [], detail

    branches: list[str] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 2 or not parts[1].startswith("refs/heads/"):
            continue
        branches.append(parts[1][len("refs/heads/") :])
    return branches, None


def extract_issue_number(branch: str) -> int | None:
    """Return issue number for agent/{slug}/{issue}-{desc} branches."""
    parts = branch.split("/")
    if len(parts) != 3 or parts[0] != "agent":
        return None

    issue_part = parts[2].split("-", 1)[0]
    if not issue_part.isdigit():
        return None
    return int(issue_part)


def classify_branch(branch: str, tasks: dict[str, Any]) -> dict[str, Any]:
    """Classify a branch as ACTIVE, STALE, or REVIEW."""
    issue = extract_issue_number(branch)
    record: dict[str, Any] = {
        "branch": branch,
        "issue": issue,
        "classification": "REVIEW",
        "task_status": None,
        "title": None,
        "reason": "branch does not match agent/{slug}/{issue}-{desc}",
    }
    if issue is None:
        return record

    task = tasks.get(str(issue))
    if task is None:
        record["reason"] = "issue not found in ledger/task_index.json"
        return record

    task_status = task.get("status")
    record["task_status"] = task_status
    record["title"] = task.get("title")

    if task_status == "paid":
        record["classification"] = "STALE"
        record["reason"] = "task is paid in task_index.json"
    elif task_status == "open":
        record["classification"] = "ACTIVE"
        record["reason"] = "task is open in task_index.json"
    else:
        record["reason"] = f"task status={task_status!r} needs manual review"

    return record


def build_report(branches: list[str], task_index: dict[str, Any]) -> list[dict[str, Any]]:
    tasks = task_index.get("tasks", {})
    return [classify_branch(branch, tasks) for branch in sorted(branches)]


def render_report(
    report: list[dict[str, Any]],
    *,
    remote: str = "origin",
    error: str | None = None,
) -> str:
    counts = {"STALE": 0, "ACTIVE": 0, "REVIEW": 0}
    for row in report:
        counts[row["classification"]] += 1

    lines = [
        "BRANCH ENTROPY AUDIT",
        f"Remote: {remote}",
        f"Branches audited: {len(report)}",
        (
            f"Summary: {counts['STALE']} STALE, "
            f"{counts['ACTIVE']} ACTIVE, {counts['REVIEW']} REVIEW"
        ),
    ]
    if error:
        lines.append(f"Collection note: {error}")

    if not report:
        lines.append("No remote branches found to audit.")
        return "\n".join(lines)

    lines.append("")
    for row in report:
        issue_text = f"#{row['issue']}" if row["issue"] is not None else "n/a"
        title = f" | {row['title']}" if row.get("title") else ""
        status = row["task_status"] if row["task_status"] is not None else "n/a"
        lines.append(
            f"[{row['classification']}] {row['branch']} | issue={issue_text} | "
            f"task_status={status}{title}"
        )
        lines.append(f"  {row['reason']}")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit remote task branches and flag stale branch entropy"
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root (default: auto-detect from script location)",
    )
    parser.add_argument(
        "--remote",
        default="origin",
        help="Git remote to inspect (default: origin)",
    )
    args = parser.parse_args(argv)

    root = _repo_root_from(args.root)
    task_index = load_task_index(root)
    branches, error = list_remote_branches(args.remote)
    report = build_report(branches, task_index)
    print(render_report(report, remote=args.remote, error=error))

    return 0


if __name__ == "__main__":
    sys.exit(main())
