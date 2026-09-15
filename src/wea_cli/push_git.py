"""`wea push` — publish the current branch through authenticated Git transport.

This replaces the earlier per-blob GitHub REST reconstruction (which re-uploaded
every tree and blob and could not preserve packed history efficiently). Native
``git push`` preserves original commit identities and SHAs, transfers only the
delta, and supports new, fast-forward, and idempotent branch updates.

Safety properties enforced here:

- Publication always targets the *current checked-out branch* resolved from the
  full ``refs/heads/...`` symbolic ref (never an abbreviated ref, which a
  same-named tag/branch collision could corrupt). An explicit branch argument
  must match the current branch.
- Detached HEAD, a dirty working tree, non-fast-forward updates, and
  ``main``/``master`` publication are refused.
- Exactly one effective *push* destination URL is resolved (honouring a separate
  ``pushurl``); it is used for the push and the readback so the inspected and
  written destinations cannot diverge. Multiple push URLs are refused.
- The transport is explicitly bounded: single refspec, ``--atomic``, no tag
  following, no submodule recursion. Pushing by URL ignores ``remote.<n>.mirror``
  and ``remote.<n>.push`` config.
- The HTTPS credential is injected through per-invocation ``GIT_CONFIG_*``
  environment scoped to the exact URL, so it never appears in argv; the token and
  its encoded header are redacted from every error surface.

No dependency on the vNext protocol package: this stays outside the writer
surface guarded by ``tests/vnext/test_runtime_boundary``.
"""

from __future__ import annotations

import base64
import os
import re
import subprocess
from pathlib import Path
from typing import Any

# Matches userinfo credentials embedded in a URL: scheme://user[:pass]@host
_URL_CREDENTIALS_RE = re.compile(r"([a-zA-Z][\w+.-]*://)[^/@\s]+@")

# Branch names that `wea push` refuses to publish. Publishing the canonical
# integration branch needs an explicitly protected path this task does not add.
PROTECTED_BRANCHES = frozenset({"main", "master"})

# Preferred configured push remote, falling back to origin when absent.
PREFERRED_REMOTES = ("push-origin", "origin")

_HEADS_PREFIX = "refs/heads/"


class GitPushError(Exception):
    """Raised when a bounded git push cannot complete safely."""


def _strip_url_credentials(text: str) -> str:
    """Redact any ``scheme://user:pass@`` credentials embedded in a URL."""
    return _URL_CREDENTIALS_RE.sub(r"\1***@", text)


def _redact(text: str, secrets: tuple[str, ...]) -> str:
    result = text
    for secret in secrets:
        if secret:
            result = result.replace(secret, "***")
    # Also strip credentials embedded in any URL (e.g. a configured pushurl),
    # which can appear in argv-derived diagnostics, not just stderr.
    return _strip_url_credentials(result)


