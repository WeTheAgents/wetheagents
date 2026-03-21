"""Tests for wea trace emit — 12 GWT requirements from spec."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from wea_cli.trace import emit_event, validate_event

# ---- Fixtures ----


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    """Create a run directory inside a .wea_runs parent."""
    runs = tmp_path / ".wea_runs"
    runs.mkdir()
    d = runs / "test-run-001"
    d.mkdir()
    return d


@pytest.fixture
def fixed_now() -> datetime:
    """Fixed timestamp for deterministic tests."""
    return datetime(2026, 3, 15, 12, 0, 0, tzinfo=timezone.utc)


# ---- GWT 1: Basic emit ----


def test_basic_emit(run_dir: Path, fixed_now: datetime) -> None:
    """Given a valid run dir, when emit is called, then exit=0 equivalent,
    events.jsonl has 1 line with 5 keys, timestamp ends in 'Z'."""
    event = emit_event(
        run_dir=run_dir,
        event_type="run_started",
        source="test-agent",
        payload={"step": 1},
        now=fixed_now,
    )

    events_path = run_dir / "events.jsonl"
    assert events_path.exists()
    lines = events_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1

    parsed = json.loads(lines[0])
    assert set(parsed.keys()) == {"timestamp", "run_id", "event_type", "source", "payload"}
    assert parsed["timestamp"].endswith("Z")
    assert parsed["event_type"] == "run_started"
    assert parsed["source"] == "test-agent"
    assert parsed["payload"] == {"step": 1}


# ---- GWT 2: First emit creates status.json ----


def test_first_emit_creates_status(run_dir: Path, fixed_now: datetime) -> None:
    """Given no prior events, when first emit, then status.json is created
    with run_id, last_event_type, event_count=1, last_updated."""
    emit_event(
        run_dir=run_dir,
        event_type="run_started",
        source="agent",
        payload={},
        now=fixed_now,
    )

    status_path = run_dir / "status.json"
    assert status_path.exists()
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["run_id"] == run_dir.name
    assert status["last_event_type"] == "run_started"
    assert status["event_count"] == 1
    assert status["last_updated"] == "2026-03-15T12:00:00Z"


# ---- GWT 3: Unknown event_type ----


def test_unknown_event_type_rejected(run_dir: Path, fixed_now: datetime) -> None:
    """Given unknown event_type 'banana', when emit, then ValueError with message,
    no files written."""
    with pytest.raises(ValueError, match="Unknown event_type: banana"):
        emit_event(
            run_dir=run_dir,
            event_type="banana",
            source="agent",
            payload={},
            now=fixed_now,
        )

    # No files should have been written
    assert not (run_dir / "events.jsonl").exists()
    assert not (run_dir / "status.json").exists()


# ---- GWT 4: Missing fields ----


def test_missing_field_raises_valueerror() -> None:
    """Given event dict missing a required field, then ValueError naming it."""
    incomplete = {
        "timestamp": "2026-03-15T12:00:00Z",
        "run_id": "test",
        "event_type": "run_started",
        # missing: source, payload
    }
    with pytest.raises(ValueError, match="Missing field: source"):
        validate_event(incomplete)


def test_missing_payload_raises_valueerror() -> None:
    """Given event dict missing payload, then ValueError naming 'payload'."""
    incomplete = {
        "timestamp": "2026-03-15T12:00:00Z",
        "run_id": "test",
        "event_type": "run_started",
        "source": "agent",
        # missing: payload
    }
    with pytest.raises(ValueError, match="Missing field: payload"):
        validate_event(incomplete)


# ---- GWT 5: Atomic status.json ----


def test_atomic_status_write(run_dir: Path, fixed_now: datetime) -> None:
    """Given sequential emits, then status.json updated atomically via
    temp + os.replace(), event_count increments, no temp files left."""
    emit_event(run_dir=run_dir, event_type="run_started", source="a", payload={}, now=fixed_now)
    emit_event(run_dir=run_dir, event_type="heartbeat", source="a", payload={}, now=fixed_now)

    status = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
    assert status["event_count"] == 2
    assert status["last_event_type"] == "heartbeat"

    # No temp files should remain
    temps = [f for f in os.listdir(run_dir) if f.startswith(".status_") and f.endswith(".tmp")]
    assert temps == []


# ---- GWT 6: Missing run directory ----


def test_missing_run_dir_exits_error(tmp_path: Path, fixed_now: datetime) -> None:
    """Given run dir does not exist, then ValueError 'Run directory not found',
    NO auto-create."""
    nonexistent = tmp_path / ".wea_runs" / "ghost-run"

    with pytest.raises(ValueError, match="Run directory not found"):
        emit_event(
            run_dir=nonexistent,
            event_type="run_started",
            source="agent",
            payload={},
            now=fixed_now,
        )

    # Must NOT auto-create
    assert not nonexistent.exists()


# ---- GWT 7: Sequential emits append-only ----


def test_sequential_emits_append_only(run_dir: Path, fixed_now: datetime) -> None:
    """Given 3 sequential emits, then events.jsonl has 3 lines, event_count=3."""
    for etype in ("run_started", "heartbeat", "milestone"):
        emit_event(run_dir=run_dir, event_type=etype, source="a", payload={}, now=fixed_now)

    lines = (run_dir / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3

    status = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
    assert status["event_count"] == 3
    assert status["last_event_type"] == "milestone"

    # Verify each line is a distinct event
    types = [json.loads(line)["event_type"] for line in lines]
    assert types == ["run_started", "heartbeat", "milestone"]


# ---- GWT 8: Payload as native JSON object ----


def test_payload_is_native_json_object(run_dir: Path, fixed_now: datetime) -> None:
    """Given payload dict, then stored as native JSON object, not string-escaped."""
    emit_event(
        run_dir=run_dir,
        event_type="milestone",
        source="agent",
        payload={"key": "value", "nested": {"n": 1}},
        now=fixed_now,
    )

    line = (run_dir / "events.jsonl").read_text(encoding="utf-8").strip()
    parsed = json.loads(line)
    # payload must be a dict, not a string
    assert isinstance(parsed["payload"], dict)
    assert parsed["payload"]["key"] == "value"
    assert parsed["payload"]["nested"] == {"n": 1}


# ---- GWT 9: Invalid payload JSON (CLI level) ----


def test_cli_invalid_payload_json(run_dir: Path) -> None:
    """Given invalid JSON payload string via CLI, then exit=1, 'Invalid JSON',
    no event written."""
    result = subprocess.run(
        [
            sys.executable, "-m", "wea_cli.cli",
            "trace", "emit",
            str(run_dir), "run_started", "agent", "not-valid-json{{{",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "Invalid JSON" in result.stdout or "Invalid JSON" in result.stderr

    assert not (run_dir / "events.jsonl").exists()


# ---- GWT 10: Path traversal in run_id ----


def test_path_traversal_slash_rejected(tmp_path: Path, fixed_now: datetime) -> None:
    """Given run_id containing '/', then ValueError, no files."""
    from wea_cli.trace import _validate_run_id

    with pytest.raises(ValueError, match="path traversal"):
        _validate_run_id("evil/path")

    with pytest.raises(ValueError, match="path traversal"):
        _validate_run_id("evil\\path")


def test_path_traversal_dotdot_rejected(tmp_path: Path, fixed_now: datetime) -> None:
    """Given run_id containing '..', then ValueError, no files."""
    evil_dir = tmp_path / "..sneaky"
    evil_dir.mkdir(parents=True)

    with pytest.raises(ValueError, match="path traversal"):
        emit_event(
            run_dir=evil_dir,
            event_type="run_started",
            source="agent",
            payload={},
            now=fixed_now,
        )


# ---- GWT bonus: CLI integration (basic happy path) ----


def test_cli_basic_emit(run_dir: Path) -> None:
    """Given valid args via CLI, then exit=0 and event written."""
    result = subprocess.run(
        [
            sys.executable, "-m", "wea_cli.cli",
            "trace", "emit",
            str(run_dir), "run_started", "cli-test", '{"ok": true}',
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0

    events_path = run_dir / "events.jsonl"
    assert events_path.exists()
    parsed = json.loads(events_path.read_text(encoding="utf-8").strip())
    assert parsed["event_type"] == "run_started"
    assert parsed["payload"] == {"ok": True}
