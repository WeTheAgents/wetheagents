#!/usr/bin/env python3
"""Identify and optionally delete stale local branches with safety guards."""

from __future__ import annotations

# ruff: noqa: I001

import argparse
import io
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _stdout_needs_utf8() -> bool:
    encoding = (sys.stdout.encoding or "").lower().replace("-", "")
    return hasattr(sys.stdout, "buffer") and encoding != "utf8"


# Ensure UTF-8 output on all platforms (Windows may default to cp1251/cp1252).
if _stdout_needs_utf8():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from io_helpers import load_json, now_iso  # noqa: E402


CATEGORY_ORDER = (
    "merged_into_main",
    "gone_remote",
    "closed_task_pr_merged",
    "idle_30d",
)
CATEGORY_LABELS = {
    "merged_into_main": "merged into main",
    "gone_remote": "gone-remote",
    "closed_task_pr_merged": "closed-task-pr-merged",
    "idle_30d": "idle-30d",
}
OPEN_TASK_STATUSES = {"open", "claimed"}
BRANCH_LOG = Path("agent0_diary") / "branch_cleanup_log.jsonl"


@dataclass
class BranchInfo:
    """Local branch metadata from git for-each-ref."""

    name: str
    sha: str
    upstream: str | None
    upstream_track: str | None
    committed_at: datetime
    issue: int | None


@dataclass
class BranchReport:
    """Classification result for a local branch."""

    branch: BranchInfo
    categories: list[str] = field(default_factory=list)
    protections: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    open_pr_number: int | None = None
    open_pr_url: str | None = None

    @property
    def age_days(self) -> float:
        return round(
            (datetime.now(timezone.utc) - self.branch.committed_at).total_seconds()
            / 86400.0,
            1,
        )

    @property
    def is_stale(self) -> bool:
        return bool(self.categories)

    @property
    def can_delete(self) -> bool:
        return self.is_stale and not self.protections


def parse_iso_utc(value: str) -> datetime:
    """Parse an ISO timestamp into a UTC-aware datetime."""
    raw = value.strip()
    if not raw:
        raise ValueError("empty timestamp")
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _repo_root_from(root: str | None) -> Path:
    if root:
        return Path(root).resolve()
    return Path(__file__).resolve().parent.parent


def _run(
    args: list[str],
    *,
    cwd: Path,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        check=check,
        text=True,
    )


