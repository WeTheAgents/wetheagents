#!/usr/bin/env python3
"""Tests for scripts/agent_lock.py.

Tests are split into two layers:
  - Pure logic (no mocks): _parse_lock_state, _is_locked
  - Command logic (GitHub I/O mocked): cmd_acquire, cmd_release, cmd_release_all, cmd_status
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import agent_lock as al  # noqa: E402


# ── Helpers ───────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _locked_entry(agent: str, session: str, *, minutes_ahead: int = 120) -> dict:
    expires = _iso(_now() + timedelta(minutes=minutes_ahead))
    return {"action": "acquire", "agent": agent, "session": session, "expires": expires, "ts": _iso(_now())}


def _release_entry(agent: str, session: str) -> dict:
    return {"action": "release", "agent": agent, "session": session, "ts": _iso(_now())}


def _comment(body: str) -> dict:
    return {"body": body}


def _json_comment(payload: dict) -> dict:
    import json
    return _comment(json.dumps(payload))


# ── Pure logic: _parse_lock_state ────────────────────────────


def test_parse_empty_comments() -> None:
    assert al._parse_lock_state([]) == {}


def test_parse_ignores_non_json() -> None:
    comments = [_comment("hello world"), _comment("---"), _comment("")]
    assert al._parse_lock_state(comments) == {}


def test_parse_ignores_json_without_action() -> None:
    comments = [_json_comment({"agent": "claude-1", "session": "s1"})]
    assert al._parse_lock_state(comments) == {}


def test_parse_ignores_json_without_agent() -> None:
    comments = [_json_comment({"action": "acquire", "session": "s1"})]
    assert al._parse_lock_state(comments) == {}


def test_parse_single_acquire() -> None:
    entry = _locked_entry("claude-1", "sess-A")
    state = al._parse_lock_state([_json_comment(entry)])
    assert "claude-1" in state
    assert state["claude-1"]["session"] == "sess-A"
    assert state["claude-1"]["action"] == "acquire"


def test_parse_later_release_overwrites_acquire() -> None:
    acquire = _locked_entry("claude-1", "sess-A")
    release = _release_entry("claude-1", "sess-A")
    state = al._parse_lock_state([_json_comment(acquire), _json_comment(release)])
    assert state["claude-1"]["action"] == "release"


def test_parse_later_acquire_overwrites_release() -> None:
    release = _release_entry("claude-1", "sess-A")
    acquire = _locked_entry("claude-1", "sess-B")
    state = al._parse_lock_state([_json_comment(release), _json_comment(acquire)])
    assert state["claude-1"]["action"] == "acquire"
    assert state["claude-1"]["session"] == "sess-B"


def test_parse_multiple_agents_independent() -> None:
    comments = [
        _json_comment(_locked_entry("claude-1", "sess-A")),
        _json_comment(_locked_entry("codex-2", "sess-B")),
    ]
    state = al._parse_lock_state(comments)
    assert state["claude-1"]["session"] == "sess-A"
    assert state["codex-2"]["session"] == "sess-B"


# ── Pure logic: _is_locked ────────────────────────────────────


def test_is_locked_active_acquire() -> None:
    entry = _locked_entry("claude-1", "sess-A", minutes_ahead=60)
    assert al._is_locked(entry, _now()) is True


def test_is_locked_expired_acquire() -> None:
    entry = {"action": "acquire", "agent": "claude-1", "session": "sess-A",
             "expires": _iso(_now() - timedelta(minutes=1)), "ts": _iso(_now())}
    assert al._is_locked(entry, _now()) is False


def test_is_locked_release_entry() -> None:
    entry = _release_entry("claude-1", "sess-A")
    assert al._is_locked(entry, _now()) is False


def test_is_locked_missing_expires() -> None:
    entry = {"action": "acquire", "agent": "claude-1", "session": "sess-A"}
    assert al._is_locked(entry, _now()) is False


# ── Command: cmd_acquire ──────────────────────────────────────


def _make_status(entries: dict[str, dict]) -> dict[str, dict]:
    """Build a lock-state dict as returned by get_lock_status."""
    return entries


@patch("agent_lock._post_comment")
@patch("agent_lock.get_lock_status")
@patch("time.sleep")
def test_acquire_free_agent_succeeds(mock_sleep: MagicMock, mock_status: MagicMock, mock_post: MagicMock) -> None:
    """Acquiring an unlocked agent returns 0 and posts a comment."""
    # First call: check before acquire → empty
    # Second call (verify 1): our acquire visible → we hold it
    # Third call (verify 2): same
    our_entry = _locked_entry("claude-1", "sess-A")
    mock_status.side_effect = [
        {},                              # initial check
        {"claude-1": our_entry},         # verify 1
        {"claude-1": our_entry},         # verify 2
    ]
    rc = al.cmd_acquire(42, "claude-1", "sess-A", 7200)
    assert rc == 0
    mock_post.assert_called_once()
    call_payload = mock_post.call_args[0][1]
    assert call_payload["action"] == "acquire"
    assert call_payload["agent"] == "claude-1"
    assert call_payload["session"] == "sess-A"


@patch("agent_lock._post_comment")
@patch("agent_lock.get_lock_status")
@patch("time.sleep")
def test_acquire_locked_by_other_returns_1(mock_sleep: MagicMock, mock_status: MagicMock, mock_post: MagicMock) -> None:
    """Acquiring an agent locked by another session returns 1."""
    other_entry = _locked_entry("claude-1", "sess-B")
    mock_status.return_value = {"claude-1": other_entry}
    rc = al.cmd_acquire(42, "claude-1", "sess-A", 7200)
    assert rc == 1
    mock_post.assert_not_called()


@patch("agent_lock._post_comment")
@patch("agent_lock.get_lock_status")
@patch("time.sleep")
def test_acquire_same_session_idempotent(mock_sleep: MagicMock, mock_status: MagicMock, mock_post: MagicMock) -> None:
    """Re-acquiring already-held lock returns 0, no new comment."""
    own_entry = _locked_entry("claude-1", "sess-A")
    mock_status.return_value = {"claude-1": own_entry}
    rc = al.cmd_acquire(42, "claude-1", "sess-A", 7200)
    assert rc == 0
    mock_post.assert_not_called()


@patch("agent_lock._post_comment")
@patch("agent_lock.get_lock_status")
@patch("time.sleep")
def test_acquire_expired_lock_can_be_taken(mock_sleep: MagicMock, mock_status: MagicMock, mock_post: MagicMock) -> None:
    """Expired lock from another session is treated as free."""
    expired = {"action": "acquire", "agent": "claude-1", "session": "sess-OLD",
               "expires": _iso(_now() - timedelta(hours=1)), "ts": _iso(_now())}
    our_entry = _locked_entry("claude-1", "sess-NEW")
    mock_status.side_effect = [
        {"claude-1": expired},       # initial check: expired → free
        {"claude-1": our_entry},     # verify 1
        {"claude-1": our_entry},     # verify 2
    ]
    rc = al.cmd_acquire(42, "claude-1", "sess-NEW", 7200)
    assert rc == 0


@patch("agent_lock._post_comment")
@patch("agent_lock.get_lock_status")
@patch("time.sleep")
def test_acquire_race_lost_returns_1(mock_sleep: MagicMock, mock_status: MagicMock, mock_post: MagicMock) -> None:
    """Race condition: competitor wins between our post and verify → return 1."""
    competitor_entry = _locked_entry("claude-1", "sess-RACE")
    mock_status.side_effect = [
        {},                                    # initial: free
        {"claude-1": competitor_entry},        # verify 1: competitor visible
    ]
    rc = al.cmd_acquire(42, "claude-1", "sess-A", 7200)
    assert rc == 1


@patch("agent_lock._post_comment")
@patch("agent_lock.get_lock_status")
@patch("time.sleep")
def test_acquire_not_visible_after_settle_returns_1(mock_sleep: MagicMock, mock_status: MagicMock, mock_post: MagicMock) -> None:
    """Our comment not visible after settle delay → return 1."""
    mock_status.side_effect = [
        {},   # initial: free
        {},   # verify 1: _NOT_VISIBLE (our comment missing)
        {},   # verify 2: still missing → fail
    ]
    rc = al.cmd_acquire(42, "claude-1", "sess-A", 7200)
    assert rc == 1


# ── Command: cmd_release ──────────────────────────────────────


@patch("agent_lock._post_comment")
@patch("agent_lock.get_lock_status")
def test_release_held_lock_succeeds(mock_status: MagicMock, mock_post: MagicMock) -> None:
    own_entry = _locked_entry("claude-1", "sess-A")
    mock_status.return_value = {"claude-1": own_entry}
    rc = al.cmd_release(42, "claude-1", "sess-A")
    assert rc == 0
    call_payload = mock_post.call_args[0][1]
    assert call_payload["action"] == "release"
    assert call_payload["agent"] == "claude-1"


@patch("agent_lock._post_comment")
@patch("agent_lock.get_lock_status")
def test_release_not_locked_is_noop(mock_status: MagicMock, mock_post: MagicMock) -> None:
    mock_status.return_value = {}
    rc = al.cmd_release(42, "claude-1", "sess-A")
    assert rc == 0
    mock_post.assert_not_called()


@patch("agent_lock._post_comment")
@patch("agent_lock.get_lock_status")
def test_release_wrong_session_denied(mock_status: MagicMock, mock_post: MagicMock) -> None:
    other_entry = _locked_entry("claude-1", "sess-B")
    mock_status.return_value = {"claude-1": other_entry}
    rc = al.cmd_release(42, "claude-1", "sess-A")
    assert rc == 1
    mock_post.assert_not_called()


@patch("agent_lock._post_comment")
@patch("agent_lock.get_lock_status")
def test_release_expired_lock_is_noop(mock_status: MagicMock, mock_post: MagicMock) -> None:
    expired = {"action": "acquire", "agent": "claude-1", "session": "sess-A",
               "expires": _iso(_now() - timedelta(hours=1)), "ts": _iso(_now())}
    mock_status.return_value = {"claude-1": expired}
    rc = al.cmd_release(42, "claude-1", "sess-A")
    assert rc == 0
    mock_post.assert_not_called()


# ── Command: cmd_release_all ──────────────────────────────────


@patch("agent_lock._post_comment")
@patch("agent_lock.get_lock_status")
def test_release_all_own_locks(mock_status: MagicMock, mock_post: MagicMock) -> None:
    state = {
        "claude-1": _locked_entry("claude-1", "sess-A"),
        "codex-2": _locked_entry("codex-2", "sess-A"),
    }
    mock_status.return_value = state
    rc = al.cmd_release_all(42, "sess-A")
    assert rc == 0
    assert mock_post.call_count == 2
    released_agents = {c[0][1]["agent"] for c in mock_post.call_args_list}
    assert released_agents == {"claude-1", "codex-2"}


@patch("agent_lock._post_comment")
@patch("agent_lock.get_lock_status")
def test_release_all_skips_other_sessions(mock_status: MagicMock, mock_post: MagicMock) -> None:
    state = {
        "claude-1": _locked_entry("claude-1", "sess-A"),
        "codex-2": _locked_entry("codex-2", "sess-OTHER"),
    }
    mock_status.return_value = state
    rc = al.cmd_release_all(42, "sess-A")
    assert rc == 0
    assert mock_post.call_count == 1
    call_payload = mock_post.call_args[0][1]
    assert call_payload["agent"] == "claude-1"


@patch("agent_lock._post_comment")
@patch("agent_lock.get_lock_status")
def test_release_all_no_locks_held(mock_status: MagicMock, mock_post: MagicMock) -> None:
    mock_status.return_value = {}
    rc = al.cmd_release_all(42, "sess-A")
    assert rc == 0
    mock_post.assert_not_called()


# ── Command: cmd_status ───────────────────────────────────────


@patch("agent_lock.get_lock_status")
def test_status_shows_locked_and_free(mock_status: MagicMock, capsys: pytest.CaptureFixture) -> None:
    state = {
        "claude-1": _locked_entry("claude-1", "sess-A"),
        "codex-2": {"action": "release", "agent": "codex-2", "session": "sess-B", "ts": _iso(_now())},
    }
    mock_status.return_value = state
    rc = al.cmd_status(42)
    assert rc == 0
    out = capsys.readouterr().out
    assert "LOCKED" in out
    assert "sess-A" in out
    assert "free" in out


@patch("agent_lock.get_lock_status")
def test_status_empty(mock_status: MagicMock, capsys: pytest.CaptureFixture) -> None:
    mock_status.return_value = {}
    rc = al.cmd_status(42)
    assert rc == 0
    out = capsys.readouterr().out
    assert "no locks" in out


# ── TTL / expiry ──────────────────────────────────────────────


def test_lock_expires_after_ttl() -> None:
    """Lock that was acquired 1s ago with 1s TTL is expired now."""
    past = _now() - timedelta(seconds=2)
    entry = {"action": "acquire", "agent": "claude-1", "session": "sess-A",
             "expires": _iso(past), "ts": _iso(past)}
    assert al._is_locked(entry, _now()) is False


def test_lock_active_before_ttl() -> None:
    """Lock that expires 1h from now is still active."""
    entry = _locked_entry("claude-1", "sess-A", minutes_ahead=60)
    assert al._is_locked(entry, _now()) is True


# ── Error path: _find_lock_issue ─────────────────────────────


@patch("agent_lock._find_lock_issue", return_value=None)
def test_main_no_lock_issue_returns_2(mock_find: MagicMock, capsys: pytest.CaptureFixture) -> None:
    """If no 'agent-locks' issue exists, main exits with code 2."""
    import sys as _sys
    orig = _sys.argv[:]
    _sys.argv = ["agent_lock.py", "status"]
    try:
        rc = al.main()
    except SystemExit as e:
        rc = e.code
    finally:
        _sys.argv = orig
    assert rc == 2


@patch("agent_lock.get_lock_status", side_effect=al.FetchError("network error"))
@patch("agent_lock._find_lock_issue", return_value=42)
def test_main_fetch_error_returns_2(mock_find: MagicMock, mock_status: MagicMock, capsys: pytest.CaptureFixture) -> None:
    """FetchError during a command propagates as exit code 2."""
    import sys as _sys
    orig = _sys.argv[:]
    _sys.argv = ["agent_lock.py", "status"]
    try:
        rc = al.main()
    except SystemExit as e:
        rc = e.code
    finally:
        _sys.argv = orig
    assert rc == 2
    err = capsys.readouterr().err
    assert "ERROR" in err
