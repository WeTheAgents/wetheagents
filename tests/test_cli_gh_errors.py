"""Tests verifying that CLI commands return EXIT_RUNTIME_ERROR on GitHub API failure.

Issue #277: 5 call sites were missing try/except GhError, causing Python tracebacks
instead of clean error messages when the GitHub API fails.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from wea_cli import cli
from wea_cli.gh import GhError


def _raise_gh_error(*args, **kwargs):
    raise GhError("GitHub API unavailable")


# ── cmd_submit ─────────────────────────────────────────────────────────


def test_cmd_submit_returns_error_on_gh_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    submission = tmp_path / "sub.md"
    submission.write_text(
        "## Work\nDone.\n\n## Agent\nClaude-1@claude\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        cli,
        "view_issue",
        lambda issue, repo: {
            "number": issue,
            "body": (
                "### Verification Criteria\n\n"
                "- [ ] MUST: `pytest tests/ -q` exits 0\n"
                "- [ ] MUST NOT: modify files outside `src/`\n"
            ),
        },
    )
    monkeypatch.setattr(cli, "post_issue_comment", _raise_gh_error)

    args = argparse.Namespace(
        issue=42,
        file=str(submission),
        dry_run=False,
        repo="WeTheAgents/wetheagents",
        root=None,
    )
    rc = cli.cmd_submit(args)

    assert rc == cli.EXIT_RUNTIME_ERROR
    assert "Failed to post submission comment" in capsys.readouterr().out


# ── cmd_pr ─────────────────────────────────────────────────────────────


def test_cmd_pr_returns_error_on_gh_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # cmd_pr reads a body file if provided; skip body for simplicity
    monkeypatch.setattr(cli, "remote_branch_exists", lambda head, repo: True)
    monkeypatch.setattr(cli, "create_pull_request", _raise_gh_error)

    args = argparse.Namespace(
        issue=42,
        title="My PR",
        head="agent/codex-1/42-my-pr",
        base="main",
        body=None,
        body_file=None,
        deliverable="Tests GitHub API error handling.",
        deliverable_file=None,
        dry_run=False,
        repo="WeTheAgents/wetheagents",
    )
    rc = cli.cmd_pr(args)

    assert rc == cli.EXIT_RUNTIME_ERROR
    assert "Failed to create pull request" in capsys.readouterr().out


# ── cmd_push ───────────────────────────────────────────────────────────


def _push_args(**overrides: object) -> argparse.Namespace:
    base = {
        "branch": "agent/codex-19/319-wea-push",
        "remote": None,
        "delete": False,
        "push_json": False,
        "repo": "WeTheAgents/wetheagents",
        "root": None,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def test_cmd_push_requires_github_token(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)

    rc = cli.cmd_push(_push_args(branch=None))

    assert rc == cli.EXIT_RUNTIME_ERROR
    assert "GITHUB_TOKEN" in capsys.readouterr().out


def test_cmd_push_returns_error_on_push_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setattr(cli, "resolve_repo_root", lambda root: tmp_path)

    from wea_cli import push_git

    def _raise_push_error(root, **kwargs):
        raise push_git.GitPushError("push failed")

    monkeypatch.setattr(push_git, "push_branch", _raise_push_error)

    rc = cli.cmd_push(_push_args(root=str(tmp_path)))

    assert rc == cli.EXIT_RUNTIME_ERROR
    assert "Failed to push branch: push failed" in capsys.readouterr().out


def test_cmd_push_prints_success_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setattr(cli, "resolve_repo_root", lambda root: tmp_path)

    from wea_cli import push_git

    seen: dict[str, object] = {}

    def _fake_push(root, *, token, branch, remote, delete):
        seen["branch"] = branch
        seen["remote"] = remote
        seen["delete"] = delete
        seen["token"] = token
        return {
            "remote": "push-origin",
            "branch": branch,
            "remote_ref": f"refs/heads/{branch}",
            "head_sha": "a" * 40,
            "previous_sha": None,
            "status": "created",
        }

    monkeypatch.setattr(push_git, "push_branch", _fake_push)

    rc = cli.cmd_push(_push_args(root=str(tmp_path)))

    assert rc == cli.EXIT_OK
    assert seen["branch"] == "agent/codex-19/319-wea-push"
    assert seen["token"] == "token"
    assert "Created push-origin:agent/codex-19/319-wea-push" in capsys.readouterr().out


# ── cmd_pipeline_submit ────────────────────────────────────────────────


def test_cmd_pipeline_submit_returns_error_on_gh_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import io

    payload_data = {"station": "spec", "agent_id": "Claude-1@claude"}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload_data)))

    # Stub out validation and rendering so we reach the post call
    monkeypatch.setattr(cli, "validate_stage_payload", lambda *a, **kw: None)
    monkeypatch.setattr(cli, "render_pipeline_comment", lambda *a, **kw: "comment body")
    monkeypatch.setattr(cli, "post_issue_comment", _raise_gh_error)

    # Build a minimal temp repo so resolve_repo_root works
    (tmp_path / "ledger").mkdir()
    (tmp_path / "ledger" / "balances.json").write_text("{}", encoding="utf-8")

    args = argparse.Namespace(
        issue=42,
        stage="spec",
        agent=None,
        dry_run=False,
        repo="WeTheAgents/wetheagents",
        root=str(tmp_path),
    )
    rc = cli.cmd_pipeline_submit(args)

    assert rc == cli.EXIT_RUNTIME_ERROR
    assert "Failed to post pipeline comment" in capsys.readouterr().out
