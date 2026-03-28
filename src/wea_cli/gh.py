"""Thin wrappers around GitHub CLI calls."""

from __future__ import annotations

import json
import subprocess
from typing import Any

from wea_cli.issue_edit import IssueEditError
from wea_cli.issue_edit import safe_edit_issue_labels as _safe_edit_issue_labels

DEFAULT_REPO = "WeTheAgents/wetheagents"


class GhError(RuntimeError):
    """Raised when `gh` command fails or returns invalid output."""


def run_gh_json(args: list[str]) -> Any:
    command = ["gh", *args]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
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
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
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


def view_issue_comments(issue: int, repo: str = DEFAULT_REPO) -> dict[str, Any]:
    payload = run_gh_json(
        [
            "issue",
            "view",
            str(issue),
            "--repo",
            repo,
            "--comments",
            "--json",
            "number,title,comments",
        ]
    )
    return payload if isinstance(payload, dict) else {}

def view_pr(pr_number: int, repo: str = DEFAULT_REPO) -> dict[str, Any]:
    payload = run_gh_json(
        [
            "pr",
            "view",
            str(pr_number),
            "--repo",
            repo,
            "--json",
            "number,title,state,author,url,isDraft",
        ]
    )
    return payload if isinstance(payload, dict) else {}

def post_issue_comment(issue: int, body: str, repo: str = DEFAULT_REPO) -> None:
    payload = run_gh_json(
        [
            "pr",
            "view",
            str(pr_number),
            "--repo",
            repo,
            "--json",
            "number,title,state,author,url,isDraft",
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


def create_pull_request(
    *,
    title: str,
    body: str,
    head: str,
    base: str = "main",
    repo: str = DEFAULT_REPO,
) -> str:
    """Create a pull request. Returns the PR URL."""
    args = [
        "pr", "create",
        "--repo", repo,
        "--title", title,
        "--body", body,
        "--head", head,
        "--base", base,
    ]
    return run_gh_text(args).strip()


def search_issues_with_comments(
    *,
    repo: str = DEFAULT_REPO,
    query: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Search issues with comments in one GraphQL call."""
    if limit < 1:
        return []

    search_query = f"repo:{repo} is:issue {query}".strip()
    gql = """
query($q: String!, $n: Int!) {
  search(type: ISSUE, query: $q, first: $n) {
    nodes {
      ... on Issue {
        number
        title
        body
        state
        url
        labels(first: 20) {
          nodes {
            name
          }
        }
        comments(last: 100) {
          nodes {
            body
            createdAt
            url
            author {
              login
            }
          }
        }
      }
    }
  }
}
""".strip()

    payload = run_gh_json(
        [
            "api",
            "graphql",
            "-f",
            f"query={gql}",
            "-f",
            f"q={search_query}",
            "-F",
            f"n={limit}",
        ]
    )
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    search = data.get("search")
    if not isinstance(search, dict):
        return []

    nodes = search.get("nodes")
    if not isinstance(nodes, list):
        return []
    return [node for node in nodes if isinstance(node, dict)]


def grant_repo_access(
    github_username: str,
    permission: str = "write",
    repo: str = DEFAULT_REPO,
) -> dict[str, Any]:
    """Add a GitHub user as an outside collaborator with the given permission."""
    payload = run_gh_json([
        "api",
        f"repos/{repo}/collaborators/{github_username}",
        "-X", "PUT",
        "-f", f"permission={permission}",
    ])
    return payload if isinstance(payload, dict) else {}


def check_repo_access(
    github_username: str,
    repo: str = DEFAULT_REPO,
) -> dict[str, str]:
    """Check a user's permission level on the repo."""
    payload = run_gh_json([
        "api",
        f"repos/{repo}/collaborators/{github_username}/permission",
        "--jq", ".permission",
    ])
    # gh --jq returns a plain string, parsed as JSON it's just a string
    if isinstance(payload, str):
        return {"permission": payload}
    return {"permission": "none"}


def _issue_label_names(issue_payload: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    labels = issue_payload.get("labels", [])
    if not isinstance(labels, list):
        return names
    for label in labels:
        if not isinstance(label, dict):
            continue
        name = str(label.get("name", "")).strip()
        if name:
            names.add(name)
    return names


def edit_issue_labels(
    issue: int,
    *,
    labels: list[str],
    repo: str = DEFAULT_REPO,
) -> None:
    """Set issue labels to the exact provided list."""
    current = _issue_label_names(view_issue(issue, repo=repo))
    target = {label.strip() for label in labels if label.strip()}

    to_add = sorted(target - current)
    to_remove = sorted(current - target)
    if not to_add and not to_remove:
        return

    args = ["issue", "edit", str(issue), "--repo", repo]
    for label in to_add:
        args.extend(["--add-label", label])
    for label in to_remove:
        args.extend(["--remove-label", label])
    run_gh_text(args)


def set_issue_state(
    issue: int,
    state: str,
    *,
    repo: str = DEFAULT_REPO,
) -> None:
    normalized = state.strip().upper()
    if normalized == "OPEN":
        run_gh_text(["issue", "reopen", str(issue), "--repo", repo])
        return
    if normalized == "CLOSED":
        run_gh_text(["issue", "close", str(issue), "--repo", repo])
        return
    raise GhError(f"Unsupported issue state: {state!r}")


def safe_issue_label_edit(
    issue: int,
    *,
    add_labels: list[str] | None = None,
    remove_labels: list[str] | None = None,
    swaps: list[tuple[str, str]] | None = None,
    repo: str = DEFAULT_REPO,
) -> dict[str, Any]:
    """Apply add/remove/swap label operations with state-flip rollback."""

    def _get_issue(issue_number: int) -> dict[str, Any]:
        return view_issue(issue_number, repo=repo)

    def _set_labels(issue_number: int, labels: list[str]) -> None:
        edit_issue_labels(issue_number, labels=labels, repo=repo)

    def _set_state(issue_number: int, state: str) -> None:
        set_issue_state(issue_number, state, repo=repo)

    try:
        return _safe_edit_issue_labels(
            issue,
            add_labels=add_labels,
            remove_labels=remove_labels,
            swaps=swaps,
            get_issue=_get_issue,
            set_labels=_set_labels,
            set_state=_set_state,
        )
    except IssueEditError as exc:
        raise GhError(str(exc)) from exc
