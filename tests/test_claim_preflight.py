from __future__ import annotations

import argparse

import pytest

from wea_cli import cli
from wea_cli.parsers import AcceptanceCriteriaCheck, AcceptanceCriterion


_BODY_WITH_CRITERIA = """### Your Agent ID

agent0@system

### Reward (WEA)

20

### Verification Criteria

- [ ] MUST: `pytest tests/ -q` exits 0
- [ ] MUST: endpoint returns expected JSON
- [ ] MUST NOT: modify files outside src/
"""

_BODY_NO_CRITERIA_HIGH_REWARD = """### Your Agent ID

agent0@system

### Reward (WEA)

22

### What needs to be done

Do something.
"""

_BODY_NO_CRITERIA_LOW_REWARD = """### Your Agent ID

agent0@system

### Reward (WEA)

5

### What needs to be done

Do something small.
"""


def _args(issue: int = 100, force: bool = False, dry_run: bool = False, plain: bool = False) -> argparse.Namespace:
    return argparse.Namespace(
        issue=issue,
        agent="Claude-1@claude",
        plain=plain,
        dry_run=dry_run,
        force=force,
        repo="WeTheAgents/wetheagents",
    )


def test_claim_with_valid_criteria_passes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Task with MUST/MUST NOT criteria and high reward — no warning, claim succeeds."""
    monkeypatch.setattr(cli, "view_issue", lambda issue, repo: {"number": issue, "body": _BODY_WITH_CRITERIA})
    posted: dict[str, object] = {}
    monkeypatch.setattr(cli, "post_issue_comment", lambda issue, body, *, repo: posted.update({"issue": issue}))

    rc = cli.cmd_claim(_args())

    assert rc == cli.EXIT_OK
    assert posted.get("issue") == 100
    assert "Warning" not in capsys.readouterr().out


def test_claim_no_criteria_below_threshold_passes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Task with no criteria but low reward (< 10 WEA) — no warning, claim succeeds."""
    monkeypatch.setattr(cli, "view_issue", lambda issue, repo: {"number": issue, "body": _BODY_NO_CRITERIA_LOW_REWARD})
    posted: dict[str, object] = {}
    monkeypatch.setattr(cli, "post_issue_comment", lambda issue, body, *, repo: posted.update({"issue": issue}))

    rc = cli.cmd_claim(_args())

    assert rc == cli.EXIT_OK
    assert posted.get("issue") == 100
    assert "Warning" not in capsys.readouterr().out


def test_claim_no_criteria_at_threshold_blocked(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Task with no criteria and reward >= 10 WEA — warning printed, claim blocked."""
    monkeypatch.setattr(cli, "view_issue", lambda issue, repo: {"number": issue, "body": _BODY_NO_CRITERIA_HIGH_REWARD})
    posted: dict[str, object] = {}
    monkeypatch.setattr(cli, "post_issue_comment", lambda issue, body, *, repo: posted.update({"issue": issue}))

    rc = cli.cmd_claim(_args())

    assert rc == cli.EXIT_DOMAIN_ERROR
    assert "issue" not in posted
    out = capsys.readouterr().out
    assert "Warning" in out
    assert "no parseable acceptance criteria" in out
    assert "--force" in out


def test_claim_force_bypasses_criteria_gate(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Task with no criteria and high reward but --force — warning shown, claim proceeds."""
    monkeypatch.setattr(cli, "view_issue", lambda issue, repo: {"number": issue, "body": _BODY_NO_CRITERIA_HIGH_REWARD})
    posted: dict[str, object] = {}
    monkeypatch.setattr(cli, "post_issue_comment", lambda issue, body, *, repo: posted.update({"issue": issue}))

    rc = cli.cmd_claim(_args(force=True))

    assert rc == cli.EXIT_OK
    assert posted.get("issue") == 100
    out = capsys.readouterr().out
    assert "Warning" in out
    assert "Use --force" not in out


def test_claim_malformed_body_no_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Body with no parseable structure and no reward field — no crash, proceeds (reward=0 < 10)."""
    monkeypatch.setattr(
        cli, "view_issue",
        lambda issue, repo: {"number": issue, "body": "## Title\n\nSome random text with no criteria section."}
    )
    monkeypatch.setattr(cli, "post_issue_comment", lambda issue, body, *, repo: None)

    rc = cli.cmd_claim(_args())

    assert rc == cli.EXIT_OK


def test_claim_empty_must_warns_but_does_not_block(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """MUST: item with empty verifiable text — warning shown but claim is not blocked."""
    empty_must = AcceptanceCriterion(requirement="must", text="", is_manual=False, raw="")
    fake_check = AcceptanceCriteriaCheck(source="structured", criteria=(empty_must,), errors=())
    monkeypatch.setattr(
        cli, "_load_acceptance_criteria_check",
        lambda issue, repo: ({"number": issue, "body": ""}, fake_check, None),
    )
    posted: dict[str, object] = {}
    monkeypatch.setattr(cli, "post_issue_comment", lambda issue, body, *, repo: posted.update({"issue": issue}))

    rc = cli.cmd_claim(_args())

    assert rc == cli.EXIT_OK
    assert posted.get("issue") == 100
    out = capsys.readouterr().out
    assert "Warning" in out
    assert "no verifiable content" in out


def test_claim_parser_supports_force_flag() -> None:
    """build_parser() registers --force on the claim subcommand."""
    parser = cli.build_parser()
    args = parser.parse_args(["claim", "42", "--force"])

    assert args.issue == 42
    assert args.force is True
