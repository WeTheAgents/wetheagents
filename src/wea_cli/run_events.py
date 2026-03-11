from __future__ import annotations

from contextlib import contextmanager
import json
import os
import tempfile
from datetime import datetime, timezone
from io import BufferedRandom
from pathlib import Path
from typing import Any

if os.name == "nt":
    import msvcrt
else:
    import fcntl

KNOWN_EVENT_TYPES = {
    "run_started",
    "heartbeat",
    "run_completed",
    "run_failed",
    "run_timeout",
    "milestone",
    "warning",
    "error",
    "auth_ok",
    "auth_failed",
    "tool_started",
    "tool_finished",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso_utc(value: str) -> str:
    raw = value.strip()
    if not raw:
        raise ValueError("timestamp must not be empty")
    normalized = raw.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_event(event: dict[str, Any]) -> dict[str, Any]:
    timestamp = _parse_iso_utc(str(event.get("timestamp", "")))
    run_id = str(event.get("run_id", "")).strip()
    event_type = str(event.get("event_type", "")).strip()
    source = str(event.get("source", "")).strip()
    payload = event.get("payload", {})

    if not run_id:
        raise ValueError("run_id is required")
    if not event_type:
        raise ValueError("event_type is required")
    if event_type not in KNOWN_EVENT_TYPES:
        raise ValueError(f"unknown event_type: {event_type}")
    if not source:
        raise ValueError("source is required")
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")

    normalized = dict(event)
    normalized["timestamp"] = timestamp
    normalized["run_id"] = run_id
    normalized["event_type"] = event_type
    normalized["source"] = source
    normalized["payload"] = payload
    return normalized


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(rendered)
            temp_name = handle.name
        os.replace(temp_name, path)
    except Exception:
        if temp_name:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
        raise


def _lock_handle(handle: BufferedRandom) -> None:
    handle.seek(0)
    if os.name == "nt":
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        return
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _unlock_handle(handle: BufferedRandom) -> None:
    handle.seek(0)
    if os.name == "nt":
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def _run_lock(run_dir: Path):
    lock_path = run_dir / ".trace.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        _lock_handle(handle)
        try:
            yield
        finally:
            _unlock_handle(handle)


def _derive_status(event_type: str, current_status: str | None) -> str:
    if event_type == "run_started":
        return "running"
    if event_type in {"run_completed"}:
        return "completed"
    if event_type in {"run_failed", "auth_failed", "error"}:
        return "failed"
    if event_type == "run_timeout":
        return "timeout"
    if event_type == "heartbeat":
        return current_status or "running"
    return current_status or "running"


def update_status_snapshot(existing: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    event_count = int(existing.get("event_count", 0) or 0) + 1
    started_at = str(existing.get("started_at", "")).strip() or event["timestamp"]
    current_status = str(existing.get("status", "")).strip() or None

    snapshot: dict[str, Any] = dict(existing)
    snapshot["run_id"] = event["run_id"]
    snapshot["status"] = _derive_status(event["event_type"], current_status)
    snapshot["started_at"] = started_at
    snapshot["last_event_at"] = event["timestamp"]
    snapshot["last_event_type"] = event["event_type"]
    snapshot["last_source"] = event["source"]
    snapshot["event_count"] = event_count
    snapshot["last_payload"] = event["payload"]
    return snapshot


def emit_event(run_dir: Path, event: dict[str, Any]) -> dict[str, Any]:
    if not run_dir.exists():
        raise FileNotFoundError(f"Run directory not found: {run_dir}")
    if not run_dir.is_dir():
        raise ValueError(f"Run path is not a directory: {run_dir}")

    normalized = validate_event(event)
    if run_dir.resolve().name != normalized["run_id"]:
        raise ValueError(
            f"run_id {normalized['run_id']!r} does not match run directory name {run_dir.name!r}"
        )

    with _run_lock(run_dir):
        events_path = run_dir / "events.jsonl"
        with events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(normalized, ensure_ascii=False) + "\n")

        status_path = run_dir / "status.json"
        snapshot = update_status_snapshot(_load_json(status_path), normalized)
        _write_json_atomic(status_path, snapshot)
        return snapshot
