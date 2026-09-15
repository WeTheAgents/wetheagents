"""`wea push` — publish a branch through authenticated Git transport.

This replaces the earlier per-blob GitHub REST reconstruction (which re-uploaded
every tree and blob and could not preserve packed history efficiently). Native
``git push`` preserves original commit identities and SHAs, transfers only the
delta, and supports new, fast-forward, and idempotent branch updates.

Authentication is injected with a one-shot ``http.extraheader`` config so the
token never appears in a remote URL, argv-visible refspec, or any printed error.

No dependency on the vNext protocol package: this stays outside the writer
surface guarded by ``tests/vnext/test_runtime_boundary``.
"""

from __future__ import annotations

import base64
import subprocess
from pathlib import Path
from typing import Any

# Branch names that `wea push` refuses to publish. Publishing the canonical
# integration branch needs an explicitly protected path this task does not add.
PROTECTED_BRANCHES = frozenset({"main", "master"})

# Preferred configured push remote, falling back to origin when absent.
PREFERRED_REMOTES = ("push-origin", "origin")


class GitPushError(Exception):
    """Raised when a bounded git push cannot complete safely."""


def _redact(text: str, secrets: tuple[str, ...]) -> str:
    result = text
    for secret in secrets:
        if secret:
            result = result.replace(secret, "***")
    return result


