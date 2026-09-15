"""Bounded Git operations with diagnostics that never echo transport secrets."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .errors import WeaCliError


class GitTransportError(WeaCliError):
    """A Git operation could not establish its required result."""


def run(root: Path, *args: str, operation: str = "Git operation") -> str:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            env=env,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitTransportError(
            f"{operation} could not run or timed out. Check Git and authentication; "
            "retry after inspecting the remote branch."
        ) from exc
    if result.returncode:
        # Git stderr can contain URLs, credential-helper output, or server secrets.
        raise GitTransportError(
            f"{operation} failed (Git exit {result.returncode}). "
            "Check repository access, configured authentication and remote history. "
            "Fetch and reconcile divergent commits before retrying; do not force push."
        )
    return result.stdout.strip()


def fetch_canonical(root: Path, ref: str) -> str:
    if ref != "origin/main":
        raise GitTransportError(
            "Use origin/main for current canonical state. "
            "Candidate and other refs are unsupported."
        )
    branch = ref.removeprefix("origin/")
    run(
        root,
        "check-ref-format",
        f"refs/heads/{branch}",
        operation="Canonical ref validation",
    )
    destination = f"refs/remotes/origin/{branch}"
    run(
        root,
        "fetch",
        "--no-tags",
        "--no-write-fetch-head",
        "origin",
        f"+refs/heads/{branch}:{destination}",
        operation="Canonical fetch (no cached fallback)",
    )
    return run(
        root,
        "rev-parse",
        "--verify",
        f"{destination}^{{commit}}",
        operation="Fetched canonical commit verification",
    )


def push_branch(root: Path, branch: str | None = None) -> dict[str, str]:
    target = run(
        root,
        "symbolic-ref",
        "--quiet",
        "HEAD",
        operation="Current branch lookup (detached HEAD is unsupported)",
    )
    if not target.startswith("refs/heads/"):
        raise GitTransportError(
            "HEAD must reference a local branch before publication."
        )
    current = target.removeprefix("refs/heads/")
    if current in {"main", "master"}:
        raise GitTransportError(
            "Protected branch publication is not supported by wea push."
        )
    if branch is not None and branch != current:
        raise GitTransportError(
            "Only the currently checked-out branch can be published."
        )
    if run(
        root,
        "status",
        "--porcelain",
        "--untracked-files=normal",
        "--ignore-submodules=none",
    ):
        raise GitTransportError(
            "Working tree is dirty. Commit intended changes before pushing."
        )
    remote = "push-origin"
    urls = run(
        root,
        "remote",
        "get-url",
        "--push",
        "--all",
        remote,
        operation="push-origin configuration lookup",
    ).splitlines()
    if len(urls) != 1:
        raise GitTransportError(
            "Configure exactly one authenticated push-origin destination."
        )
    # Refuse mirror mode: it can publish unrelated refs even with an explicit target.
    config = run(
        root,
        "config",
        "--type=bool",
        "--default=false",
        "--get",
        "remote.push-origin.mirror",
        operation="push-origin configuration validation",
    )
    if config == "true":
        raise GitTransportError(
            "Mirror push-origin is unsupported; configure a normal remote."
        )
    head = run(root, "rev-parse", "--verify", "HEAD^{commit}")
    run(
        root,
        "push",
        "--porcelain",
        "--no-follow-tags",
        "--recurse-submodules=no",
        remote,
        f"{head}:{target}",
        operation="Fast-forward branch publication",
    )
    observed = run(
        root,
        "ls-remote",
        "--exit-code",
        urls[0],
        target,
        operation="Published head verification",
    ).splitlines()
    # ls-remote patterns also match suffixes of nested refs.
    matching = [row.split() for row in observed if row.split()[1:] == [target]]
    if matching != [[head, target]]:
        raise GitTransportError(
            "Remote head changed during publication. Inspect it before retrying."
        )
    return {"remote": remote, "branch": current, "head": head}
