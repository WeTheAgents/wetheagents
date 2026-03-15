"""Trace event emission and local run event store."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

EVENT_TYPES = frozenset({
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
})

REQUIRED_FIELDS = ("timestamp", "run_id", "event_type", "source", "payload")


def validate_event(event: dict) -> None:
    """Validate event dict has all required fields and valid event_type.

    Raises ValueError for missing fields or unknown event_type.
    Must be called BEFORE any I/O.
    """
    for field in REQUIRED_FIELDS:
        if field not in event:
            raise ValueError(f"Missing field: {field}")

    if event["event_type"] not in EVENT_TYPES:
        raise ValueError(f"Unknown event_type: {event['event_type']}")


def _validate_run_id(run_id: str) -> None:
    """Reject path traversal attempts in run_id.

    Raises ValueError if run_id contains /, \\, or ..
    """
    if "/" in run_id or "\\" in run_id or ".." in run_id:
        raise ValueError(f"Invalid run_id (path traversal): {run_id}")


def _atomic_write_status(status_path: Path, status: dict) -> None:
    """Write status.json atomically via tempfile + os.replace()."""
    data = json.dumps(status, indent=2, ensure_ascii=False) + "\n"
    fd, tmp_path = tempfile.mkstemp(
        dir=str(status_path.parent),
        prefix=".status_",
        suffix=".tmp",
    )
    closed = False
    try:
        os.write(fd, data.encode("utf-8"))
        os.close(fd)
        closed = True
        os.replace(tmp_path, str(status_path))
    except BaseException:
        if not closed:
            os.close(fd)
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def emit_event(
    run_dir: Path,
    event_type: str,
    source: str,
    payload: dict,
    now: datetime | None = None,
) -> dict:
    """Emit a trace event to a run directory.

    Args:
        run_dir: Path to the run directory (must already exist).
        event_type: One of EVENT_TYPES.
        source: Source identifier string.
        payload: JSON-serializable dict payload.
        now: Injectable timestamp for testability.

    Returns:
        The validated event dict that was written.

    Raises:
        ValueError: If event_type is unknown, run_id has path traversal,
                    or run directory does not exist.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    run_id = run_dir.name
    _validate_run_id(run_id)

    # Build event
    event = {
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_id": run_id,
        "event_type": event_type,
        "source": source,
        "payload": payload,
    }

    # Validate BEFORE any I/O
    validate_event(event)

    if not run_dir.is_dir():
        raise ValueError("Run directory not found")

    # Append event to events.jsonl
    events_path = run_dir / "events.jsonl"
    with open(events_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")

    # Read current status for event_count
    status_path = run_dir / "status.json"
    if status_path.exists():
        current_status = json.loads(status_path.read_text(encoding="utf-8"))
        event_count = current_status.get("event_count", 0) + 1
    else:
        event_count = 1

    # Write status.json atomically
    status = {
        "run_id": run_id,
        "last_event_type": event_type,
        "last_updated": event["timestamp"],
        "event_count": event_count,
    }
    _atomic_write_status(status_path, status)

    return event
