from __future__ import annotations

import argparse

import pytest

from wea_cli import cli


def test_parser_supports_comment_subcommand() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(["comment", "144", "--file", "note.md", "--dry-run"])

    assert args.command == "comment"
    assert args.issue == 144
    assert args.file == "note.md"
    assert args.dry_run is True


def test_cmd_comment_dry_run_prints_preview(temp_repo, capsys: pytest.CaptureFixture[str]) -> None:
    comment_file = temp_repo / "comment.md"
    message = "\u041f\u0440\u0438\u0432\u0435\u0442 from agent0"
    comment_file.write_text(f"{message}\n", encoding="utf-8")

    args = argparse.Namespace(
        issue=144,
        file=str(comment_file),
        dry_run=True,
        repo="WeTheAgents/wetheagents",
    )
    rc = cli.cmd_comment(args)

    assert rc == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "Issue: #144" in out
    assert str(comment_file.resolve()) in out
    assert message in out


def test_cmd_comment_rejects_empty_file(temp_repo, capsys: pytest.CaptureFixture[str]) -> None:
    comment_file = temp_repo / "comment.md"
    comment_file.write_text("", encoding="utf-8")

    args = argparse.Namespace(
        issue=144,
        file=str(comment_file),
        dry_run=False,
        repo="WeTheAgents/wetheagents",
    )
    rc = cli.cmd_comment(args)

    assert rc == cli.EXIT_DOMAIN_ERROR
    assert "Comment file is empty." in capsys.readouterr().out


def test_cmd_comment_posts_comment_body(
    temp_repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    comment_file = temp_repo / "comment.md"
    comment_file.write_text("Ship it.\n", encoding="utf-8")
    called: dict[str, object] = {}

    def _fake_post_issue_comment(issue: int, content: str, *, repo: str) -> None:
        called["issue"] = issue
        called["content"] = content
        called["repo"] = repo

    monkeypatch.setattr(cli, "post_issue_comment", _fake_post_issue_comment)

    args = argparse.Namespace(
        issue=144,
        file=str(comment_file),
        dry_run=False,
        repo="WeTheAgents/wetheagents",
    )
    rc = cli.cmd_comment(args)

    assert rc == cli.EXIT_OK
    assert called == {
        "issue": 144,
        "content": "Ship it.\n",
        "repo": "WeTheAgents/wetheagents",
    }
    assert "Posted comment on issue #144." in capsys.readouterr().out
