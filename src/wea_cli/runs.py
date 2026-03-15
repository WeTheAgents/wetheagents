"""Read-only inspection of .wea_runs/ run directories."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_run_snapshot(run_dir: Path) -> dict[str, Any]:
    """Read supervisor.json and status.json from a run directory.

    Returns a 6-field dict. Never crashes: missing files, corrupt JSON,
    and missing keys all fall back to documented defaults.

    Fields:
        run_id       — from supervisor.json, fallback to directory name
        status       — from supervisor.json, default "unknown"
        started_at   — from supervisor.json, default None
        last_event_at — from status.json last_updated, default None
        command      — from supervisor.json, default None
        event_count  — from status.json, default 0
    """
    snapshot: dict[str, Any] = {
        "run_id": run_dir.name,
        "status": "unknown",
        "started_at": None,
        "last_event_at": None,
        "command": None,
        "event_count": 0,
    }

    # Read supervisor.json
    supervisor_path = run_dir / "supervisor.json"
    if supervisor_path.exists():
        try:
            supervisor = json.loads(supervisor_path.read_text(encoding="utf-8"))
            if isinstance(supervisor, dict):
                if "run_id" in supervisor:
                    snapshot["run_id"] = supervisor["run_id"]
                if "status" in supervisor:
                    snapshot["status"] = supervisor["status"]
                if "started_at" in supervisor:
                    snapshot["started_at"] = supervisor["started_at"]
                if "command" in supervisor:
                    snapshot["command"] = supervisor["command"]
        except (json.JSONDecodeError, OSError, ValueError):
            # Corrupt or unreadable — leave defaults in place
            pass

    # Read status.json
    status_path = run_dir / "status.json"
    if status_path.exists():
        try:
            status = json.loads(status_path.read_text(encoding="utf-8"))
            if isinstance(status, dict):
                if "last_updated" in status:
                    snapshot["last_event_at"] = status["last_updated"]
                if "event_count" in status:
                    snapshot["event_count"] = status["event_count"]
        except (json.JSONDecodeError, OSError, ValueError):
            # Corrupt or unreadable — leave defaults in place
            pass

    return snapshot


def list_runs(runs_base: Path) -> list[dict[str, Any]]:
    """List all run directories under runs_base.

    Returns a list of snapshots (from read_run_snapshot) sorted newest-first
    by started_at. Entries with started_at=None are sorted last.
    Non-directory entries are silently skipped.
    If runs_base does not exist, returns an empty list.
    """
    if not runs_base.exists() or not runs_base.is_dir():
        return []

    snapshots: list[dict[str, Any]] = []
    for entry in runs_base.iterdir():
        if not entry.is_dir():
            continue
        snapshot = read_run_snapshot(entry)
        snapshots.append(snapshot)

    # Sort newest-first: None values go last
    snapshots.sort(
        key=lambda s: (s["started_at"] is None, s["started_at"] or ""),
        reverse=False,
    )
    # After the sort key above: (False, timestamp) sorts before (True, "").
    # We want newest-first, so reverse the non-None group while keeping None last.
    # Simpler: sort by (is_none, reverse_timestamp)
    snapshots.sort(
        key=lambda s: (s["started_at"] is None, _negate_str(s["started_at"])),
    )

    return snapshots


def _negate_str(s: str | None) -> str:
    """Return a string that sorts in reverse ISO order when sorted ascending.

    Timestamps are ISO 8601 (sortable lexicographically). We negate by
    XOR-ing each character with 0xFF to invert the sort order.
    None is handled by the caller (is_none flag).
    """
    if s is None:
        return ""
    # Flip each character: chr(0xFF - ord(c)) gives reversed lex order for ASCII
    return "".join(chr(0xFF - ord(c)) for c in s)


def format_runs_table(snapshots: list[dict[str, Any]]) -> str:
    """Format a human-readable table of run snapshots.

    Columns: RUN_ID, STATUS, STARTED, EVENTS, COMMAND
    Command is truncated to 60 characters.
    Header is always printed, even with zero runs.
    """
    COMMAND_MAX = 60
    header = f"{'RUN_ID':<45}  {'STATUS':<10}  {'STARTED':<20}  {'EVENTS':>6}  COMMAND"
    separator = "-" * len(header)
    lines = [header, separator]

    for s in snapshots:
        run_id = str(s.get("run_id") or "")
        status = str(s.get("status") or "")
        started = str(s.get("started_at") or "")[:19]  # trim to YYYY-MM-DDTHH:MM:SS
        event_count = int(s.get("event_count") or 0)
        command = str(s.get("command") or "")
        if len(command) > COMMAND_MAX:
            command = command[:COMMAND_MAX - 3] + "..."

        lines.append(
            f"{run_id:<45}  {status:<10}  {started:<20}  {event_count:>6}  {command}"
        )

    return "\n".join(lines)
