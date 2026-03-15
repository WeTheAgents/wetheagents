"""Tests for hooks_adapter — Claude Code hook → wea trace event translation."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from wea_cli.hooks_adapter import handle_hook


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run_dir(tmp_path: Path) -> Path:
    """Create a minimal run directory structure."""
    runs = tmp_path / ".wea_runs"
    runs.mkdir()
    run_dir = runs / "test-run-001"
    run_dir.mkdir()
    return run_dir


def _read_events(run_dir: Path) -> list[dict]:
    """Read all events from events.jsonl in the run directory."""
    events_path = run_dir / "events.jsonl"
    if not events_path.exists():
        return []
    return [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").strip().splitlines()
        if line.strip()
    ]


# ---------------------------------------------------------------------------
# Fixture payloads
# ---------------------------------------------------------------------------

SESSION_START_PAYLOAD = {
    "session_id": "abc123",
    "hook_event_name": "SessionStart",
    "cwd": "/tmp",
    "model": "claude-sonnet-4-6",
    "source": "startup",
    "permission_mode": "default",
    "transcript_path": "/tmp/abc.jsonl",
}

PRE_TOOL_USE_BASH_PAYLOAD = {
    "session_id": "abc123",
    "hook_event_name": "PreToolUse",
    "cwd": "/tmp",
    "tool_name": "Bash",
    "tool_use_id": "toolu_01ABC",
    "tool_input": {"command": "npm test", "description": "Run tests"},
    "permission_mode": "default",
    "transcript_path": "/tmp/abc.jsonl",
}

POST_TOOL_USE_WRITE_PAYLOAD = {
    "session_id": "abc123",
    "hook_event_name": "PostToolUse",
    "cwd": "/tmp",
    "tool_name": "Write",
    "tool_use_id": "toolu_01DEF",
    "tool_input": {"file_path": "/src/main.py", "content": "..."},
    "tool_response": {"filePath": "/src/main.py", "success": True},
    "permission_mode": "default",
    "transcript_path": "/tmp/abc.jsonl",
}

STOP_PAYLOAD = {
    "session_id": "abc123",
    "hook_event_name": "Stop",
    "cwd": "/tmp",
    "stop_hook_active": False,
    "last_assistant_message": "Done.",
    "permission_mode": "default",
    "transcript_path": "/tmp/abc.jsonl",
}

SUBAGENT_STOP_PAYLOAD = {
    "session_id": "abc123",
    "hook_event_name": "SubagentStop",
    "cwd": "/tmp",
    "stop_hook_active": False,
    "agent_id": "def456",
    "agent_type": "Explore",
    "agent_transcript_path": "/tmp/sub.jsonl",
    "last_assistant_message": "Found issues.",
    "permission_mode": "default",
    "transcript_path": "/tmp/abc.jsonl",
}


# ---------------------------------------------------------------------------
# Test 1: SessionStart → auth_ok
# ---------------------------------------------------------------------------


def test_session_start_emits_auth_ok(tmp_path: Path) -> None:
    """Given a SessionStart payload, handle_hook emits an auth_ok event."""
    run_dir = _make_run_dir(tmp_path)

    rc = handle_hook(SESSION_START_PAYLOAD, run_dir=run_dir)

    assert rc == 0
    events = _read_events(run_dir)
    assert len(events) == 1
    event = events[0]
    assert event["event_type"] == "auth_ok"
    assert event["source"] == "wea-hooks"
    assert event["payload"]["session_id"] == "abc123"
    assert event["payload"]["model"] == "claude-sonnet-4-6"
    assert event["payload"]["source"] == "startup"


# ---------------------------------------------------------------------------
# Test 2: PreToolUse (Bash) → tool_started with command summary
# ---------------------------------------------------------------------------


def test_pre_tool_use_bash_emits_tool_started(tmp_path: Path) -> None:
    """Given a PreToolUse/Bash payload, handle_hook emits tool_started with command summary."""
    run_dir = _make_run_dir(tmp_path)

    rc = handle_hook(PRE_TOOL_USE_BASH_PAYLOAD, run_dir=run_dir)

    assert rc == 0
    events = _read_events(run_dir)
    assert len(events) == 1
    event = events[0]
    assert event["event_type"] == "tool_started"
    assert event["source"] == "wea-hooks"
    payload = event["payload"]
    assert payload["tool_name"] == "Bash"
    assert payload["tool_use_id"] == "toolu_01ABC"
    assert payload["tool_input_summary"] == "npm test"


# ---------------------------------------------------------------------------
# Test 3: PostToolUse (Write) → tool_finished with file_path reflected in tool_name
# ---------------------------------------------------------------------------


def test_post_tool_use_write_emits_tool_finished(tmp_path: Path) -> None:
    """Given a PostToolUse/Write payload, handle_hook emits tool_finished with success."""
    run_dir = _make_run_dir(tmp_path)

    rc = handle_hook(POST_TOOL_USE_WRITE_PAYLOAD, run_dir=run_dir)

    assert rc == 0
    events = _read_events(run_dir)
    assert len(events) == 1
    event = events[0]
    assert event["event_type"] == "tool_finished"
    assert event["source"] == "wea-hooks"
    payload = event["payload"]
    assert payload["tool_name"] == "Write"
    assert payload["tool_use_id"] == "toolu_01DEF"
    assert payload["success"] is True


# ---------------------------------------------------------------------------
# Test 4: Stop → run_completed
# ---------------------------------------------------------------------------


def test_stop_emits_run_completed(tmp_path: Path) -> None:
    """Given a Stop payload, handle_hook emits a run_completed event."""
    run_dir = _make_run_dir(tmp_path)

    rc = handle_hook(STOP_PAYLOAD, run_dir=run_dir)

    assert rc == 0
    events = _read_events(run_dir)
    assert len(events) == 1
    event = events[0]
    assert event["event_type"] == "run_completed"
    assert event["source"] == "wea-hooks"
    payload = event["payload"]
    assert payload["session_id"] == "abc123"
    assert payload["stop_hook_active"] is False


# ---------------------------------------------------------------------------
# Test 5: SubagentStop → milestone
# ---------------------------------------------------------------------------


def test_subagent_stop_emits_milestone(tmp_path: Path) -> None:
    """Given a SubagentStop payload, handle_hook emits a milestone event."""
    run_dir = _make_run_dir(tmp_path)

    rc = handle_hook(SUBAGENT_STOP_PAYLOAD, run_dir=run_dir)

    assert rc == 0
    events = _read_events(run_dir)
    assert len(events) == 1
    event = events[0]
    assert event["event_type"] == "milestone"
    assert event["source"] == "wea-hooks"
    payload = event["payload"]
    assert payload["milestone"] == "subagent_completed"
    assert payload["agent_type"] == "Explore"
    assert payload["agent_id"] == "def456"


# ---------------------------------------------------------------------------
# Test 6: Malformed payload (no hook_event_name) → fail open, return 0
# ---------------------------------------------------------------------------


def test_missing_hook_event_name_fails_open(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Given a payload without hook_event_name, handle_hook returns 0 and emits no event."""
    run_dir = _make_run_dir(tmp_path)
    malformed = {"session_id": "abc123", "cwd": "/tmp"}

    rc = handle_hook(malformed, run_dir=run_dir)

    assert rc == 0
    events = _read_events(run_dir)
    assert len(events) == 0
    captured = capsys.readouterr()
    assert "warning" in captured.err.lower() or "missing" in captured.err.lower()


