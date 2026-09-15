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


def test_basic_header_encodes_token() -> None:
    header = push_git._basic_header("s3cr3t")
    assert header.startswith("AUTHORIZATION: basic ")
    encoded = header.split("basic ", 1)[1]
    assert base64.b64decode(encoded).decode() == "x-access-token:s3cr3t"


def test_strip_url_credentials() -> None:
    assert (
        push_git._strip_url_credentials("https://user:secretpass@host/x.git")
        == "https://***@host/x.git"
    )
    assert (
        push_git._strip_url_credentials("ls-remote https://x-access-token:tok@h/r a")
        == "ls-remote https://***@h/r a"
    )


def test_redact_strips_embedded_url_credentials() -> None:
    msg = "`git push https://user:pw@example.com/x.git` failed: boom"
    out = push_git._redact(msg, ())
    assert "user:pw" not in out
    assert "***@example.com" in out


def test_auth_env_scopes_header_to_url_without_argv() -> None:
    header = push_git._basic_header("s3cr3t")
    env = push_git._auth_env("https://example.com/x.git", header)
    assert env["GIT_CONFIG_COUNT"] == "1"
    assert env["GIT_CONFIG_KEY_0"] == "http.https://example.com/x.git.extraheader"
    assert env["GIT_CONFIG_VALUE_0"] == header


def test_auth_material_only_for_https_and_redacts_header() -> None:
    # Non-HTTPS transport uses no injected credential.
    env, secrets = push_git._auth_material("/local/path.git", "tok")
    assert env is None and secrets == ()
    # HTTPS returns scoped env plus BOTH the token and its encoded header as
    # secrets so neither can leak through an error surface.
    env, secrets = push_git._auth_material("https://example.com/x.git", "tok")
    assert env is not None
    assert "tok" in secrets
    assert any(s.startswith("AUTHORIZATION: basic ") for s in secrets)


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


def test_push_error_does_not_leak_credential_bearing_url(
    repos: tuple[Path, Path],
) -> None:
    work, _ = repos
    # A pushurl carrying embedded credentials to an unreachable host.
    _git(work, "remote", "add", "creds", "https://fetch.invalid/x.git")
    _git(
        work,
        "remote",
        "set-url",
        "--push",
        "creds",
        "https://user:secretpass@nonexistent.invalid/x.git",
    )
    _git(work, "checkout", "-b", "feature/x")
    with pytest.raises(GitPushError) as excinfo:
        push_git.push_branch(work, token="tok", branch="feature/x", remote="creds")
    message = str(excinfo.value)
    assert "secretpass" not in message
    assert "user:secretpass" not in message


def test_result_and_render_never_leak_token(repos: tuple[Path, Path]) -> None:
    work, _ = repos
    _git(work, "checkout", "-b", "feature/x")
    token = "leak-me-if-you-can"
    result = push_git.push_branch(work, token=token, branch="feature/x")
    rendered = push_git.render(result)
    assert token not in repr(result)
    assert token not in rendered


# --- current-branch enforcement & ref-collision edge cases ------------------


def test_explicit_branch_must_match_current(repos: tuple[Path, Path]) -> None:
    work, _ = repos
    _git(work, "checkout", "-b", "feature/x")  # current branch
    _git(work, "branch", "feature/y")  # exists but not checked out
    with pytest.raises(GitPushError, match="current branch `feature/x`"):
        push_git.push_branch(work, token="", branch="feature/y")


def test_detached_head_rejected_even_with_explicit_branch(
    repos: tuple[Path, Path],
) -> None:
    work, _ = repos
    _git(work, "branch", "feature/x")
    head = _git(work, "rev-parse", "HEAD")
    _git(work, "checkout", head)  # detached
    with pytest.raises(GitPushError, match="Detached HEAD"):
        push_git.push_branch(work, token="", branch="feature/x")


def test_default_push_uses_current_branch(repos: tuple[Path, Path]) -> None:
    work, remote = repos
    _git(work, "checkout", "-b", "feature/x")
    head = _git(work, "rev-parse", "HEAD")
    result = push_git.push_branch(work, token="")  # no explicit branch
    assert result["branch"] == "feature/x"
    assert _remote_sha(remote, "feature/x") == head


def test_branch_named_like_ref_prefix_uses_full_ref(repos: tuple[Path, Path]) -> None:
    """A branch literally named `heads/feature` (collides with `--short`)."""
    work, remote = repos
    _git(work, "checkout", "-b", "heads/feature")
    head = _git(work, "rev-parse", "HEAD")
    # default form
    result = push_git.push_branch(work, token="")
    assert result["branch"] == "heads/feature"
    assert result["remote_ref"] == "refs/heads/heads/feature"
    assert _remote_sha(remote, "heads/feature") == head
    # explicit form must also resolve to the same full ref
    idempotent = push_git.push_branch(work, token="", branch="heads/feature")
    assert idempotent["status"] == "up-to-date"


