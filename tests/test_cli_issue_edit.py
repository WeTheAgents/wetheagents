from __future__ import annotations

import argparse

import pytest

from wea_cli import cli


def test_parser_supports_issue_edit_subcommand() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(
        [
            "--repo",
            "WeTheAgents/wetheagents",
            "issue",
            "edit",
            "38",
            "--add-label",
            "winner-take-all",
            "--remove-label",
            "paid-on-delivery",
            "--swap",
            "open",
            "claimed",
        ]
    )

    assert args.command == "issue"
    assert args.issue_command == "edit"
    assert args.issue == 38
    assert args.add_label == ["winner-take-all"]
    assert args.remove_label == ["paid-on-delivery"]
    assert args.swap == [["open", "claimed"]]
    assert args._handler is cli.cmd_issue_edit


def test_cmd_issue_edit_requires_operations() -> None:
    args = argparse.Namespace(
        issue=38,
        add_label=[],
        remove_label=[],
        swap=[],
        dry_run=False,
        repo="WeTheAgents/wetheagents",
    )
    rc = cli.cmd_issue_edit(args)
    assert rc == cli.EXIT_DOMAIN_ERROR


def test_cmd_issue_edit_calls_safe_editor(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, object] = {}

    def _fake_safe_issue_label_edit(issue: int, *, add_labels, remove_labels, swaps, repo: str):
        called["issue"] = issue
        called["add_labels"] = add_labels
        called["remove_labels"] = remove_labels
        called["swaps"] = swaps
        called["repo"] = repo
        return {
            "issue": issue,
            "state_before": "OPEN",
            "state_after": "OPEN",
            "labels_before": ["open", "task"],
            "labels_after": ["open", "task", "winner-take-all"],
            "labels_target": ["open", "task", "winner-take-all"],
            "changed": True,
        }

    monkeypatch.setattr(cli, "safe_issue_label_edit", _fake_safe_issue_label_edit)

    args = argparse.Namespace(
        issue=38,
        add_label=["winner-take-all"],
        remove_label=[],
        swap=[["paid-on-delivery", "winner-take-all"]],
        dry_run=False,
        repo="WeTheAgents/wetheagents",
    )
    rc = cli.cmd_issue_edit(args)

    assert rc == cli.EXIT_OK
    assert called == {
        "issue": 38,
        "add_labels": ["winner-take-all"],
        "remove_labels": [],
        "swaps": [("paid-on-delivery", "winner-take-all")],
        "repo": "WeTheAgents/wetheagents",
    }
