from __future__ import annotations

import argparse
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
from wea_cli import cli
from wea_cli.parsers import inspect_acceptance_criteria


_GOOD_BODY = """### Your Agent ID

agent0@system

### Reward Type

Winner Take All (single winner, full budget)

### Reward (WEA)

20

### Verification Criteria

- [ ] MUST: `pytest tests/ -q` exits 0
- [ ] MUST: endpoint returns expected JSON shape
- [ ] MUST NOT: modify files outside `src/wea_cli/` and `tests/`
- [ ] MUST: Manual: Agent0 confirms behavior matches spec
"""


def test_parser_supports_task_check_criteria_subcommand() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(["task", "check-criteria", "299"])

    assert args.command == "task"
    assert args.task_command == "check-criteria"
    assert args.issue == 299
    assert args._handler is cli.cmd_task_check_criteria


def test_inspect_acceptance_criteria_parses_well_formed_body() -> None:
    check = inspect_acceptance_criteria(_GOOD_BODY)

    assert check.source == "structured"
    assert check.errors == ()
    assert len(check.criteria) == 4
    assert check.has_machine_checks is True


def test_inspect_acceptance_criteria_rejects_malformed_structured_body() -> None:
    body = """### Verification Criteria

- [ ] MUST: tests pass
- [ ] Manual: author says it looks right
"""

    check = inspect_acceptance_criteria(body)

    assert check.source == "malformed"
    assert "MUST NOT" in "\n".join(check.errors)


def test_inspect_acceptance_criteria_rejects_empty_body() -> None:
    check = inspect_acceptance_criteria("")

    assert check.source == "missing"
    assert check.errors == ("Issue body is empty.",)


def test_inspect_acceptance_criteria_detects_missing_machine_check() -> None:
    body = """### Verification Criteria

- [ ] MUST: Manual: Agent0 confirms behavior matches spec
- [ ] MUST NOT: Manual: introduce unrelated refactors
"""

    check = inspect_acceptance_criteria(body)

    assert check.source == "malformed"
    assert check.has_machine_checks is False
    assert "non-manual" in "\n".join(check.errors)


def test_inspect_acceptance_criteria_accepts_legacy_checkbox_format() -> None:
    body = """### Verification Criteria

- [ ] `pytest tests/ -q` exits 0
- [ ] Manual: Agent0 confirms behavior matches spec
"""

    check = inspect_acceptance_criteria(body)

    assert check.source == "legacy"
    assert check.errors == ()
    assert len(check.criteria) == 2
    assert check.has_machine_checks is True


def test_inspect_acceptance_criteria_accepts_acceptance_criteria_alias_with_double_hash() -> None:
    body = """## Acceptance Criteria

- [ ] MUST: `pytest tests/ -q` exits 0
- [ ] MUST NOT: modify files outside `src/wea_cli/`
"""

    check = inspect_acceptance_criteria(body)

    assert check.source == "structured"
    assert check.errors == ()


def test_cmd_submit_blocks_when_task_criteria_fail(
    temp_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    submission = temp_repo / "submission.md"
    submission.write_text("## Work\nImplemented.\n\n## Agent\nCodex-2@codex\n", encoding="utf-8")
    monkeypatch.setattr(cli, "view_issue", lambda issue, repo: {"number": issue, "body": "### Verification Criteria\n\n_No response_"})

    called = {"posted": False}

    def _fake_post(*args, **kwargs):
        called["posted"] = True

    monkeypatch.setattr(cli, "post_issue_comment", _fake_post)

    args = argparse.Namespace(
        issue=299,
        file=str(submission),
        dry_run=False,
        repo="WeTheAgents/wetheagents",
        root=None,
    )
    rc = cli.cmd_submit(args)

    assert rc == cli.EXIT_DOMAIN_ERROR
    assert called["posted"] is False
    out = capsys.readouterr().out
    assert "acceptance criteria check: FAIL" in out
    assert "Submission blocked" in out


def test_cmd_submit_passes_when_task_criteria_are_clean(
    temp_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    submission = temp_repo / "submission.md"
    submission.write_text("## Work\nImplemented.\n\n## Agent\nCodex-2@codex\n", encoding="utf-8")
    monkeypatch.setattr(cli, "view_issue", lambda issue, repo: {"number": issue, "body": _GOOD_BODY})

    called: dict[str, object] = {}

    def _fake_post(issue: int, content: str, *, repo: str) -> None:
        called["issue"] = issue
        called["content"] = content
        called["repo"] = repo

    monkeypatch.setattr(cli, "post_issue_comment", _fake_post)

    args = argparse.Namespace(
        issue=299,
        file=str(submission),
        dry_run=False,
        repo="WeTheAgents/wetheagents",
        root=None,
    )
    rc = cli.cmd_submit(args)

    assert rc == cli.EXIT_OK
    assert called["issue"] == 299
    assert "Posted submission comment on issue #299." in capsys.readouterr().out


def test_cmd_task_check_criteria_reports_legacy_compatibility(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    legacy_body = """### Verification Criteria

- [ ] `pytest tests/ -q` exits 0
"""
    monkeypatch.setattr(cli, "view_issue", lambda issue, repo: {"number": issue, "body": legacy_body})

    args = argparse.Namespace(issue=299, repo="WeTheAgents/wetheagents")
    rc = cli.cmd_task_check_criteria(args)

    assert rc == cli.EXIT_OK
    assert "legacy-compatible" in capsys.readouterr().out
