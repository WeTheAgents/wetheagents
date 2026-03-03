"""Thin wrappers around GitHub CLI calls."""

from __future__ import annotations

import json
import subprocess
from typing import Any

DEFAULT_REPO = "WeTheAgents/wetheagents"


class GhError(RuntimeError):
    """Raised when `gh` command fails or returns invalid output."""


def run_gh_json(args: list[str]) -> Any:
    command = ["gh", *args]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True)
    except FileNotFoundError as exc:
        raise GhError("`gh` CLI not found. Install GitHub CLI and authenticate.") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        raise GhError(f"`gh {' '.join(args)}` failed: {stderr or 'unknown error'}") from exc

    try:
        return json.loads(result.stdout or "null")
    except json.JSONDecodeError as exc:
        raise GhError("Invalid JSON from `gh` output.") from exc


def run_gh_text(args: list[str]) -> str:
    command = ["gh", *args]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True)
    except FileNotFoundError as exc:
        raise GhError("`gh` CLI not found. Install GitHub CLI and authenticate.") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        raise GhError(f"`gh {' '.join(args)}` failed: {stderr or 'unknown error'}") from exc
    return result.stdout


def list_open_tasks(repo: str = DEFAULT_REPO) -> list[dict[str, Any]]:
    payload = run_gh_json(
        [
            "issue",
            "list",
            "--repo",
            repo,
            "--state",
            "open",
            "--label",
            "task",
            "--limit",
            "200",
            "--json",
            "number,title,body,url,labels",
        ]
    )
    return payload if isinstance(payload, list) else []


def view_issue(issue: int, repo: str = DEFAULT_REPO) -> dict[str, Any]:
    payload = run_gh_json(
        [
            "issue",
            "view",
            str(issue),
            "--repo",
            repo,
            "--json",
            "number,title,body,url,state,author,labels",
        ]
    )
    return payload if isinstance(payload, dict) else {}


def post_issue_comment(issue: int, body: str, repo: str = DEFAULT_REPO) -> None:
    run_gh_text(["issue", "comment", str(issue), "--repo", repo, "--body", body])


def create_issue(
    title: str,
    body: str,
    labels: list[str] | None = None,
    repo: str = DEFAULT_REPO,
) -> str:
    """Create a GitHub issue. Returns the issue URL."""
    args = ["issue", "create", "--repo", repo, "--title", title, "--body", body]
    for label in labels or []:
        args.extend(["--label", label])
    return run_gh_text(args).strip()
def list_issue_comments(issue: int, repo: str = DEFAULT_REPO) -> list[dict[str, Any]]:
    payload = run_gh_json(
        [
            "issue",
            "view",
            str(issue),
            "--repo",
            repo,
            "--comments",
            "--json",
            "comments",
        ]
    )
    if isinstance(payload, dict) and "comments" in payload:
        comments = payload["comments"]
        return comments if isinstance(comments, list) else []
    return []
