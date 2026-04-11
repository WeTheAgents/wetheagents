from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.check_branch_entropy import (
    build_report,
    classify_branch,
    extract_issue_number,
    list_remote_branches,
    main,
    render_report,
)


def _tasks() -> dict[str, dict[str, str]]:
    return {
        "414": {"status": "open", "title": "stale branch entropy audit"},
        "403": {"status": "paid", "title": "gauntlet red-team"},
        "402": {"status": "claimed", "title": "needs review"},
    }


def test_extract_issue_number_from_valid_agent_branch() -> None:
    assert extract_issue_number("agent/codex-19/414-branch-entropy-audit") == 414


def test_extract_issue_number_rejects_non_agent_branch() -> None:
    assert extract_issue_number("feature/codex-19/414-branch-entropy-audit") is None


def test_classify_branch_marks_paid_task_stale() -> None:
    row = classify_branch("agent/codex-19/403-redteam", _tasks())
    assert row["classification"] == "STALE"
    assert row["task_status"] == "paid"


def test_classify_branch_marks_open_task_active() -> None:
    row = classify_branch("agent/codex-19/414-branch-entropy-audit", _tasks())
    assert row["classification"] == "ACTIVE"
    assert row["task_status"] == "open"


def test_classify_branch_marks_missing_issue_review() -> None:
    row = classify_branch("agent/codex-19/999-no-match", _tasks())
    assert row["classification"] == "REVIEW"
    assert "not found" in row["reason"]


def test_classify_branch_marks_non_open_non_paid_review() -> None:
    row = classify_branch("agent/codex-19/402-needs-review", _tasks())
    assert row["classification"] == "REVIEW"
    assert "manual review" in row["reason"]


def test_build_report_sorts_and_counts_multiple_branches() -> None:
    report = build_report(
        [
            "agent/codex-19/414-branch-entropy-audit",
            "junk-branch",
            "agent/codex-19/403-redteam",
        ],
        {"tasks": _tasks()},
    )
    assert [row["branch"] for row in report] == [
        "agent/codex-19/403-redteam",
        "agent/codex-19/414-branch-entropy-audit",
        "junk-branch",
    ]
    assert [row["classification"] for row in report] == ["STALE", "ACTIVE", "REVIEW"]


def test_render_report_is_readable() -> None:
    report = build_report(
        [
            "agent/codex-19/403-redteam",
            "agent/codex-19/414-branch-entropy-audit",
        ],
        {"tasks": _tasks()},
    )
    text = render_report(report, remote="origin")
    assert "BRANCH ENTROPY AUDIT" in text
    assert "Summary: 1 STALE, 1 ACTIVE, 0 REVIEW" in text
    assert "[STALE] agent/codex-19/403-redteam" in text
    assert "[ACTIVE] agent/codex-19/414-branch-entropy-audit" in text


def test_list_remote_branches_parses_git_ls_remote_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["git"],
            returncode=0,
            stdout=(
                "abc refs/heads/agent/codex-19/414-branch-entropy-audit\n"
                "def refs/heads/main\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    branches, error = list_remote_branches()
    assert branches == ["agent/codex-19/414-branch-entropy-audit", "main"]
    assert error is None


def test_list_remote_branches_returns_error_but_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.CalledProcessError(
            128,
            ["git", "ls-remote", "--heads", "origin"],
            stderr="network blocked",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    branches, error = list_remote_branches()
    assert branches == []
    assert error == "network blocked"


def test_main_exits_zero_even_if_git_collection_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "scripts.check_branch_entropy.load_task_index",
        lambda root: {"tasks": _tasks()},
    )
    monkeypatch.setattr(
        "scripts.check_branch_entropy.list_remote_branches",
        lambda remote: ([], "network blocked"),
    )

    code = main(["--root", str(Path.cwd())])
    captured = capsys.readouterr()

    assert code == 0
    assert "Collection note: network blocked" in captured.out
