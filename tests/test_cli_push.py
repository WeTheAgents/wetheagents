"""Regression coverage for the Git-transport `wea push`.

Push is exercised end to end against a local bare remote (no network, no
credentials required for a filesystem remote), covering the add/change/delete
SHA sequence, new/fast-forward/idempotent updates, and every rejection path
that caused the Windows pilot to fall back to `git push`. A subprocess test
drives the real installed entry point through ``cmd_push``.
"""

from __future__ import annotations

import base64
import subprocess
import sys
from pathlib import Path

import pytest

from wea_cli import cli


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _head(root: Path, ref: str = "HEAD") -> str:
    return _git(root, "rev-parse", ref)


def _remote_sha(bare: Path, branch: str) -> str:
    out = _git(bare, "rev-parse", f"refs/heads/{branch}")
    return out


@pytest.fixture()
def repo_with_remote(tmp_path: Path) -> tuple[Path, Path]:
    bare = tmp_path / "up.git"
    work = tmp_path / "work"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(bare), "--bare"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(work)],
        check=True,
        capture_output=True,
    )
    _git(work, "config", "user.email", "a@b.c")
    _git(work, "config", "user.name", "tester")
    _git(work, "remote", "add", "origin", str(bare))
    (work / "f.txt").write_text("one\n", encoding="utf-8")
    _git(work, "add", "f.txt")
    _git(work, "commit", "-qm", "one")
    return work, bare


# --- happy paths: new / add-change-delete / fast-forward / idempotent --------


def test_push_creates_new_remote_branch_with_exact_sha(
    repo_with_remote: tuple[Path, Path],
) -> None:
    work, bare = repo_with_remote
    _git(work, "checkout", "-qb", "feature")
    head = _head(work)
    message = cli._push_branch_via_git(work, "origin", "feature", "tok")
    assert "Created origin/feature" in message
    assert head in message
    assert _remote_sha(bare, "feature") == head


def test_push_add_change_delete_sequence_tracks_exact_shas(
    repo_with_remote: tuple[Path, Path],
) -> None:
    work, bare = repo_with_remote
    _git(work, "checkout", "-qb", "feature")

    # add
    (work / "added.txt").write_text("added\n", encoding="utf-8")
    _git(work, "add", "added.txt")
    _git(work, "commit", "-qm", "add file")
    cli._push_branch_via_git(work, "origin", "feature", "tok")
    assert _remote_sha(bare, "feature") == _head(work)

    # change
    (work / "added.txt").write_text("changed\n", encoding="utf-8")
    _git(work, "commit", "-qam", "change file")
    cli._push_branch_via_git(work, "origin", "feature", "tok")
    assert _remote_sha(bare, "feature") == _head(work)

    # delete
    _git(work, "rm", "-q", "added.txt")
    _git(work, "commit", "-qm", "delete file")
    message = cli._push_branch_via_git(work, "origin", "feature", "tok")
    assert "Updated origin/feature" in message
    assert _remote_sha(bare, "feature") == _head(work)


def test_push_is_idempotent_when_up_to_date(
    repo_with_remote: tuple[Path, Path],
) -> None:
    work, _bare = repo_with_remote
    _git(work, "checkout", "-qb", "feature")
    cli._push_branch_via_git(work, "origin", "feature", "tok")
    message = cli._push_branch_via_git(work, "origin", "feature", "tok")
    assert "already up to date" in message


def test_push_then_delete_removes_remote_branch(
    repo_with_remote: tuple[Path, Path],
) -> None:
    work, bare = repo_with_remote
    _git(work, "checkout", "-qb", "disposable")
    cli._push_branch_via_git(work, "origin", "disposable", "tok")
    assert _remote_sha(bare, "disposable")  # present
    _git(work, "push", "origin", "--delete", "disposable")
    listing = _git(work, "ls-remote", "origin", "refs/heads/disposable")
    assert listing == ""


# --- rejection paths ---------------------------------------------------------


def test_push_rejects_main_publication(
    repo_with_remote: tuple[Path, Path],
) -> None:
    work, _bare = repo_with_remote
    with pytest.raises(cli.PushError, match="main"):
        cli._push_branch_via_git(work, "origin", None, "tok")


def test_push_allows_main_only_with_explicit_flag(
    repo_with_remote: tuple[Path, Path],
) -> None:
    work, bare = repo_with_remote
    message = cli._push_branch_via_git(work, "origin", None, "tok", allow_main=True)
    assert "origin/main" in message
    assert _remote_sha(bare, "main") == _head(work)


def test_push_rejects_detached_head(
    repo_with_remote: tuple[Path, Path],
) -> None:
    work, _bare = repo_with_remote
    _git(work, "checkout", "-q", "--detach")
    with pytest.raises(cli.PushError, match=r"[Dd]etached"):
        cli._push_branch_via_git(work, "origin", None, "tok")


def test_push_rejects_dirty_working_tree(
    repo_with_remote: tuple[Path, Path],
) -> None:
    work, _bare = repo_with_remote
    _git(work, "checkout", "-qb", "feature")
    (work / "f.txt").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(cli.PushError, match="dirty ambiguity"):
        cli._push_branch_via_git(work, "origin", None, "tok")


