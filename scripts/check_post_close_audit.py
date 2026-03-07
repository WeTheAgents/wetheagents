#!/usr/bin/env python3
"""Audit recently closed tasks for post-close policy violations."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass
class AuditViolation:
    issue: int
    violation_type: str
    detail: str
    title: str


def _run_gh_json(args: list[str]) -> Any:
    result = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return json.loads(result.stdout or "null")


def _default_repo() -> str:
    return os.environ.get("GITHUB_REPOSITORY", "WeTheAgents/wetheagents")


def fetch_recently_closed_tasks(days: int, repo: str) -> list[dict[str, Any]]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    payload = _run_gh_json(
        [
            "issue",
            "list",
            "--repo",
            repo,
            "--state",
            "closed",
            "--label",
            "task",
            "--search",
            f"closed:>={since}",
            "--limit",
            "200",
            "--json",
            "number,title,url,labels,closedAt",
        ]
    )
    return payload if isinstance(payload, list) else []


def fetch_issue_timeline(issue: int, repo: str) -> list[dict[str, Any]]:
    payload = _run_gh_json(
        [
            "api",
            f"repos/{repo}/issues/{issue}/timeline",
        ]
    )
    return payload if isinstance(payload, list) else []


def fetch_pr_status(pr_number: int, repo: str) -> dict[str, Any]:
    payload = _run_gh_json(
        [
            "pr",
            "view",
            str(pr_number),
            "--repo",
            repo,
            "--json",
            "number,state,mergedAt,baseRefName,url",
        ]
    )
    return payload if isinstance(payload, dict) else {}


def fetch_open_follow_ups(issue: int, repo: str) -> list[dict[str, Any]]:
    payload = _run_gh_json(
        [
            "issue",
            "list",
            "--repo",
            repo,
            "--state",
            "open",
            "--search",
            f'"#{issue}"',
            "--limit",
            "100",
            "--json",
            "number,title,url",
        ]
    )
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict) and int(item.get("number", 0)) != issue]


def extract_linked_pr_numbers(timeline: list[dict[str, Any]]) -> list[int]:
    linked: set[int] = set()
    for event in timeline:
        if not isinstance(event, dict):
            continue
        source = event.get("source")
        if not isinstance(source, dict):
            continue
        issue_payload = source.get("issue")
        if not isinstance(issue_payload, dict):
            continue
        if "pull_request" not in issue_payload:
            continue
        number = issue_payload.get("number")
        if isinstance(number, int):
            linked.add(number)
    return sorted(linked)


def audit_issue(
    issue: dict[str, Any],
    *,
    repo: str,
    issue_timeline_fetcher=fetch_issue_timeline,
    pr_fetcher=fetch_pr_status,
    follow_up_fetcher=fetch_open_follow_ups,
) -> list[AuditViolation]:
    number = int(issue["number"])
    title = str(issue.get("title", "")).strip()
    labels = {
        str(label.get("name", "")).strip()
        for label in issue.get("labels", [])
        if isinstance(label, dict) and str(label.get("name", "")).strip()
    }
    violations: list[AuditViolation] = []

    if "paid" not in labels:
        violations.append(
            AuditViolation(number, "missing-paid-label", "closed task is missing `paid` label", title)
        )

    timeline = issue_timeline_fetcher(number, repo)
    for pr_number in extract_linked_pr_numbers(timeline):
        pr = pr_fetcher(pr_number, repo)
        merged_at = str(pr.get("mergedAt", "")).strip()
        base_ref = str(pr.get("baseRefName", "")).strip()
        if not merged_at:
            violations.append(
                AuditViolation(
                    number,
                    "linked-pr-not-merged",
                    f"linked PR #{pr_number} is not merged",
                    title,
                )
            )
            continue
        if base_ref and base_ref != "main":
            violations.append(
                AuditViolation(
                    number,
                    "linked-pr-not-main",
                    f"linked PR #{pr_number} merged into `{base_ref}`, not `main`",
                    title,
                )
            )

    follow_ups = follow_up_fetcher(number, repo)
    if follow_ups:
        refs = ", ".join(f"#{int(item['number'])}" for item in follow_ups)
        violations.append(
            AuditViolation(
                number,
                "open-follow-up",
                f"open follow-up issue(s) still reference this task: {refs}",
                title,
            )
        )

    return violations


def run_audit(
    *,
    days: int = 7,
    repo: str | None = None,
    issue_fetcher=fetch_recently_closed_tasks,
    issue_timeline_fetcher=fetch_issue_timeline,
    pr_fetcher=fetch_pr_status,
    follow_up_fetcher=fetch_open_follow_ups,
) -> list[AuditViolation]:
    repo_name = repo or _default_repo()
    issues = issue_fetcher(days, repo_name)
    violations: list[AuditViolation] = []
    for issue in issues:
        violations.extend(
            audit_issue(
                issue,
                repo=repo_name,
                issue_timeline_fetcher=issue_timeline_fetcher,
                pr_fetcher=pr_fetcher,
                follow_up_fetcher=follow_up_fetcher,
            )
        )
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit recently closed task issues")
    parser.add_argument("--days", type=int, default=7, help="Look back this many days (default: 7)")
    parser.add_argument("--root", default=None, help="Accepted for CLI consistency; unused by this audit")
    parser.add_argument("--repo", default=None, help="GitHub repo in owner/name format")
    args = parser.parse_args()

    violations = run_audit(days=args.days, repo=args.repo)
    if not violations:
        print(f"PASS: no closure violations found in the last {args.days} day(s)")
        return 0

    print(f"FAIL: found {len(violations)} closure violation(s)")
    for violation in violations:
        print(
            f"  - issue #{violation.issue} [{violation.violation_type}] "
            f"{violation.detail}"
        )
    return 1


if __name__ == "__main__":
    sys.exit(main())