def test_main_rejected_even_with_same_named_tag(repos: tuple[Path, Path]) -> None:
    work, remote = repos
    _git(work, "tag", "main")  # tag collides with branch name
    # current branch is main (fixture default); publishing it must be refused
    with pytest.raises(GitPushError, match="protected branch"):
        push_git.push_branch(work, token="")
    assert _remote_sha(remote, "main") is None  # nothing published


def test_effective_push_url_prefers_pushurl(tmp_path: Path) -> None:
    """Push and readback use the configured pushurl, not the fetch URL."""
    fetch_remote = tmp_path / "fetch.git"
    fetch_remote.mkdir()
    _git(fetch_remote, "init", "--bare", "--initial-branch=main")
    push_remote = tmp_path / "push.git"
    push_remote.mkdir()
    _git(push_remote, "init", "--bare", "--initial-branch=main")

    work = tmp_path / "w"
    work.mkdir()
    _git(work, "init", "--initial-branch=main")
    _git(work, "config", "user.email", "c@example.com")
    _git(work, "config", "user.name", "C")
    _git(work, "remote", "add", "push-origin", str(fetch_remote))
    _git(work, "remote", "set-url", "--push", "push-origin", str(push_remote))
    (work / "f.txt").write_text("x\n", encoding="utf-8")
    _git(work, "add", "f.txt")
    _git(work, "commit", "-m", "c1")
    _git(work, "checkout", "-b", "feature/z")
    head = _git(work, "rev-parse", "HEAD")

    assert push_git.effective_push_url(work, "push-origin") == str(push_remote)
    result = push_git.push_branch(work, token="", branch="feature/z")
    assert result["status"] == "created"
    # Landed in the push repo, NOT the fetch repo.
    assert _remote_sha(push_remote, "feature/z") == head
    assert _remote_sha(fetch_remote, "feature/z") is None


def test_remote_sha_requires_exact_ref_match(repos: tuple[Path, Path]) -> None:
    """`ls-remote` suffix matching must not report a sibling branch as the target."""
    work, remote = repos
    # Publish a colliding branch whose ref name ends with `feature/x`.
    _git(work, "checkout", "-b", "sub/feature/x")
    push_git.push_branch(work, token="", branch="sub/feature/x")
    assert _remote_sha(remote, "sub/feature/x") is not None

    # A brand-new `feature/x` does not yet exist on the remote.
    _git(work, "checkout", "main")
    _git(work, "checkout", "-b", "feature/x")
    url = push_git.effective_push_url(work, "push-origin")
    assert push_git._remote_sha(work, url, "feature/x", env=None, secrets=()) is None
    # And publishing it actually creates the branch (not a false up-to-date).
    result = push_git.push_branch(work, token="", branch="feature/x")
    assert result["status"] == "created"
    assert _remote_sha(remote, "feature/x") == result["head_sha"]


def test_push_url_rewrite_rule_rejected(repos: tuple[Path, Path]) -> None:
    """A url.*.insteadOf rule that still matches the resolved push URL is refused.

    `git remote get-url --push` applies the first rewrite (mid -> final); a second
    rule whose FROM prefix matches that resolved URL would make `git push` rewrite
    it again (final -> other), publishing to a different repo than the one
    inspected. That ambiguity must be rejected.
    """
    work, _ = repos
    _git(work, "config", "url.https://final.example/.insteadOf", "https://mid.example/")
    _git(
        work, "config", "url.https://other.example/.insteadOf", "https://final.example/"
    )
    _git(
        work, "remote", "set-url", "--push", "push-origin", "https://mid.example/x.git"
    )
    with pytest.raises(GitPushError, match="rewrite the resolved push destination"):
        push_git.effective_push_url(work, "push-origin")


def test_multiple_push_urls_rejected(tmp_path: Path) -> None:
    a = tmp_path / "a.git"
    a.mkdir()
    _git(a, "init", "--bare", "--initial-branch=main")
    b = tmp_path / "b.git"
    b.mkdir()
    _git(b, "init", "--bare", "--initial-branch=main")
    work = tmp_path / "w2"
    work.mkdir()
    _git(work, "init", "--initial-branch=main")
    _git(work, "remote", "add", "push-origin", str(a))
    _git(work, "remote", "set-url", "--push", "push-origin", str(a))
    _git(work, "remote", "set-url", "--push", "--add", "push-origin", str(b))
    with pytest.raises(GitPushError, match="multiple push URLs"):
        push_git.effective_push_url(work, "push-origin")