def _git(
    args: list[str],
    *,
    cwd: Path,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return _run(["git", *args], cwd=cwd, check=check)


def _gh(
    args: list[str],
    *,
    cwd: Path,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return _run(["gh", *args], cwd=cwd, check=check)


def _parse_issue(branch_name: str) -> int | None:
    parts = branch_name.split("/")
    if len(parts) != 3 or parts[0] != "agent":
        return None
    issue_part = parts[2].split("-", 1)[0]
    if not issue_part.isdigit():
        return None
    return int(issue_part)


def _parse_worktree_porcelain(text: str) -> list[dict[str, str]]:
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


def _load_open_task_statuses(root: Path) -> dict[int, str]:
    task_index = load_json(
        root / "ledger" / "task_index.json",
        default={"tasks": {}},
        encoding="utf-8-sig",
    )
    tasks = task_index.get("tasks", {})
    if not isinstance(tasks, dict):
        return {}

    statuses: dict[int, str] = {}
    for issue_str, payload in tasks.items():
        if not isinstance(payload, dict):
            continue
        try:
            issue = int(issue_str)
        except (TypeError, ValueError):
            continue
        status = payload.get("status")
        if isinstance(status, str):
            statuses[issue] = status
    return statuses


def _list_local_branches(root: Path) -> list[BranchInfo]:
    result = _git(
        [
            "for-each-ref",
            "--format=%(refname:short)|%(objectname)|%(upstream:short)|"
            "%(upstream:track)|%(committerdate:iso8601)",
            "refs/heads",
        ],
        cwd=root,
    )

    branches: list[BranchInfo] = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        parts = line.split("|")
        if len(parts) != 5:
            continue
        name, sha, upstream, upstream_track, committed_raw = parts
        branches.append(
            BranchInfo(
                name=name,
                sha=sha,
                upstream=upstream or None,
                upstream_track=upstream_track or None,
                committed_at=parse_iso_utc(committed_raw),
                issue=_parse_issue(name),
            )
        )

    return sorted(branches, key=lambda item: item.name)


def _resolve_main_ref(root: Path, override: str | None) -> tuple[str, str]:
    candidates = [override] if override else []
    candidates.extend(
        ["refs/remotes/origin/main", "origin/main", "refs/heads/main", "main"]
    )

    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        result = _git(["rev-parse", "--verify", candidate], cwd=root, check=False)
        if result.returncode == 0:
            return candidate, result.stdout.strip()

    raise RuntimeError("Could not resolve a main branch ref.")


def _worktree_branch_map(root: Path) -> dict[str, str]:
    result = _git(["worktree", "list", "--porcelain"], cwd=root)
    branch_map: dict[str, str] = {}

    for entry in _parse_worktree_porcelain(result.stdout):
        branch_ref = entry.get("branch")
        path = entry.get("worktree")
        if not branch_ref or not path or not branch_ref.startswith("refs/heads/"):
            continue
        branch_map[branch_ref[len("refs/heads/") :]] = path.replace("\\", "/")

    return branch_map


def _branch_is_merged(
    root: Path,
    branch_name: str,
    main_ref: str,
    main_sha: str,
) -> bool:
    branch_sha = _git(["rev-parse", branch_name], cwd=root).stdout.strip()
    if branch_sha == main_sha:
        return False
    result = _git(
        ["merge-base", "--is-ancestor", branch_name, main_ref],
        cwd=root,
        check=False,
    )
    return result.returncode == 0


def _query_open_pull_requests(
    root: Path,
) -> tuple[dict[str, dict[str, Any]], str | None]:
    try:
        result = _gh(
            [
                "pr",
                "list",
                "--state",
                "open",
                "--limit",
                "500",
                "--json",
                "number,headRefName,url",
            ],
            cwd=root,
        )
    except FileNotFoundError:
        return {}, "gh not found in PATH"
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        return {}, detail

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return {}, f"invalid gh pr list JSON: {exc}"

    open_prs: dict[str, dict[str, Any]] = {}
    for row in payload:
        if not isinstance(row, dict):
            continue
        head = row.get("headRefName")
        number = row.get("number")
        if not isinstance(head, str) or not isinstance(number, int):
            continue
        open_prs[head] = {
            "number": number,
            "url": row.get("url"),
        }
    return open_prs, None


def _git_log_has_match(
    root: Path,
    main_ref: str,
    pattern: str,
    *,
    merges_only: bool = False,
) -> bool:
    args = ["log"]
    if merges_only:
        args.append("--merges")
    args.extend(
        [main_ref, "--format=%s", "-n", "1", "--extended-regexp", "--grep", pattern]
    )
    result = _git(args, cwd=root, check=False)
    return result.returncode == 0 and bool(result.stdout.strip())


def _issue_closed_by_merged_task(
    root: Path,
    main_ref: str,
    issue: int | None,
    branch_name: str,
    task_statuses: dict[int, str],
    issue_cache: dict[int, bool],
) -> bool:
    if issue is None:
        return False
    if task_statuses.get(issue) in OPEN_TASK_STATUSES:
        return False
    if issue in issue_cache:
        return issue_cache[issue]

    task_subject_pattern = rf"^\[Task #{issue}\]"
    if _git_log_has_match(root, main_ref, task_subject_pattern):
        issue_cache[issue] = True
        return True

    merge_subject_pattern = rf"Merge pull request .*{re.escape(branch_name)}$"
    return _git_log_has_match(
        root,
        main_ref,
        merge_subject_pattern,
        merges_only=True,
    )


def _is_agent0_branch(branch_name: str) -> bool:
    return branch_name.startswith("agent0/") or branch_name.startswith("agent/agent0/")


def _write_predelete_log(log_path: Path, record: BranchReport) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": now_iso(),
        "action": "pre_delete",
        "branch": record.branch.name,
        "sha": record.branch.sha,
        "categories": list(record.categories),
    }
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def build_report(
    root: Path,
    *,
    main_ref_override: str | None = None,
    idle_days: int = 30,
) -> tuple[list[BranchReport], str, Path, str | None]:
    branches = _list_local_branches(root)
    main_ref, main_sha = _resolve_main_ref(root, main_ref_override)
    worktree_branches = _worktree_branch_map(root)
    task_statuses = _load_open_task_statuses(root)
    open_prs, pr_query_error = _query_open_pull_requests(root)
    now = datetime.now(timezone.utc)
    idle_threshold = timedelta(days=idle_days)
    issue_cache: dict[int, bool] = {}
    reports: list[BranchReport] = []

    for branch in branches:
        row = BranchReport(branch=branch)

        if branch.name == "main":
            row.protections.append("protected:main")
        if _is_agent0_branch(branch.name):
            row.protections.append("protected:agent0")

        worktree_path = worktree_branches.get(branch.name)
        if worktree_path:
            row.protections.append(f"checked_out_in_worktree:{worktree_path}")

        open_pr = open_prs.get(branch.name)
        if open_pr:
            row.protections.append(f"open_pr:#{open_pr['number']}")
            row.open_pr_number = open_pr["number"]
            row.open_pr_url = str(open_pr.get("url") or "")

        if _branch_is_merged(root, branch.name, main_ref, main_sha):
            row.categories.append("merged_into_main")

        if branch.upstream_track and "gone" in branch.upstream_track.lower():
            row.categories.append("gone_remote")

        if _issue_closed_by_merged_task(
            root,
            main_ref,
            branch.issue,
            branch.name,
            task_statuses,
            issue_cache,
        ):
            row.categories.append("closed_task_pr_merged")

        if now - branch.committed_at > idle_threshold:
            row.categories.append("idle_30d")

        reports.append(row)

    log_path = root / BRANCH_LOG
    return reports, main_ref, log_path, pr_query_error


def render_report(
    reports: list[BranchReport],
    *,
    main_ref: str,
    log_path: Path,
    apply: bool,
    pr_query_error: str | None,
) -> str:
    category_counts = {category: 0 for category in CATEGORY_ORDER}
    stale_candidates = [row for row in reports if row.is_stale]
    deletable = [row for row in stale_candidates if row.can_delete]
    protected = [row for row in stale_candidates if row.protections]

    for row in stale_candidates:
        for category in row.categories:
            category_counts[category] += 1

    lines = [
        "BRANCH CLEANUP",
        f"Mode: {'apply' if apply else 'dry-run'}",
        f"Main ref: {main_ref}",
        f"Branch log: {log_path.as_posix()}",
        (
            "Open PR guard: unavailable"
            if pr_query_error
            else "Open PR guard: verified via gh"
        ),
    ]
    if pr_query_error:
        lines.append(f"Open PR note: {pr_query_error}")

    lines.append("")
    lines.append("Category counts:")
    for category in CATEGORY_ORDER:
        lines.append(f"- {CATEGORY_LABELS[category]}: {category_counts[category]}")

    lines.append("")
    lines.append(f"Stale branches found: {len(stale_candidates)}")
    lines.append(f"Deletion candidates: {len(deletable)}")
    lines.append(f"Protected or skipped: {len(protected)}")

    if deletable:
        lines.append("")
        lines.append("Deletion candidates:")
        for row in deletable:
            labels = ", ".join(CATEGORY_LABELS[item] for item in row.categories)
            lines.append(
                f"- {row.branch.name} @ {row.branch.sha[:7]} | "
                f"age={row.age_days}d | {labels}"
            )

    if protected:
        lines.append("")
        lines.append("Protected or skipped:")
        for row in protected:
            labels = ", ".join(CATEGORY_LABELS[item] for item in row.categories)
            protections = ", ".join(row.protections)
            lines.append(
                f"- {row.branch.name} @ {row.branch.sha[:7]} | age={row.age_days}d | "
                f"{labels} | {protections}"
            )

    if not stale_candidates:
        lines.append("")
        lines.append("No stale branches matched the cleanup categories.")

    if apply and pr_query_error:
        lines.append("")
        lines.append(
            "Apply blocked: open PR verification failed, so no branches "
            "will be deleted."
        )

    return "\n".join(lines)


def apply_deletions(
    root: Path,
    *,
    reports: list[BranchReport],
    log_path: Path,
) -> tuple[list[str], list[str]]:
    deleted: list[str] = []
    failed: list[str] = []

    for row in reports:
        if not row.can_delete:
            continue

        _write_predelete_log(log_path, row)
        result = _git(["branch", "-D", row.branch.name], cwd=root, check=False)
        if result.returncode == 0:
            deleted.append(row.branch.name)
            continue

        detail = (result.stderr or result.stdout or "git branch -D failed").strip()
        failed.append(f"{row.branch.name}: {detail}")

    return deleted, failed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Identify stale local branches by merged/gone/closed-task/idle signals "
            "and optionally delete them."
        )
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root (default: auto-detect from script location)",
    )
    parser.add_argument(
        "--main-ref",
        default=None,
        help="Override the ref used for merged-into-main checks",
    )
    parser.add_argument(
        "--idle-days",
        type=int,
        default=30,
        help="Idle threshold in days for the idle-30d category (default: 30)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Delete eligible stale branches after logging SHA+name to JSONL",
    )
    args = parser.parse_args(argv)

    root = _repo_root_from(args.root)

    try:
        reports, main_ref, log_path, pr_query_error = build_report(
            root,
            main_ref_override=args.main_ref,
            idle_days=args.idle_days,
        )
    except (RuntimeError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    print(
        render_report(
            reports,
            main_ref=main_ref,
            log_path=log_path,
            apply=args.apply,
            pr_query_error=pr_query_error,
        )
    )

    if args.apply:
        if pr_query_error:
            return 2
        deleted, failed = apply_deletions(root, reports=reports, log_path=log_path)
        print("")
        print(f"Deleted branches: {len(deleted)}")
        for branch_name in deleted:
            print(f"- {branch_name}")
        if failed:
            print("")
            print("Delete failures:")
            for failure in failed:
                print(f"- {failure}")
            return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
