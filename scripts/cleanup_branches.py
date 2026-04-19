#!/usr/bin/env python3
"""Identify and optionally delete stale branches in four categories.

Categories
----------
merged      Local branches whose tip is reachable from origin/main.
gone        Local branches whose remote-tracking branch no longer exists.
closed-task Remote branches whose task issue is closed+paid and PR is merged.
idle-30d    Local branches with no commits in >30 days and no open PR (report only).

Usage
-----
  python scripts/cleanup_branches.py                      # dry-run
  python scripts/cleanup_branches.py --apply              # delete merged + gone local branches
  python scripts/cleanup_branches.py --apply --aggressive # also delete remote closed-task branches

Safety
------
  - Never deletes: main, agent0/*, current branch, worktree-attached branches.
  - Never deletes a branch that has an open PR.
  - Logs SHA + name to agent0_diary/branch_cleanup_log.jsonl BEFORE any deletion.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = REPO_ROOT / "agent0_diary" / "branch_cleanup_log.jsonl"
IDLE_DAYS = 30
PROTECTED_BRANCHES = {"main"}
PROTECTED_PREFIXES = ("agent0/",)

_BRANCH_VV_RE = re.compile(
    r"^(?P<cur>[*\s]) (?P<name>\S+)\s+(?P<sha>[0-9a-f]+)\s*(?:\[(?P<tracking>[^\]]*)\])?"
)


# ── Subprocess helper ─────────────────────────────────────────────────────────

def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)


# ── Protection check ─────────────────────────────────────────────────────────

def _is_protected(name: str) -> bool:
    if name in PROTECTED_BRANCHES:
        return True
    return any(name.startswith(p) for p in PROTECTED_PREFIXES)


# ── Batch GitHub API queries ──────────────────────────────────────────────────

def _fetch_open_pr_branches() -> set[str]:
    """Branch names that have at least one open PR (must not delete)."""
    r = _run(["gh", "pr", "list", "--state", "open", "--json", "headRefName", "--limit", "1000"])
    if r.returncode != 0:
        print(f"[warn] gh pr list open failed: {r.stderr.strip()}", file=sys.stderr)
        return set()
    try:
        return {pr["headRefName"] for pr in json.loads(r.stdout)}
    except (json.JSONDecodeError, KeyError):
        return set()


def _fetch_paid_closed_issue_numbers() -> set[str]:
    """Issue numbers that are closed AND carry the 'paid' label."""
    r = _run([
        "gh", "issue", "list", "--state", "closed", "--label", "paid",
        "--json", "number", "--limit", "2000",
    ])
    if r.returncode != 0:
        print(f"[warn] gh issue list closed+paid failed: {r.stderr.strip()}", file=sys.stderr)
        return set()
    try:
        return {str(issue["number"]) for issue in json.loads(r.stdout)}
    except (json.JSONDecodeError, KeyError):
        return set()


def _fetch_merged_pr_branches() -> set[str]:
    """Branch names whose PR was merged (confirming work was accepted)."""
    r = _run(["gh", "pr", "list", "--state", "merged", "--json", "headRefName", "--limit", "2000"])
    if r.returncode != 0:
        print(f"[warn] gh pr list merged failed: {r.stderr.strip()}", file=sys.stderr)
        return set()
    try:
        return {pr["headRefName"] for pr in json.loads(r.stdout)}
    except (json.JSONDecodeError, KeyError):
        return set()


# ── Git queries ───────────────────────────────────────────────────────────────

def _parse_local_branches() -> list[dict]:
    """Parse `git branch -vv` into structured records."""
    r = _run(["git", "branch", "-vv"])
    branches = []
    for line in r.stdout.splitlines():
        m = _BRANCH_VV_RE.match(line)
        if not m:
            continue
        name = m.group("name")
        if name.startswith("("):  # skip "(HEAD detached at ...)" entries
            continue
        tracking = m.group("tracking") or ""
        branches.append({
            "name": name,
            "sha": m.group("sha"),
            "current": m.group("cur") == "*",
            "gone": ": gone" in tracking,
        })
    return branches


def _fetch_merged_local_names() -> set[str]:
    """Local branch names whose tips are reachable from origin/main."""
    r = _run(["git", "branch", "--merged", "origin/main"])
    names: set[str] = set()
    for line in r.stdout.splitlines():
        name = line.strip().lstrip("* ")
        if name and not name.startswith("("):  # skip detached HEAD entries
            names.add(name)
    return names


def _fetch_remote_branch_names() -> list[str]:
    """Remote branch names (stripped of 'origin/' prefix)."""
    r = _run(["git", "branch", "-r"])
    branches = []
    for line in r.stdout.splitlines():
        branch = line.strip()
        if branch.startswith("origin/") and "->" not in branch:
            branches.append(branch[len("origin/"):])
    return branches


def _fetch_worktree_branches() -> set[str]:
    """Branch names currently checked out in any worktree (must not delete)."""
    r = _run(["git", "worktree", "list", "--porcelain"])
    branches: set[str] = set()
    for line in r.stdout.splitlines():
        if line.startswith("branch "):
            b = line[7:].strip()
            if b.startswith("refs/heads/"):
                b = b[len("refs/heads/"):]
            branches.add(b)
    return branches


def _get_branch_last_commit_dates() -> dict[str, datetime]:
    """Map of local branch name → last committer date (UTC)."""
    r = _run([
        "git", "for-each-ref",
        "--format=%(refname:short)\t%(committerdate:unix)",
        "refs/heads",
    ])
    dates: dict[str, datetime] = {}
    for line in r.stdout.splitlines():
        if "\t" not in line:
            continue
        name, ts_str = line.split("\t", 1)
        try:
            dates[name] = datetime.fromtimestamp(int(ts_str.strip()), tz=timezone.utc)
        except (ValueError, OSError):
            pass
    return dates


def _parse_issue_number(branch_name: str) -> str | None:
    """Extract issue number from agent/<name>/<issue>-<slug> branch names."""
    m = re.search(r"/(\d+)-", branch_name)
    return m.group(1) if m else None


# ── Log ───────────────────────────────────────────────────────────────────────

def _write_log(entries: list[dict]) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Main ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Delete merged and gone local branches",
    )
    parser.add_argument(
        "--aggressive", action="store_true",
        help="Also delete remote closed-task branches (requires --apply)",
    )
    args = parser.parse_args(argv)

    # ── Refresh remote state ──────────────────────────────────────────────────
    print("[info] Fetching origin (--prune)…")
    r = _run(["git", "fetch", "origin", "--prune"])
    if r.returncode != 0:
        print(f"[warn] git fetch failed: {r.stderr.strip()}")

    # ── Batch GitHub queries ──────────────────────────────────────────────────
    print("[info] Querying GitHub…")
    open_pr_branches = _fetch_open_pr_branches()
    paid_closed_issues = _fetch_paid_closed_issue_numbers()
    merged_pr_branches = _fetch_merged_pr_branches()

    # ── Local branch data ─────────────────────────────────────────────────────
    local_branches = _parse_local_branches()
    merged_local_names = _fetch_merged_local_names()
    worktree_branches = _fetch_worktree_branches()
    branch_dates = _get_branch_last_commit_dates()

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=IDLE_DAYS)

    # ── Category 1: merged ────────────────────────────────────────────────────
    merged: list[dict] = []
    for b in local_branches:
        if _is_protected(b["name"]) or b["current"] or b["name"] in worktree_branches:
            continue
        if b["name"] in merged_local_names and b["name"] not in open_pr_branches:
            merged.append(b)

    # ── Category 2: gone ──────────────────────────────────────────────────────
    gone: list[dict] = []
    for b in local_branches:
        if _is_protected(b["name"]) or b["current"] or b["name"] in worktree_branches:
            continue
        if b["gone"] and b["name"] not in open_pr_branches:
            gone.append(b)

    # ── Category 3: closed-task (remote) ─────────────────────────────────────
    remote_branches = _fetch_remote_branch_names()
    closed_task: list[str] = []
    for rb in remote_branches:
        if _is_protected(rb) or rb == "main":
            continue
        issue_num = _parse_issue_number(rb)
        if (
            issue_num
            and issue_num in paid_closed_issues
            and rb in merged_pr_branches
            and rb not in open_pr_branches
        ):
            closed_task.append(rb)

    # ── Category 4: idle-30d (report only) ───────────────────────────────────
    idle: list[dict] = []
    for b in local_branches:
        if _is_protected(b["name"]) or b["current"] or b["name"] in worktree_branches:
            continue
        if b["name"] in merged_local_names or b["gone"]:
            continue  # already in merged / gone
        if b["name"] in open_pr_branches:
            continue
        last_dt = branch_dates.get(b["name"])
        if last_dt and last_dt < cutoff:
            idle.append({**b, "last_commit": last_dt.strftime("%Y-%m-%d")})

    # ── Report ────────────────────────────────────────────────────────────────
    print()
    print("=== Stale Branch Report ===")

    print(f"\n[merged] {len(merged)} local branches merged into origin/main:")
    for b in merged:
        print(f"  {b['name']} ({b['sha'][:8]})")

    print(f"\n[gone] {len(gone)} local branches with gone remote tracking:")
    for b in gone:
        print(f"  {b['name']} ({b['sha'][:8]})")

    print(f"\n[closed-task] {len(closed_task)} remote branches with paid+closed issues and merged PRs:")
    for rb in closed_task:
        print(f"  origin/{rb}")

    print(f"\n[idle-30d] {len(idle)} local branches idle >{IDLE_DAYS}d (report only — not auto-deleted):")
    for b in idle:
        print(f"  {b['name']} ({b['sha'][:8]}) last: {b['last_commit']}")

    # Unique stale local count (merged ∪ gone, deduped)
    merged_names = {b["name"] for b in merged}
    gone_names = {b["name"] for b in gone}
    stale_local_total = len(merged_names | gone_names)
    print(
        f"\nSUMMARY: merged={len(merged)} gone={len(gone)} "
        f"closed_task={len(closed_task)} idle_30d={len(idle)} "
        f"stale_local_total={stale_local_total}"
    )

    if not args.apply:
        print("\n[dry-run] No changes made. Use --apply to delete merged+gone branches.")
        return 0

    # ── Collect unique local deletions (merged ∪ gone) ────────────────────────
    timestamp = _now_iso()
    to_delete_local: dict[str, dict] = {}
    for b in merged:
        to_delete_local[b["name"]] = {**b, "category": "merged"}
    for b in gone:
        if b["name"] not in to_delete_local:
            to_delete_local[b["name"]] = {**b, "category": "gone"}

    # ── Build log entries (written BEFORE deletion) ───────────────────────────
    log_entries: list[dict] = [
        {
            "timestamp": timestamp,
            "sha": b["sha"],
            "branch": name,
            "category": b["category"],
            "action": "delete-local",
        }
        for name, b in to_delete_local.items()
    ]

    if args.aggressive:
        for rb in closed_task:
            r = _run(["git", "rev-parse", f"origin/{rb}"])
            sha = r.stdout.strip()[:8] if r.returncode == 0 else "unknown"
            log_entries.append({
                "timestamp": timestamp,
                "sha": sha,
                "branch": rb,
                "category": "closed-task",
                "action": "delete-remote",
            })

    if log_entries:
        _write_log(log_entries)
        print(f"\n[log] Wrote {len(log_entries)} entries to {LOG_PATH.relative_to(REPO_ROOT)}")

    # ── Delete local branches ─────────────────────────────────────────────────
    deleted_local = 0
    failed_local = 0
    for name in to_delete_local:
        r = _run(["git", "branch", "-D", name])
        if r.returncode == 0:
            print(f"  [ok] deleted local: {name}")
            deleted_local += 1
        else:
            print(f"  [fail] {name}: {r.stderr.strip()}")
            failed_local += 1

    # ── Delete remote branches (aggressive only) ──────────────────────────────
    deleted_remote = 0
    failed_remote = 0
    if args.aggressive:
        for rb in closed_task:
            r = _run(["git", "push", "origin", "--delete", rb])
            if r.returncode == 0:
                print(f"  [ok] deleted remote: origin/{rb}")
                deleted_remote += 1
            else:
                print(f"  [fail] origin/{rb}: {r.stderr.strip()}")
                failed_remote += 1

    print(
        f"\n[done] local: {deleted_local} deleted, {failed_local} failed"
        + (f" | remote: {deleted_remote} deleted, {failed_remote} failed" if args.aggressive else "")
    )

    return 0 if (failed_local + failed_remote) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