def _run_git(
    root: Path,
    args: list[str],
    *,
    config: list[str] | None = None,
    env: dict[str, str] | None = None,
    secrets: tuple[str, ...] = (),
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run git with cwd=root, redacting secrets from any error surface.

    ``config`` holds non-secret ``-c key=value`` pairs inserted before the
    subcommand. Secrets are injected only through ``env`` (never argv).
    """
    command = ["git", "-C", str(root), *(config or []), *args]
    run_env = None
    if env is not None:
        run_env = os.environ.copy()
        run_env.update(env)
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            env=run_env,
        )
    except FileNotFoundError as exc:  # pragma: no cover - environment dependent
        raise GitPushError(
            "`git` CLI not found. Install Git to use `wea push`."
        ) from exc
    if check and completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        # Report only the subcommand (args), never -c config or env auth. Redact
        # the complete diagnostic (args may carry a credential-bearing push URL),
        # not just stderr.
        message = f"`git {' '.join(args)}` failed: {stderr or 'unknown error'}"
        raise GitPushError(_redact(message, secrets))
    return completed


def _basic_header(token: str) -> str:
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode("ascii")
    return f"AUTHORIZATION: basic {basic}"


def _auth_env(url: str, header: str) -> dict[str, str]:
    """Scope an Authorization header to exactly ``url`` via GIT_CONFIG_* env.

    Keeping the credential in the environment (not argv) means it never appears
    in a process listing or an error message built from the command line.
    """
    return {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": f"http.{url}.extraheader",
        "GIT_CONFIG_VALUE_0": header,
    }


# Non-secret transport bounds applied to every push.
_PUSH_BOUNDS = ["-c", "push.followTags=false", "-c", "push.recurseSubmodules=no"]
_PUSH_FLAGS = ["--atomic", "--no-follow-tags", "--recurse-submodules=no"]


def current_branch(root: Path) -> str | None:
    """Return the checked-out branch, or ``None`` when HEAD is detached.

    Uses the full ``refs/heads/...`` symbolic ref and strips the prefix exactly
    once, so a branch literally named ``heads/feature`` (which ``--short`` would
    render ambiguously against a same-named tag) is handled correctly.
    """
    completed = _run_git(root, ["symbolic-ref", "--quiet", "HEAD"], check=False)
    if completed.returncode != 0:
        return None
    ref = completed.stdout.strip()
    if not ref.startswith(_HEADS_PREFIX):
        return None
    return ref[len(_HEADS_PREFIX) :]


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


def _rewrite_prefixes(root: Path) -> list[str]:
    """Return the FROM prefixes of any url.*.insteadOf / pushInsteadOf rules."""
    completed = _run_git(
        root,
        ["config", "--get-regexp", r"^url\..*\.(insteadof|pushinsteadof)$"],
        check=False,
    )
    prefixes: list[str] = []
    for line in completed.stdout.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[1].strip():
            prefixes.append(parts[1].strip())
    return prefixes


def effective_push_url(root: Path, remote: str) -> str:
    """Resolve exactly one effective push URL used for both push and readback.

    ``git remote get-url --push`` already applies ``insteadOf``/``pushInsteadOf``
    rewrites; passing the result back to ``git push``/``ls-remote`` would apply a
    matching rule a second time, sending traffic to a different repository than
    the one inspected. If any configured rewrite prefix still matches the
    resolved URL, refuse rather than publish to an ambiguous destination.
    """
    completed = _run_git(root, ["remote", "get-url", "--push", "--all", remote])
    urls = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if not urls:
        raise GitPushError(f"Remote `{remote}` has no push URL configured.")
    if len(urls) > 1:
        raise GitPushError(
            f"Remote `{remote}` has multiple push URLs; refusing an unbounded push. "
            "Configure a single push destination."
        )
    url = urls[0]
    for prefix in _rewrite_prefixes(root):
        if url.startswith(prefix):
            raise GitPushError(
                "A configured url.*.insteadOf/pushInsteadOf rule would rewrite the "
                "resolved push destination a second time; refusing an ambiguous "
                "push. Point the remote at a direct URL."
            )
    return url


def _head_sha(root: Path) -> str:
    return _run_git(root, ["rev-parse", "--verify", "HEAD"]).stdout.strip()


def _remote_sha(
    root: Path,
    url: str,
    branch: str,
    *,
    env: dict[str, str] | None,
    secrets: tuple[str, ...],
) -> str | None:
    target = f"{_HEADS_PREFIX}{branch}"
    completed = _run_git(
        root,
        ["ls-remote", "--heads", url, target],
        env=env,
        secrets=secrets,
    )
    # `git ls-remote` matches ref-name suffixes, so a branch like
    # `sub/feature/x` also answers a query for `feature/x`. Accept only the row
    # whose ref name is exactly the requested branch; otherwise the branch is
    # absent.
    for line in completed.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == target:
            return parts[0]
    return None


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


def _auth_material(
    url: str, token: str
) -> tuple[dict[str, str] | None, tuple[str, ...]]:
    """Return (auth_env, secrets) for an HTTPS url; empty for other transports."""
    if not url.startswith("https://"):
        return None, ()
    if not token:
        raise GitPushError("An authenticated token is required for HTTPS `wea push`.")
    header = _basic_header(token)
    return _auth_env(url, header), (token, header)


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
    url = effective_push_url(root, remote_name)
    env, secrets = _auth_material(url, token)

    if delete:
        if branch is None:
            raise GitPushError("Deletion requires an explicit branch name.")
        if branch in PROTECTED_BRANCHES and not allow_protected:
            raise GitPushError(
                f"Refusing to delete protected branch `{branch}` on `{remote_name}`."
            )
        existing = _remote_sha(root, url, branch, env=env, secrets=secrets)
        if existing is None:
            raise GitPushError(
                f"Remote branch `{branch}` does not exist on `{remote_name}`."
            )
        _run_git(
            root,
            ["push", *_PUSH_FLAGS, url, f":{_HEADS_PREFIX}{branch}"],
            config=_PUSH_BOUNDS,
            env=env,
            secrets=secrets,
        )
        if _remote_sha(root, url, branch, env=env, secrets=secrets) is not None:
            raise GitPushError(f"Remote branch `{branch}` still present after delete.")
        return {
            "remote": remote_name,
            "branch": branch,
            "remote_ref": f"{_HEADS_PREFIX}{branch}",
            "head_sha": None,
            "previous_sha": existing,
            "status": "deleted",
        }

    # Publication targets the current checked-out branch only.
    branch_name = current_branch(root)
    if branch_name is None:
        raise GitPushError(
            "Detached HEAD: check out the branch you intend to publish before "
            "`wea push`."
        )
    if branch is not None and branch != branch_name:
        raise GitPushError(
            f"`wea push` publishes the current branch `{branch_name}`; refusing to "
            f"publish a different branch `{branch}`. Check it out first."
        )
    if branch_name in PROTECTED_BRANCHES and not allow_protected:
        raise GitPushError(
            f"Refusing to publish protected branch `{branch_name}`. "
            "This command does not add a main publication path."
        )
    if working_tree_dirty(root):
        raise GitPushError(
            "Working tree has uncommitted changes; commit or stash before pushing "
            f"`{branch_name}` to avoid publishing an ambiguous state."
        )

    head_sha = _head_sha(root)
    remote_sha = _remote_sha(root, url, branch_name, env=env, secrets=secrets)
    if remote_sha == head_sha:
        return {
            "remote": remote_name,
            "branch": branch_name,
            "remote_ref": f"{_HEADS_PREFIX}{branch_name}",
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
        ["push", *_PUSH_FLAGS, url, f"{head_sha}:{_HEADS_PREFIX}{branch_name}"],
        config=_PUSH_BOUNDS,
        env=env,
        secrets=secrets,
    )

    published = _remote_sha(root, url, branch_name, env=env, secrets=secrets)
    if published != head_sha:
        raise GitPushError(
            f"Post-push verification failed: remote head is {published}, expected "
            f"{head_sha}."
        )
    return {
        "remote": remote_name,
        "branch": branch_name,
        "remote_ref": f"{_HEADS_PREFIX}{branch_name}",
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