def test_push_rejects_dirty_when_current_branch_named_explicitly(
    repo_with_remote: tuple[Path, Path],
) -> None:
    work, _bare = repo_with_remote
    _git(work, "checkout", "-qb", "feature")
    (work / "f.txt").write_text("dirty\n", encoding="utf-8")
    # Naming the checked-out branch explicitly must not bypass the dirty guard.
    with pytest.raises(cli.PushError, match="dirty ambiguity"):
        cli._push_branch_via_git(work, "origin", "feature", "tok")


def test_push_targets_push_url_when_fetch_and_push_differ(
    repo_with_remote: tuple[Path, Path],
) -> None:
    work, fetch_bare = repo_with_remote
    # Give origin a separate push URL; `git push` must write there and readback
    # must verify there, not against the fetch repository.
    push_bare = work.parent / "push.git"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(push_bare), "--bare"],
        check=True,
        capture_output=True,
    )
    _git(work, "remote", "set-url", "--push", "origin", str(push_bare))
    _git(work, "checkout", "-qb", "feature")
    head = _head(work)

    message = cli._push_branch_via_git(work, "origin", "feature", "tok")
    assert head in message
    # Landed in the push repository, absent from the fetch repository.
    assert _remote_sha(push_bare, "feature") == head
    assert _git(work, "ls-remote", str(fetch_bare), "refs/heads/feature") == ""


def test_push_verifies_every_push_destination(
    repo_with_remote: tuple[Path, Path],
) -> None:
    work, _fetch_bare = repo_with_remote
    # Two push destinations; git push writes both, and both must be verified.
    push_a = work.parent / "push_a.git"
    push_b = work.parent / "push_b.git"
    for bare in (push_a, push_b):
        subprocess.run(
            ["git", "init", "-q", "-b", "main", str(bare), "--bare"],
            check=True,
            capture_output=True,
        )
    _git(work, "remote", "set-url", "--push", "origin", str(push_a))
    _git(work, "remote", "set-url", "--push", "--add", "origin", str(push_b))
    _git(work, "checkout", "-qb", "feature")
    head = _head(work)

    cli._push_branch_via_git(work, "origin", "feature", "tok")
    assert _remote_sha(push_a, "feature") == head
    assert _remote_sha(push_b, "feature") == head


def test_push_rejects_non_fast_forward(
    repo_with_remote: tuple[Path, Path],
) -> None:
    work, bare = repo_with_remote
    _git(work, "checkout", "-qb", "feature")
    cli._push_branch_via_git(work, "origin", "feature", "tok")
    # Diverge the remote from a second clone so local is no longer a descendant.
    clone = work.parent / "clone2"
    subprocess.run(
        ["git", "clone", "-q", str(bare), str(clone)], check=True, capture_output=True
    )
    _git(clone, "config", "user.email", "a@b.c")
    _git(clone, "config", "user.name", "t")
    _git(clone, "checkout", "-q", "feature")
    (clone / "f.txt").write_text("remote-only\n", encoding="utf-8")
    _git(clone, "commit", "-qam", "remote change")
    _git(clone, "push", "-q", "-f", "origin", "feature")
    # Local advances independently -> non-fast-forward.
    (work / "f.txt").write_text("local-only\n", encoding="utf-8")
    _git(work, "commit", "-qam", "local change")
    with pytest.raises(cli.PushError):
        cli._push_branch_via_git(work, "origin", "feature", "tok")


def test_push_rejects_explicit_branch_other_than_current(
    repo_with_remote: tuple[Path, Path],
) -> None:
    work, _bare = repo_with_remote
    _git(work, "checkout", "-qb", "feature")
    # On `feature`, an explicit different branch must be rejected: push only
    # publishes the current checked-out branch.
    with pytest.raises(cli.PushError, match="only the current branch"):
        cli._push_branch_via_git(work, "origin", "main", "tok")


def test_push_handles_tag_colliding_with_current_branch(
    repo_with_remote: tuple[Path, Path],
) -> None:
    work, bare = repo_with_remote
    _git(work, "checkout", "-qb", "feature")
    # A tag named exactly like the branch must not be published in its place.
    _git(work, "tag", "feature")
    head = _head(work, "refs/heads/feature")
    cli._push_branch_via_git(work, "origin", "feature", "tok")
    assert _remote_sha(bare, "feature") == head
    # The colliding tag was not pushed (transport is bounded to the branch).
    assert _git(work, "ls-remote", "origin", "refs/tags/feature") == ""


def test_push_resolves_current_branch_named_like_a_ref_prefix(
    repo_with_remote: tuple[Path, Path],
) -> None:
    work, bare = repo_with_remote
    # A branch literally named `heads/feature` must strip refs/heads/ exactly once.
    _git(work, "checkout", "-qb", "heads/feature")
    assert cli._current_branch(work) == "heads/feature"
    cli._push_branch_via_git(work, "origin", None, "tok")
    assert _remote_sha(bare, "heads/feature") == _head(work)