# ---------------------------------------------------------------------------
# Test 7: Unknown hook_event_name → fail open, return 0, no event
# ---------------------------------------------------------------------------


def test_unknown_hook_event_name_fails_open(tmp_path: Path) -> None:
    """Given an unknown hook_event_name, handle_hook returns 0 without emitting an event."""
    run_dir = _make_run_dir(tmp_path)
    unknown = {
        "hook_event_name": "FutureUnknownHook",
        "session_id": "abc123",
        "cwd": "/tmp",
    }

    rc = handle_hook(unknown, run_dir=run_dir)

    assert rc == 0
    events = _read_events(run_dir)
    assert len(events) == 0


# ---------------------------------------------------------------------------
# Test 8: Missing WEA_RUN_DIR (no run_dir arg) → fail open, return 0
# ---------------------------------------------------------------------------


def test_missing_run_dir_env_fails_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Given no run_dir arg and no WEA_RUN_DIR env var, handle_hook returns 0 without error."""
    monkeypatch.delenv("WEA_RUN_DIR", raising=False)

    rc = handle_hook(SESSION_START_PAYLOAD, run_dir=None)

    assert rc == 0


# ---------------------------------------------------------------------------
# Bonus test 9: WEA_RUN_DIR env var is used when run_dir=None
# ---------------------------------------------------------------------------


def test_env_run_dir_used_when_arg_is_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Given WEA_RUN_DIR env var set, handle_hook uses it when run_dir=None."""
    run_dir = _make_run_dir(tmp_path)
    monkeypatch.setenv("WEA_RUN_DIR", str(run_dir))

    rc = handle_hook(SESSION_START_PAYLOAD, run_dir=None)

    assert rc == 0
    events = _read_events(run_dir)
    assert len(events) == 1
    assert events[0]["event_type"] == "auth_ok"


