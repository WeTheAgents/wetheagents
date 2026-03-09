from __future__ import annotations

import json
from pathlib import Path
import threading
import time

import pytest

from wea_cli import run_events
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


def test_emit_event_serializes_status_updates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run_dir = _make_run_dir(tmp_path)
    real_load_json = run_events._load_json
    first_reader_entered = threading.Event()
    release_first_reader = threading.Event()
    call_count = 0
    call_lock = threading.Lock()
    errors: list[BaseException] = []

    def delayed_load_json(path: Path) -> dict[str, object]:
        nonlocal call_count
        with call_lock:
            call_count += 1
            current_call = call_count
        if current_call == 1:
            first_reader_entered.set()
            assert release_first_reader.wait(timeout=2)
        return real_load_json(path)

    monkeypatch.setattr(run_events, "_load_json", delayed_load_json)

    def worker(event: dict[str, object]) -> None:
        try:
            emit_event(run_dir, event)
        except BaseException as exc:  # pragma: no cover - failure path asserted below
            errors.append(exc)

    first = threading.Thread(
        target=worker,
        args=(
            {
                "timestamp": "2026-03-09T14:00:00Z",
                "run_id": "run_123",
                "event_type": "run_started",
                "source": "cli",
                "payload": {"step": 1},
            },
        ),
    )
    second = threading.Thread(
        target=worker,
        args=(
            {
                "timestamp": "2026-03-09T14:00:01Z",
                "run_id": "run_123",
                "event_type": "run_failed",
                "source": "cli",
                "payload": {"step": 2},
            },
        ),
    )

    first.start()
    assert first_reader_entered.wait(timeout=2)
    second.start()
    time.sleep(0.05)
    release_first_reader.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert not errors
    status = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
    assert status["event_count"] == 2
    assert status["status"] == "failed"
    assert status["last_event_type"] == "run_failed"

    lines = (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
