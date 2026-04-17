from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from wea_cli import cli


def _args(**overrides: object) -> argparse.Namespace:
    payload: dict[str, object] = {
        "issue": 42,
        "head": "agent/codex-2/42-add-widget",
        "base": "main",
        "title": None,
        "agent": "Codex-2@codex",
        "deliverable": "Implemented the widget and added tests.",
        "deliverable_file": None,
        "body": None,
        "body_file": None,
        "dry_run": False,
        "repo": "WeTheAgents/wetheagents",
    }
    payload.update(overrides)
    return argparse.Namespace(**payload)


def test_cmd_pr_autogenerates_wea_compliant_title_and_body(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: dict[str, str] = {}

    monkeypatch.setattr(cli, "remote_branch_exists", lambda head, repo: True)

    def _fake_create_pull_request(*, title: str, body: str, head: str, base: str, repo: str) -> str:
        seen.update(
            {
                "title": title,
                "body": body,
                "head": head,
                "base": base,
                "repo": repo,
            }
        )
        return "https://example.test/pr/42"

    monkeypatch.setattr(cli, "create_pull_request", _fake_create_pull_request)

    rc = cli.cmd_pr(_args())

    assert rc == cli.EXIT_OK
    assert seen == {
        "title": "[Task #42] Add widget",
        "body": (
            "## Task\n"
            "Closes #42\n\n"
            "## Deliverable\n"
            "Implemented the widget and added tests.\n\n"
            "## Agent\n"
            "Codex-2@codex\n"
        ),
        "head": "agent/codex-2/42-add-widget",
        "base": "main",
        "repo": "WeTheAgents/wetheagents",
    }
    assert "Pull request created: https://example.test/pr/42" in capsys.readouterr().out


def test_cmd_pr_requires_agent_resolution(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "resolve_agent", lambda explicit=None: None)

    rc = cli.cmd_pr(_args(agent=None))

    assert rc == cli.EXIT_RUNTIME_ERROR
    assert "Agent is required" in capsys.readouterr().out


def test_cmd_pr_requires_deliverable_or_body(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = cli.cmd_pr(_args(deliverable=None))

    assert rc == cli.EXIT_DOMAIN_ERROR
    assert "Provide `--deliverable`, `--deliverable-file`, `--body`, or `--body-file`." in capsys.readouterr().out


def test_cmd_pr_rejects_invalid_head_pattern(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = cli.cmd_pr(_args(head="feature/add-widget"))

    assert rc == cli.EXIT_DOMAIN_ERROR
    assert "Head branch must match `agent/<name>/<issue>-<short-slug>`." in capsys.readouterr().out


def test_cmd_pr_rejects_head_issue_mismatch(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = cli.cmd_pr(_args(head="agent/codex-2/99-add-widget"))

    assert rc == cli.EXIT_DOMAIN_ERROR
    assert "Head branch issue #99 does not match requested issue #42." in capsys.readouterr().out


def test_cmd_pr_validates_explicit_body(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = cli.cmd_pr(
        _args(
            deliverable=None,
            body=(
                "## Task\n"
                "Closes #42\n\n"
                "## Deliverable\n"
                "Implemented the widget.\n"
            ),
        )
    )

    assert rc == cli.EXIT_DOMAIN_ERROR
    assert "Missing `## Agent` section." in capsys.readouterr().out


def test_cmd_pr_dry_run_prints_generated_body_from_deliverable_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    deliverable = tmp_path / "deliverable.md"
    deliverable.write_text("Added the widget, docs, and regression tests.\n", encoding="utf-8")

    rc = cli.cmd_pr(_args(deliverable=None, deliverable_file=str(deliverable), dry_run=True))

    out = capsys.readouterr().out
    assert rc == cli.EXIT_OK
    assert "Title" in out
    assert "[Task #42] Add widget" in out
    assert "Agent" in out
    assert "Codex-2@codex" in out
    assert "Closes #42" in out
    assert "Added the widget, docs, and regression tests." in out


def test_cmd_pr_requires_wea_push_before_creating_pr(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "remote_branch_exists", lambda head, repo: False)

    rc = cli.cmd_pr(_args())

    assert rc == cli.EXIT_DOMAIN_ERROR
    assert "Run `wea push agent/codex-2/42-add-widget` and retry." in capsys.readouterr().out
