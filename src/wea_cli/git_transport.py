"""Bounded Git operations; transport output can contain secrets and stays private."""

from __future__ import annotations

import base64
import os
import subprocess
from pathlib import Path


class TransportError(ValueError):
    """A Git precondition or transport failed without disclosing remote details."""


def git(root: Path, *args: str, operation: str = "Git operation") -> str:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    # A caller may have enabled traces containing credential-bearing URLs.
    for key in tuple(env):
        if key.startswith("GIT_TRACE") or key == "GIT_CURL_VERBOSE":
            del env[key]
    token = env.get("GH_TOKEN") or env.get("GITHUB_TOKEN")
    if token:
        # Git does not consume GH_TOKEN itself. Keep the credential out of argv,
        # persisted config and logs; apply it only to the GitHub HTTPS host.
        count = int(env.get("GIT_CONFIG_COUNT", "0"))
        encoded = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        for index, value in enumerate(("", f"AUTHORIZATION: basic {encoded}"), count):
            env[f"GIT_CONFIG_KEY_{index}"] = "http.https://github.com/.extraheader"
            env[f"GIT_CONFIG_VALUE_{index}"] = value
        env["GIT_CONFIG_COUNT"] = str(count + 2)
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "-c", "remote.push-origin.mirror=false", *args],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise TransportError(
            f"{operation} failed. Check Git, network access, remote configuration "
            "and authentication; then retry. Transport details are withheld."
        ) from exc
    return result.stdout.strip()


def canonical_commit(root: Path, ref: str) -> str:
    if not ref.startswith("origin/"):
        raise TransportError("Canonical ref must be origin/<branch>, e.g. origin/main.")
    branch = ref.removeprefix("origin/")
    git(root, "check-ref-format", f"refs/heads/{branch}", operation="Ref validation")
    target = f"refs/remotes/origin/{branch}"
    canonical = canonical_commit(root, "origin/main") if branch != "main" else None
    git(
        root,
        "fetch",
        "--no-tags",
        "origin",
        f"+refs/heads/{branch}:{target}",
        operation="Canonical fetch",
    )
    commit = git(
        root,
        "rev-parse",
        "--verify",
        f"{target}^{{commit}}",
        operation="Canonical ref verification",
    )
    fetched = git(
        root,
        "rev-parse",
        "--verify",
        "FETCH_HEAD^{commit}",
        operation="Fetched commit verification",
    )
    if commit != fetched:
        raise TransportError("Canonical ref changed during fetch; retry report.")
    if canonical is not None and commit != canonical:
        raise TransportError(
            "Configured ref is not current canonical origin/main; "
            "use --ref origin/main."
        )
    return commit


def push_branch(root: Path, branch: str | None = None) -> dict[str, str]:
    current = git(
        root,
        "symbolic-ref",
        "--quiet",
        "--short",
        "HEAD",
        operation="Branch lookup (detached HEAD is unsupported)",
    )
    if branch is not None and branch != current:
        raise TransportError(
            "Push only the checked-out branch; switch worktrees first."
        )
    if current in {"main", "master"}:
        raise TransportError("Main publication is prohibited; use a feature branch PR.")
    if git(root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise TransportError(
            "Working tree is dirty; commit or stash intended changes first."
        )
    ref = f"refs/heads/{current}"
    head = git(root, "rev-parse", "--verify", "HEAD^{commit}")
    urls = git(
        root,
        "remote",
        "get-url",
        "--push",
        "--all",
        "push-origin",
        operation="push-origin configuration",
    ).splitlines()
    if len(urls) != 1:
        raise TransportError(
            "Configure exactly one push-origin push URL before publishing."
        )
    # Use the effective push URL for reads too: fetch and push URLs may differ.
    url = urls[0]
    before = git(
        root, "ls-remote", "--refs", url, ref, operation="Remote branch lookup"
    )
    old = before.split()[0] if before else None
    if old and old != head:
        git(root, "fetch", "--no-tags", url, ref, operation="Remote ancestry fetch")
        git(
            root,
            "merge-base",
            "--is-ancestor",
            old,
            head,
            operation="Fast-forward check (non-fast-forward update rejected)",
        )
    if old != head:
        git(
            root,
            "push",
            "--porcelain",
            "--no-follow-tags",
            "--recurse-submodules=no",
            "push-origin",
            f"{head}:{ref}",
            operation="Branch push",
        )
    after = git(
        root, "ls-remote", "--refs", url, ref, operation="Published SHA verification"
    )
    if not after or after.split()[0] != head:
        raise TransportError(
            "Remote SHA differs from intended HEAD; inspect branch before retry."
        )
    return {
        "remote": "push-origin",
        "branch": current,
        "ref": ref,
        "head": head,
        "status": "unchanged" if old == head else "updated" if old else "created",
    }
