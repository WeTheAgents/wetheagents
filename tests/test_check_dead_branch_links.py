"""Unit tests for scripts/check_dead_branch_links.py."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure the scripts directory is on the path
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from check_dead_branch_links import (  # noqa: E402
    extract_issue_number,
    scan_dead_branches,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_list_fn(branches: list[str], error: str | None = None):
    """Return a fake list_fn that returns the given branches."""
    def _fn(remote: str = "origin"):
        return branches, error
    return _fn


def _make_state_fn(states: dict[int, str]):
    """Return a fake state_fn mapping issue number → state string."""
    def _fn(issue_number: int, repo: str = "WeTheAgents/wetheagents"):
        return states.get(issue_number)
    return _fn


# ---------------------------------------------------------------------------
# extract_issue_number unit tests
# ---------------------------------------------------------------------------

def test_extract_issue_number_valid():
    assert extract_issue_number("agent/claude-5/438-dead-branch") == 438


def test_extract_issue_number_invalid_prefix():
    assert extract_issue_number("main") is None


def test_extract_issue_number_too_few_parts():
    assert extract_issue_number("agent/438-dead-branch") is None


def test_extract_issue_number_non_digit():
    assert extract_issue_number("agent/claude-5/abc-bad-branch") is None


# ---------------------------------------------------------------------------
# scan_dead_branches integration-style tests (all network calls mocked)
# ---------------------------------------------------------------------------

def test_no_agent_branches():
    """No agent/* branches at all → PASS, empty dead list."""
    report = scan_dead_branches(
        _list_fn=_make_list_fn([]),
        _state_fn=_make_state_fn({}),
    )
    assert report["status"] == "PASS"
    assert report["dead_branches"] == []
    assert report["cleanup_commands"] == []
    assert report["branches_scanned"] == 0


def test_open_issue_branch_is_kept():
    """Branch with OPEN issue → not dead."""
    report = scan_dead_branches(
        _list_fn=_make_list_fn(["agent/claude-5/100-some-feature"]),
        _state_fn=_make_state_fn({100: "OPEN"}),
    )
    assert report["status"] == "PASS"
    assert report["dead_branches"] == []


def test_closed_issue_branch_is_dead():
    """Branch with CLOSED issue → dead."""
    report = scan_dead_branches(
        _list_fn=_make_list_fn(["agent/claude-5/200-done-work"]),
        _state_fn=_make_state_fn({200: "CLOSED"}),
    )
    assert report["status"] == "FAIL"
    assert "agent/claude-5/200-done-work" in report["dead_branches"]
    assert "git push origin --delete agent/claude-5/200-done-work" in report["cleanup_commands"]


def test_mixed_open_and_closed():
    """Mixed branches: only closed ones are flagged."""
    branches = [
        "agent/claude-1/10-open-task",
        "agent/claude-5/20-closed-task",
        "agent/gemini-4/30-also-open",
    ]
    states = {10: "OPEN", 20: "CLOSED", 30: "OPEN"}
    report = scan_dead_branches(
        _list_fn=_make_list_fn(branches),
        _state_fn=_make_state_fn(states),
    )
    assert report["status"] == "FAIL"
    assert report["dead_branches"] == ["agent/claude-5/20-closed-task"]
    assert len(report["cleanup_commands"]) == 1


def test_invalid_branch_format_is_skipped():
    """Branch that doesn't match agent/{name}/{num}-{slug} is silently skipped."""
    report = scan_dead_branches(
        _list_fn=_make_list_fn(["agent/bad-format"]),
        _state_fn=_make_state_fn({}),
    )
    assert report["status"] == "PASS"
    assert report["dead_branches"] == []
    assert "agent/bad-format" in report["skipped"]


def test_multiple_dead_branches():
    """Multiple closed branches all appear in dead_branches and cleanup_commands."""
    branches = [
        "agent/alice/1-task-one",
        "agent/alice/2-task-two",
        "agent/alice/3-task-three",
    ]
    states = {1: "CLOSED", 2: "CLOSED", 3: "CLOSED"}
    report = scan_dead_branches(
        _list_fn=_make_list_fn(branches),
        _state_fn=_make_state_fn(states),
    )
    assert report["status"] == "FAIL"
    assert len(report["dead_branches"]) == 3
    assert len(report["cleanup_commands"]) == 3


def test_malformed_issue_number_is_skipped():
    """Branch with non-numeric prefix (e.g. agent/x/notanumber-foo) is skipped."""
    report = scan_dead_branches(
        _list_fn=_make_list_fn(["agent/x/notanumber-foo"]),
        _state_fn=_make_state_fn({}),
    )
    assert report["status"] == "PASS"
    assert "agent/x/notanumber-foo" in report["skipped"]


def test_all_branches_closed():
    """All branches dead → FAIL, all in dead_branches, all cleanup commands present."""
    branches = [
        "agent/claude-5/50-alpha",
        "agent/claude-5/51-beta",
    ]
    states = {50: "CLOSED", 51: "CLOSED"}
    report = scan_dead_branches(
        _list_fn=_make_list_fn(branches),
        _state_fn=_make_state_fn(states),
    )
    assert report["status"] == "FAIL"
    assert set(report["dead_branches"]) == set(branches)
    expected_cmds = {f"git push origin --delete {b}" for b in branches}
    assert set(report["cleanup_commands"]) == expected_cmds


def test_gh_call_failure_skips_branch():
    """If gh returns None (network/auth error), branch is skipped (not falsely flagged dead)."""
    report = scan_dead_branches(
        _list_fn=_make_list_fn(["agent/claude-5/999-unknown"]),
        _state_fn=_make_state_fn({}),  # no entry → returns None
    )
    assert report["status"] == "PASS"
    assert "agent/claude-5/999-unknown" in report["skipped"]


def test_git_fetch_failure_gives_error_status():
    """If git ls-remote fails, status is ERROR (not a false PASS)."""
    report = scan_dead_branches(
        _list_fn=_make_list_fn([], error="git: command not found"),
        _state_fn=_make_state_fn({}),
    )
    assert report["status"] == "ERROR"
    assert report["fetch_error"] == "git: command not found"
    assert report["dead_branches"] == []


def test_cleanup_command_uses_correct_remote():
    """Cleanup commands reference the configured remote name."""
    report = scan_dead_branches(
        remote="push-origin",
        _list_fn=_make_list_fn(["agent/claude-5/77-done"]),
        _state_fn=_make_state_fn({77: "CLOSED"}),
    )
    assert "git push push-origin --delete agent/claude-5/77-done" in report["cleanup_commands"]
