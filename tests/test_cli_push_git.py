"""Regression tests for `wea push` git transport (src/wea_cli/push_git.py).

These use real local Git integration: a working repo pushing to a bare repo used
as the remote. Commit identities and SHAs must be preserved exactly.
"""

from __future__ import annotations

import base64
import subprocess
from pathlib import Path

import pytest

from wea_cli import push_git
from wea_cli.push_git import GitPushError


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return result.stdout.strip()


@pytest.fixture()
def repos(tmp_path: Path) -> tuple[Path, Path]:
    """Return (work, remote): a work repo with a bare `push-origin` remote."""
    remote = tmp_path / "remote.git"
    remote.mkdir()
    _git(remote, "init", "--bare", "--initial-branch=main")

    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "--initial-branch=main")
    _git(work, "config", "user.email", "claude-14@example.com")
    _git(work, "config", "user.name", "Claude-14")
    _git(work, "remote", "add", "push-origin", str(remote))
    (work / "README.md").write_text("base\n", encoding="utf-8")
    _git(work, "add", "README.md")
    _git(work, "commit", "-m", "base commit")
    return work, remote


def _remote_sha(remote: Path, branch: str) -> str | None:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(remote),
            "rev-parse",
            "--verify",
            "--quiet",
            f"refs/heads/{branch}",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    out = result.stdout.strip()
    return out or None


# --- redaction / auth construction -----------------------------------------


def test_redact_replaces_secret() -> None:
    assert push_git._redact("token=abc123 leaked", ("abc123",)) == "token=*** leaked"


def test_auth_config_encodes_token_without_url() -> None:
    config = push_git._auth_config("s3cr3t")
    assert config[0] == "-c"
    assert config[1].startswith("http.extraheader=AUTHORIZATION: basic ")
    encoded = config[1].split("basic ", 1)[1]
    assert base64.b64decode(encoded).decode() == "x-access-token:s3cr3t"


# --- new / fast-forward / idempotent / delete with exact SHAs ---------------


def test_push_creates_new_branch_with_exact_sha(repos: tuple[Path, Path]) -> None:
    work, remote = repos
    _git(work, "checkout", "-b", "feature/x")
    head = _git(work, "rev-parse", "HEAD")

    result = push_git.push_branch(work, token="", branch="feature/x")

    assert result["status"] == "created"
    assert result["head_sha"] == head
    assert result["remote"] == "push-origin"
    assert _remote_sha(remote, "feature/x") == head  # identity/SHA preserved


def test_push_fast_forward_then_idempotent(repos: tuple[Path, Path]) -> None:
    work, remote = repos
    _git(work, "checkout", "-b", "feature/x")
    push_git.push_branch(work, token="", branch="feature/x")

    (work / "next.txt").write_text("more\n", encoding="utf-8")
    _git(work, "add", "next.txt")
    _git(work, "commit", "-m", "second")
    head2 = _git(work, "rev-parse", "HEAD")

    updated = push_git.push_branch(work, token="", branch="feature/x")
    assert updated["status"] == "updated"
    assert updated["head_sha"] == head2
    assert _remote_sha(remote, "feature/x") == head2

    idempotent = push_git.push_branch(work, token="", branch="feature/x")
    assert idempotent["status"] == "up-to-date"
    assert idempotent["head_sha"] == head2


def test_push_delete_removes_branch(repos: tuple[Path, Path]) -> None:
    work, remote = repos
    _git(work, "checkout", "-b", "feature/x")
    head = _git(work, "rev-parse", "HEAD")
    push_git.push_branch(work, token="", branch="feature/x")
    assert _remote_sha(remote, "feature/x") == head

    deleted = push_git.push_branch(work, token="", branch="feature/x", delete=True)
    assert deleted["status"] == "deleted"
    assert deleted["previous_sha"] == head
    assert _remote_sha(remote, "feature/x") is None


def test_delete_missing_branch_rejected(repos: tuple[Path, Path]) -> None:
    work, _ = repos
    with pytest.raises(GitPushError, match="does not exist"):
        push_git.push_branch(work, token="", branch="ghost", delete=True)


# --- rejections -------------------------------------------------------------


def test_detached_head_rejected(repos: tuple[Path, Path]) -> None:
    work, _ = repos
    head = _git(work, "rev-parse", "HEAD")
    _git(work, "checkout", head)  # detached
    with pytest.raises(GitPushError, match="Detached HEAD"):
        push_git.push_branch(work, token="")


def test_dirty_working_tree_rejected(repos: tuple[Path, Path]) -> None:
    work, _ = repos
    _git(work, "checkout", "-b", "feature/x")
    (work / "README.md").write_text("dirty edit\n", encoding="utf-8")
    with pytest.raises(GitPushError, match="uncommitted changes"):
        push_git.push_branch(work, token="", branch="feature/x")


def test_main_publication_rejected(repos: tuple[Path, Path]) -> None:
    work, _ = repos
    with pytest.raises(GitPushError, match="protected branch"):
        push_git.push_branch(work, token="", branch="main")


def test_non_fast_forward_rejected(repos: tuple[Path, Path]) -> None:
    work, _remote = repos
    _git(work, "checkout", "-b", "feature/x")
    push_git.push_branch(work, token="", branch="feature/x")

    # Rewrite local history so remote is no longer an ancestor.
    _git(work, "commit", "--amend", "-m", "rewritten base")
    with pytest.raises(GitPushError, match="fast-forward"):
        push_git.push_branch(work, token="", branch="feature/x")


def test_unknown_remote_rejected(repos: tuple[Path, Path]) -> None:
    work, _ = repos
    _git(work, "checkout", "-b", "feature/x")
    with pytest.raises(GitPushError, match="not configured"):
        push_git.push_branch(work, token="", branch="feature/x", remote="nope")


def test_transport_failure_is_reported_and_redacted(
    repos: tuple[Path, Path], tmp_path: Path
) -> None:
    work, _ = repos
    _git(work, "remote", "add", "broken", str(tmp_path / "no-such-remote.git"))
    _git(work, "checkout", "-b", "feature/x")
    token = "supersecrettoken"
    with pytest.raises(GitPushError) as excinfo:
        push_git.push_branch(work, token=token, branch="feature/x", remote="broken")
    assert token not in str(excinfo.value)


def test_result_and_render_never_leak_token(repos: tuple[Path, Path]) -> None:
    work, _ = repos
    _git(work, "checkout", "-b", "feature/x")
    token = "leak-me-if-you-can"
    result = push_git.push_branch(work, token=token, branch="feature/x")
    rendered = push_git.render(result)
    assert token not in repr(result)
    assert token not in rendered
