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


# ── cmd_claim ──────────────────────────────────────────────────────────


def test_cmd_claim_returns_error_on_gh_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "post_issue_comment", _raise_gh_error)

    args = argparse.Namespace(
        issue=42,
        agent="Claude-1@claude",
        plain=False,
        dry_run=False,
        repo="WeTheAgents/wetheagents",
        root=None,
    )
    rc = cli.cmd_claim(args)

    assert rc == cli.EXIT_RUNTIME_ERROR
    assert "Failed to post claim comment" in capsys.readouterr().out


# ── cmd_submit ─────────────────────────────────────────────────────────


def test_cmd_submit_returns_error_on_gh_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    submission = tmp_path / "sub.md"
    submission.write_text("## Work\nDone.\n\n## Agent\nClaude-1@claude\n", encoding="utf-8")
    monkeypatch.setattr(
        cli,
        "view_issue",
        lambda issue, repo: {
            "number": issue,
            "body": "### Verification Criteria\n\n- [ ] MUST: `pytest tests/ -q` exits 0\n- [ ] MUST NOT: modify files outside `src/`\n",
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
    monkeypatch.setattr(cli, "create_pull_request", _raise_gh_error)

    args = argparse.Namespace(
        issue=42,
        title="My PR",
        head="feature-branch",
        base="main",
        body=None,
        body_file=None,
        dry_run=False,
        repo="WeTheAgents/wetheagents",
    )
    rc = cli.cmd_pr(args)

    assert rc == cli.EXIT_RUNTIME_ERROR
    assert "Failed to create pull request" in capsys.readouterr().out


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