def test_push_rejects_mirror_remote(
    repo_with_remote: tuple[Path, Path],
) -> None:
    work, _bare = repo_with_remote
    _git(work, "config", "remote.origin.mirror", "true")
    _git(work, "checkout", "-qb", "feature")
    with pytest.raises(cli.PushError, match="mirror"):
        cli._push_branch_via_git(work, "origin", "feature", "tok")


def test_push_does_not_publish_unrelated_tags(
    repo_with_remote: tuple[Path, Path],
) -> None:
    work, _bare = repo_with_remote
    _git(work, "checkout", "-qb", "feature")
    _git(work, "tag", "v9.9.9")  # annotated-free tag pointing at the pushed commit
    cli._push_branch_via_git(work, "origin", "feature", "tok")
    # --no-follow-tags: the tag must not ride along with the branch push.
    assert _git(work, "ls-remote", "origin", "refs/tags/v9.9.9") == ""


def test_push_surfaces_transport_failure_for_missing_remote(
    repo_with_remote: tuple[Path, Path],
) -> None:
    work, _bare = repo_with_remote
    _git(work, "checkout", "-qb", "feature")
    with pytest.raises(cli.PushError, match="not configured"):
        cli._push_branch_via_git(work, "ghost-remote", "feature", "tok")


# --- credential handling -----------------------------------------------------


def test_auth_env_never_exposes_token_on_command_line() -> None:
    env = cli._git_auth_env("s3cr3t-token")
    # Token appears only base64-encoded inside the appended header value.
    assert "s3cr3t-token" not in env["GIT_CONFIG_VALUE_1"]
    decoded = base64.b64decode(env["GIT_CONFIG_VALUE_1"].split()[-1]).decode()
    assert decoded == "x-access-token:s3cr3t-token"
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    # An empty value is injected first to reset any inherited extraheader.
    assert env["GIT_CONFIG_COUNT"] == "2"
    assert env["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"
    assert env["GIT_CONFIG_VALUE_0"] == ""
    assert env["GIT_CONFIG_KEY_1"] == "http.https://github.com/.extraheader"


def test_auth_env_replaces_inherited_extraheader(
    repo_with_remote: tuple[Path, Path],
) -> None:
    import os

    work, _bare = repo_with_remote
    # A persisted credential header already configured on the repo.
    _git(
        work,
        "config",
        "http.https://github.com/.extraheader",
        "Authorization: Basic inherited-credential",
    )
    env = {**os.environ, **cli._git_auth_env("dummy")}
    headers = subprocess.run(
        [
            "git",
            "-C",
            str(work),
            "config",
            "--get-all",
            "http.https://github.com/.extraheader",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    # git's HTTP layer resets the multivalued extraheader on an empty value, so
    # the effective headers are those after the last empty entry: only ours.
    last_reset = max(i for i, h in enumerate(headers) if h.strip() == "")
    effective = [h for h in headers[last_reset + 1 :] if h.strip()]
    assert effective == [env["GIT_CONFIG_VALUE_1"]]


def test_sanitize_strips_token_and_url_credentials() -> None:
    out = cli._sanitize_git_output(
        "`git push https://alice:s3cr3t@github.com/x.git` failed: tok-xyz denied",
        "tok-xyz",
    )
    assert "s3cr3t" not in out
    assert "tok-xyz" not in out
    assert "https://***@github.com/x.git" in out


def test_redact_removes_token_from_surfaced_output() -> None:
    redacted = cli._redact("failed for tok-abc at url", "tok-abc")
    assert redacted == "failed for *** at url"
    assert cli._redact("no token here", "") == "no token here"


def test_push_success_message_does_not_contain_token(
    repo_with_remote: tuple[Path, Path],
) -> None:
    work, _bare = repo_with_remote
    _git(work, "checkout", "-qb", "feature")
    message = cli._push_branch_via_git(work, "origin", "feature", "super-secret")
    assert "super-secret" not in message


# --- subprocess CLI integration ----------------------------------------------


def test_cli_push_subprocess_end_to_end(
    repo_with_remote: tuple[Path, Path],
) -> None:
    work, bare = repo_with_remote
    # cmd_push resolves the repo root via ledger/balances.json; provide a stub.
    (work / "ledger").mkdir()
    (work / "ledger" / "balances.json").write_text("{}", encoding="utf-8")
    _git(work, "checkout", "-qb", "feature")
    (work / "g.txt").write_text("two\n", encoding="utf-8")
    _git(work, "add", "g.txt")
    _git(work, "commit", "-qm", "two")
    head = _head(work)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "wea_cli.cli",
            "--root",
            str(work),
            "push",
            "feature",
            "--remote",
            "origin",
        ],
        capture_output=True,
        text=True,
        env={**_clean_env(), "GITHUB_TOKEN": "tok"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert head in result.stdout
    assert _remote_sha(bare, "feature") == head


def _clean_env() -> dict[str, str]:
    import os

    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(cli.__file__).resolve().parents[1])
    env["PYTHONIOENCODING"] = "utf-8"
    return env