def _run_git(
    root: Path,
    args: list[str],
    *,
    config: list[str] | None = None,
    secrets: tuple[str, ...] = (),
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run git with cwd=root, redacting secrets from any error surface.

    ``config`` holds ``-c key=value`` pairs inserted before the subcommand; they
    are never included in raised error text so authentication headers cannot leak.
    """
    command = ["git", "-C", str(root), *(config or []), *args]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except FileNotFoundError as exc:  # pragma: no cover - environment dependent
        raise GitPushError(
            "`git` CLI not found. Install Git to use `wea push`."
        ) from exc
    if check and completed.returncode != 0:
        stderr = _redact((completed.stderr or "").strip(), secrets)
        # Report only the subcommand (args), never the -c auth config.
        safe_args = " ".join(args)
        raise GitPushError(f"`git {safe_args}` failed: {stderr or 'unknown error'}")
    return completed


def _auth_config(token: str) -> list[str]:
    """Build a one-shot Authorization header config for HTTPS git transport."""
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode("ascii")
    return ["-c", f"http.extraheader=AUTHORIZATION: basic {basic}"]


def current_branch(root: Path) -> str | None:
    """Return the checked-out branch, or ``None`` when HEAD is detached."""
    completed = _run_git(
        root, ["symbolic-ref", "--quiet", "--short", "HEAD"], check=False
    )
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def working_tree_dirty(root: Path) -> bool:
    completed = _run_git(root, ["status", "--porcelain"])
    return bool(completed.stdout.strip())


def resolve_remote(root: Path, remote: str | None) -> str:
    """Resolve the push remote name, preferring the configured push remote."""
    listed = {
        line.strip()
        for line in _run_git(root, ["remote"]).stdout.splitlines()
        if line.strip()
    }
    if remote:
        if remote not in listed:
            raise GitPushError(f"Git remote `{remote}` is not configured.")
        return remote
    for candidate in PREFERRED_REMOTES:
        if candidate in listed:
            return candidate
    raise GitPushError(
        "No push remote configured. Expected one of: " + ", ".join(PREFERRED_REMOTES)
    )


def remote_url(root: Path, remote: str) -> str:
    return _run_git(root, ["remote", "get-url", remote]).stdout.strip()


def _resolve_branch(root: Path, branch: str | None) -> tuple[str, str]:
    if branch:
        ref = f"refs/heads/{branch}"
        completed = _run_git(
            root, ["rev-parse", "--verify", "--quiet", ref], check=False
        )
        head = completed.stdout.strip()
        if completed.returncode != 0 or not head:
            raise GitPushError(f"Local branch `{branch}` does not exist.")
        return branch, head
    name = current_branch(root)
    if not name:
        raise GitPushError(
            "Detached HEAD: pass an explicit branch name to `wea push <branch>`."
        )
    head = _run_git(root, ["rev-parse", "--verify", "HEAD"]).stdout.strip()
    return name, head


def _remote_sha(
    root: Path, remote: str, branch: str, config: list[str], secrets: tuple[str, ...]
) -> str | None:
    completed = _run_git(
        root,
        ["ls-remote", "--heads", remote, f"refs/heads/{branch}"],
        config=config,
        secrets=secrets,
    )
    line = completed.stdout.strip()
    if not line:
        return None
    return line.split()[0]


def _is_ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    completed = _run_git(
        root,
        ["merge-base", "--is-ancestor", ancestor, descendant],
        check=False,
    )
    if completed.returncode in (0, 1):
        return completed.returncode == 0
    stderr = (completed.stderr or "").strip()
    raise GitPushError(
        f"`git merge-base --is-ancestor` failed: {stderr or 'unknown error'}"
    )


def push_branch(
    root: Path,
    *,
    token: str,
    branch: str | None = None,
    remote: str | None = None,
    delete: bool = False,
    allow_protected: bool = False,
) -> dict[str, Any]:
    """Publish (or delete) a single branch through authenticated git transport.

    Returns a result dict with the resolved remote, branch, head SHA, and status.
    Never prints or returns the token or a token-bearing remote URL.
    """
    remote_name = resolve_remote(root, remote)
    url = remote_url(root, remote_name)

    # HTTPS transports authenticate with a one-shot Authorization header so the
    # token never lands in a remote URL or an argv-visible refspec. Local/file
    # or ssh remotes rely on ambient credentials and need no injected token.
    use_auth = url.startswith("https://")
    if use_auth and not token:
        raise GitPushError("An authenticated token is required for HTTPS `wea push`.")
    config = _auth_config(token) if use_auth else []
    secrets = (token,) if token else ()

    if delete:
        if branch is None:
            raise GitPushError("Deletion requires an explicit branch name.")
        if branch in PROTECTED_BRANCHES and not allow_protected:
            raise GitPushError(
                f"Refusing to delete protected branch `{branch}` on `{remote_name}`."
            )
        existing = _remote_sha(root, remote_name, branch, config, secrets)
        if existing is None:
            raise GitPushError(
                f"Remote branch `{branch}` does not exist on `{remote_name}`."
            )
        _run_git(
            root,
            ["push", remote_name, f":refs/heads/{branch}"],
            config=config,
            secrets=secrets,
        )
        if _remote_sha(root, remote_name, branch, config, secrets) is not None:
            raise GitPushError(f"Remote branch `{branch}` still present after delete.")
        return {
            "remote": remote_name,
            "branch": branch,
            "remote_ref": f"refs/heads/{branch}",
            "head_sha": None,
            "previous_sha": existing,
            "status": "deleted",
        }

    branch_name, head_sha = _resolve_branch(root, branch)

    if branch_name in PROTECTED_BRANCHES and not allow_protected:
        raise GitPushError(
            f"Refusing to publish protected branch `{branch_name}`. "
            "This command does not add a main publication path."
        )

    # Dirty ambiguity: only meaningful when publishing the checked-out branch,
    # where uncommitted changes make "the current branch delta" ambiguous.
    if branch is None or branch_name == current_branch(root):
        if working_tree_dirty(root):
            raise GitPushError(
                "Working tree has uncommitted changes; commit or stash before pushing "
                f"`{branch_name}` to avoid publishing an ambiguous state."
            )

    remote_sha = _remote_sha(root, remote_name, branch_name, config, secrets)
    if remote_sha == head_sha:
        return {
            "remote": remote_name,
            "branch": branch_name,
            "remote_ref": f"refs/heads/{branch_name}",
            "head_sha": head_sha,
            "previous_sha": remote_sha,
            "status": "up-to-date",
        }
    if remote_sha is not None and not _is_ancestor(root, remote_sha, head_sha):
        raise GitPushError(
            f"Remote `{remote_name}/{branch_name}` ({remote_sha}) is not an "
            f"ancestor of local {head_sha}; `wea push` only performs "
            "fast-forward updates."
        )

    _run_git(
        root,
        ["push", remote_name, f"{head_sha}:refs/heads/{branch_name}"],
        config=config,
        secrets=secrets,
    )

    published = _remote_sha(root, remote_name, branch_name, config, secrets)
    if published != head_sha:
        raise GitPushError(
            f"Post-push verification failed: remote head is {published}, expected "
            f"{head_sha}."
        )
    return {
        "remote": remote_name,
        "branch": branch_name,
        "remote_ref": f"refs/heads/{branch_name}",
        "head_sha": head_sha,
        "previous_sha": remote_sha,
        "status": "created" if remote_sha is None else "updated",
    }


def render(result: dict[str, Any]) -> str:
    status = result["status"]
    remote = result["remote"]
    branch = result["branch"]
    if status == "deleted":
        return f"Deleted {remote}:{branch} (was {result['previous_sha']})."
    if status == "up-to-date":
        return f"{remote}:{branch} already up to date at {result['head_sha']}."
    verb = "Created" if status == "created" else "Updated"
    return f"{verb} {remote}:{branch} at {result['head_sha']}."