# ---------------------------------------------------------------------------
# Bonus test 10: Bash command truncated to 100 chars in tool_input_summary
# ---------------------------------------------------------------------------


def test_bash_command_truncated_to_100_chars(tmp_path: Path) -> None:
    """Given a Bash tool_input with command longer than 100 chars, summary is truncated."""
    run_dir = _make_run_dir(tmp_path)
    long_command = "echo " + "a" * 200
    payload = {
        **PRE_TOOL_USE_BASH_PAYLOAD,
        "tool_input": {"command": long_command},
    }

    rc = handle_hook(payload, run_dir=run_dir)

    assert rc == 0
    events = _read_events(run_dir)
    assert len(events) == 1
    summary = events[0]["payload"]["tool_input_summary"]
    assert len(summary) == 100
    assert summary == long_command[:100]


# ---------------------------------------------------------------------------
# Bonus test 11: PostToolUse without tool_response.success defaults to True
# ---------------------------------------------------------------------------


def test_post_tool_use_no_success_field_defaults_true(tmp_path: Path) -> None:
    """Given PostToolUse payload with no tool_response.success, success defaults to True."""
    run_dir = _make_run_dir(tmp_path)
    payload = {
        "session_id": "abc123",
        "hook_event_name": "PostToolUse",
        "cwd": "/tmp",
        "tool_name": "Bash",
        "tool_use_id": "toolu_01XYZ",
        "tool_input": {"command": "ls"},
        "tool_response": {"output": "file.txt"},  # no "success" key
        "permission_mode": "default",
        "transcript_path": "/tmp/abc.jsonl",
    }

    rc = handle_hook(payload, run_dir=run_dir)

    assert rc == 0
    events = _read_events(run_dir)
    assert len(events) == 1
    assert events[0]["payload"]["success"] is True


# ---------------------------------------------------------------------------
# Bonus test 12: CLI integration — wea hooks handle reads from stdin
# ---------------------------------------------------------------------------


def test_cli_hooks_handle_session_start(tmp_path: Path) -> None:
    """Given valid SessionStart JSON on stdin, wea hooks handle exits 0 and emits event."""
    run_dir = _make_run_dir(tmp_path)
    payload_json = json.dumps(SESSION_START_PAYLOAD)

    result = subprocess.run(
        [sys.executable, "-m", "wea_cli.cli", "hooks", "handle"],
        input=payload_json,
        capture_output=True,
        text=True,
        env={**__import__("os").environ, "WEA_RUN_DIR": str(run_dir)},
    )

    assert result.returncode == 0
    events = _read_events(run_dir)
    assert len(events) == 1
    assert events[0]["event_type"] == "auth_ok"
