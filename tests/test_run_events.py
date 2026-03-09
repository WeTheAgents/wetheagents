from __future__ import annotations

import json
from pathlib import Path

import pytest

from wea_cli.run_events import emit_event, update_status_snapshot, validate_event


def _make_run_dir(tmp_path: Path, run_id: str = "run_123") -> Path:
    run_dir = tmp_path / ".wea_runs" / run_id
    run_dir.mkdir(parents=True)
    return run_dir


def test_validate_event_rejects_unknown_type() -> None:
    with pytest.raises(ValueError, match="unknown event_type"):
        validate_event(
            {
                "timestamp": "2026-03-09T14:00:00Z",
                "run_id": "run_123",
                "event_type": "unknown",
                "source": "cli",
                "payload": {},
            }
        )


def test_validate_event_requires_object_payload() -> None:
    with pytest.raises(ValueError, match="payload must be an object"):
        validate_event(
            {
                "timestamp": "2026-03-09T14:00:00Z",
                "run_id": "run_123",
                "event_type": "run_started",
                "source": "cli",
                "payload": [],
            }
        )


def test_emit_event_appends_and_updates_status(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path)

    first = emit_event(
        run_dir,
        {
            "timestamp": "2026-03-09T14:00:00Z",
            "run_id": "run_123",
            "event_type": "run_started",
            "source": "cli",
            "payload": {"command": "demo"},
        },
    )
    second = emit_event(
        run_dir,
        {
            "timestamp": "2026-03-09T14:01:00Z",
            "run_id": "run_123",
            "event_type": "heartbeat",
            "source": "cli",
            "payload": {"pid": 42},
        },
    )

    events_path = run_dir / "events.jsonl"
    lines = events_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["event_type"] == "run_started"
    assert json.loads(lines[1])["event_type"] == "heartbeat"

    assert first["status"] == "running"
    assert second["status"] == "running"
    assert second["started_at"] == "2026-03-09T14:00:00Z"
    assert second["last_event_at"] == "2026-03-09T14:01:00Z"
    assert second["event_count"] == 2

    status = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
    assert status == second


def test_emit_event_requires_existing_run_directory(tmp_path: Path) -> None:
    missing = tmp_path / ".wea_runs" / "run_missing"
    with pytest.raises(FileNotFoundError, match="Run directory not found"):
        emit_event(
            missing,
            {
                "timestamp": "2026-03-09T14:00:00Z",
                "run_id": "run_missing",
                "event_type": "run_started",
                "source": "cli",
                "payload": {},
            },
        )


def test_emit_event_rejects_mismatched_run_id(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path, run_id="run_actual")
    with pytest.raises(ValueError, match="does not match run directory name"):
        emit_event(
            run_dir,
            {
                "timestamp": "2026-03-09T14:00:00Z",
                "run_id": "run_other",
                "event_type": "run_started",
                "source": "cli",
                "payload": {},
            },
        )


def test_update_status_snapshot_marks_failure() -> None:
    snapshot = update_status_snapshot(
        {},
        {
            "timestamp": "2026-03-09T14:00:00Z",
            "run_id": "run_123",
            "event_type": "auth_failed",
            "source": "hook:claude",
            "payload": {"reason": "bad token"},
        },
    )
    assert snapshot["status"] == "failed"
    assert snapshot["event_count"] == 1
