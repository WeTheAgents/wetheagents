"""Tests for wea runs and wea run-status commands."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from wea_cli.runs import format_runs_table, list_runs, read_run_snapshot

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run_dir(runs_base: Path, run_id: str) -> Path:
    """Create a run directory under runs_base."""
    run_dir = runs_base / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _write_supervisor(run_dir: Path, data: dict) -> None:
    (run_dir / "supervisor.json").write_text(
        json.dumps(data, indent=2), encoding="utf-8"
    )


def _write_status(run_dir: Path, data: dict) -> None:
    (run_dir / "status.json").write_text(
        json.dumps(data, indent=2), encoding="utf-8"
    )


def _make_complete_run(
    runs_base: Path,
    run_id: str,
    status: str = "completed",
    started_at: str = "2026-03-15T12:00:00Z",
    command: str = "echo hello",
    event_count: int = 3,
    last_updated: str = "2026-03-15T12:01:00Z",
) -> Path:
    """Create a run directory with both supervisor.json and status.json."""
    run_dir = _make_run_dir(runs_base, run_id)
    _write_supervisor(run_dir, {
        "run_id": run_id,
        "status": status,
        "started_at": started_at,
        "last_heartbeat_at": None,
        "last_milestone_at": None,
        "pid": 12345,
        "command": command,
    })
    _write_status(run_dir, {
        "run_id": run_id,
        "last_event_type": "run_completed",
        "last_updated": last_updated,
        "event_count": event_count,
    })
    return run_dir


# ---------------------------------------------------------------------------
# Test 1: Single completed run returns correct 6-field output
# ---------------------------------------------------------------------------


def test_single_completed_run_snapshot(tmp_path: Path) -> None:
    """Given a completed run with both files, read_run_snapshot returns all 6 fields correctly."""
    runs_base = tmp_path / ".wea_runs"
    runs_base.mkdir()
    _make_complete_run(
        runs_base,
        run_id="my-run-001",
        status="completed",
        started_at="2026-03-15T12:00:00Z",
        command="wea spawn python script.py",
        event_count=5,
        last_updated="2026-03-15T12:05:00Z",
    )

    snapshot = read_run_snapshot(runs_base / "my-run-001")

    assert snapshot["run_id"] == "my-run-001"
    assert snapshot["status"] == "completed"
    assert snapshot["started_at"] == "2026-03-15T12:00:00Z"
    assert snapshot["last_event_at"] == "2026-03-15T12:05:00Z"
    assert snapshot["command"] == "wea spawn python script.py"
    assert snapshot["event_count"] == 5
    # Exactly 6 keys
    assert set(snapshot.keys()) == {"run_id", "status", "started_at", "last_event_at", "command", "event_count"}


# ---------------------------------------------------------------------------
# Test 2: Two runs sorted newest-first
# ---------------------------------------------------------------------------


def test_two_runs_sorted_newest_first(tmp_path: Path) -> None:
    """Given two runs, list_runs returns them newest started_at first."""
    runs_base = tmp_path / ".wea_runs"
    runs_base.mkdir()
    _make_complete_run(runs_base, "old-run", started_at="2026-03-14T08:00:00Z")
    _make_complete_run(runs_base, "new-run", started_at="2026-03-15T10:00:00Z")

    snapshots = list_runs(runs_base)

    assert len(snapshots) == 2
    assert snapshots[0]["run_id"] == "new-run"
    assert snapshots[1]["run_id"] == "old-run"


# ---------------------------------------------------------------------------
# Test 3: --json flag produces valid JSON array
# ---------------------------------------------------------------------------


def test_json_flag_produces_valid_json_array(tmp_path: Path) -> None:
    """Given --json flag, wea runs outputs a valid JSON array."""
    runs_base = tmp_path / ".wea_runs"
    runs_base.mkdir()
    _make_complete_run(runs_base, "run-abc", event_count=2)

    result = subprocess.run(
        [sys.executable, "-m", "wea_cli.cli", "runs", "--json", "--runs-dir", str(runs_base)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    parsed = json.loads(result.stdout)
    assert isinstance(parsed, list)
    assert len(parsed) == 1
    assert parsed[0]["run_id"] == "run-abc"


# ---------------------------------------------------------------------------
# Test 4: Empty .wea_runs -> empty output, exit 0
# ---------------------------------------------------------------------------


def test_empty_runs_dir_exit_zero(tmp_path: Path) -> None:
    """Given an empty .wea_runs directory, wea runs exits 0 with header-only table."""
    runs_base = tmp_path / ".wea_runs"
    runs_base.mkdir()

    result = subprocess.run(
        [sys.executable, "-m", "wea_cli.cli", "runs", "--runs-dir", str(runs_base)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    # Header should always be present
    assert "RUN_ID" in result.stdout
    assert "STATUS" in result.stdout


# ---------------------------------------------------------------------------
# Test 5: Missing .wea_runs -> empty output, exit 0
# ---------------------------------------------------------------------------


def test_missing_runs_dir_exit_zero(tmp_path: Path) -> None:
    """Given .wea_runs does not exist, wea runs exits 0 with header-only table."""
    nonexistent = tmp_path / ".wea_runs"
    # Do not create it

    result = subprocess.run(
        [sys.executable, "-m", "wea_cli.cli", "runs", "--runs-dir", str(nonexistent)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "RUN_ID" in result.stdout


# ---------------------------------------------------------------------------
# Test 6: Missing status.json -> last_event_at=None, event_count=0
# ---------------------------------------------------------------------------


def test_missing_status_json_defaults(tmp_path: Path) -> None:
    """Given supervisor.json present but status.json missing, snapshot has correct defaults."""
    runs_base = tmp_path / ".wea_runs"
    runs_base.mkdir()
    run_dir = _make_run_dir(runs_base, "run-no-status")
    _write_supervisor(run_dir, {
        "run_id": "run-no-status",
        "status": "running",
        "started_at": "2026-03-15T09:00:00Z",
        "last_heartbeat_at": None,
        "last_milestone_at": None,
        "pid": 9999,
        "command": "python worker.py",
    })
    # No status.json

    snapshot = read_run_snapshot(run_dir)

    assert snapshot["last_event_at"] is None
    assert snapshot["event_count"] == 0
    assert snapshot["status"] == "running"
    assert snapshot["run_id"] == "run-no-status"


# ---------------------------------------------------------------------------
# Test 7: Missing supervisor.json -> status=unknown
# ---------------------------------------------------------------------------


def test_missing_supervisor_json_status_unknown(tmp_path: Path) -> None:
    """Given status.json present but supervisor.json missing, status defaults to unknown."""
    runs_base = tmp_path / ".wea_runs"
    runs_base.mkdir()
    run_dir = _make_run_dir(runs_base, "run-no-supervisor")
    _write_status(run_dir, {
        "run_id": "run-no-supervisor",
        "last_event_type": "heartbeat",
        "last_updated": "2026-03-15T11:00:00Z",
        "event_count": 7,
    })
    # No supervisor.json

    snapshot = read_run_snapshot(run_dir)

    assert snapshot["status"] == "unknown"
    assert snapshot["run_id"] == "run-no-supervisor"  # fallback to directory name
    assert snapshot["last_event_at"] == "2026-03-15T11:00:00Z"
    assert snapshot["event_count"] == 7


# ---------------------------------------------------------------------------
# Test 8: Corrupt supervisor.json -> status=unknown, no crash
# ---------------------------------------------------------------------------


def test_corrupt_supervisor_json_no_crash(tmp_path: Path) -> None:
    """Given corrupt supervisor.json, snapshot falls back to defaults and does not crash."""
    runs_base = tmp_path / ".wea_runs"
    runs_base.mkdir()
    run_dir = _make_run_dir(runs_base, "run-corrupt")
    (run_dir / "supervisor.json").write_text("{ this is not valid json {{{{", encoding="utf-8")
    _write_status(run_dir, {
        "run_id": "run-corrupt",
        "last_event_type": "run_started",
        "last_updated": "2026-03-15T10:30:00Z",
        "event_count": 1,
    })

    # Must not raise
    snapshot = read_run_snapshot(run_dir)

    assert snapshot["status"] == "unknown"
    assert snapshot["run_id"] == "run-corrupt"  # directory name fallback
    # Status.json should still have been read
    assert snapshot["event_count"] == 1


# ---------------------------------------------------------------------------
# Test 9: Run ID not found -> wea run-status exits 1
# ---------------------------------------------------------------------------


def test_run_status_not_found_exits_one(tmp_path: Path) -> None:
    """Given run ID that does not exist, wea run-status exits 1."""
    runs_base = tmp_path / ".wea_runs"
    runs_base.mkdir()
    # Create a different run to ensure the dir exists
    _make_complete_run(runs_base, "some-other-run")

    result = subprocess.run(
        [
            sys.executable, "-m", "wea_cli.cli",
            "run-status", "nonexistent-run-id",
            "--runs-dir", str(runs_base),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "not found" in result.stdout.lower() or "not found" in result.stderr.lower()


# ---------------------------------------------------------------------------
# Test 10: Both files missing -> all defaults, still listed
# ---------------------------------------------------------------------------


def test_both_files_missing_all_defaults(tmp_path: Path) -> None:
    """Given a run dir with no JSON files at all, snapshot uses all defaults and is listed."""
    runs_base = tmp_path / ".wea_runs"
    runs_base.mkdir()
    run_dir = _make_run_dir(runs_base, "empty-run")
    # No supervisor.json, no status.json

    snapshot = read_run_snapshot(run_dir)

    assert snapshot["run_id"] == "empty-run"
    assert snapshot["status"] == "unknown"
    assert snapshot["started_at"] is None
    assert snapshot["last_event_at"] is None
    assert snapshot["command"] is None
    assert snapshot["event_count"] == 0

    # And it should appear in list_runs
    snapshots = list_runs(runs_base)
    assert len(snapshots) == 1
    assert snapshots[0]["run_id"] == "empty-run"


# ---------------------------------------------------------------------------
# Test 11: Non-directory entries in .wea_runs are skipped
# ---------------------------------------------------------------------------


def test_non_directory_entries_skipped(tmp_path: Path) -> None:
    """Given a file (not directory) inside .wea_runs, it is silently skipped."""
    runs_base = tmp_path / ".wea_runs"
    runs_base.mkdir()
    # Create a plain file that should be skipped
    (runs_base / "some-file.txt").write_text("not a run dir", encoding="utf-8")
    _make_complete_run(runs_base, "real-run-001")

    snapshots = list_runs(runs_base)

    assert len(snapshots) == 1
    assert snapshots[0]["run_id"] == "real-run-001"


# ---------------------------------------------------------------------------
# Test 12: format_runs_table always prints header even with zero runs
# ---------------------------------------------------------------------------


def test_format_runs_table_header_always_present() -> None:
    """format_runs_table prints header line even when snapshots list is empty."""
    table = format_runs_table([])
    assert "RUN_ID" in table
    assert "STATUS" in table
    assert "STARTED" in table
    assert "EVENTS" in table
    assert "COMMAND" in table


# ---------------------------------------------------------------------------
# Test 13: Command truncated to 60 chars in table
# ---------------------------------------------------------------------------


def test_format_runs_table_command_truncated() -> None:
    """Long commands are truncated to 60 characters in the table."""
    long_command = "python " + "a" * 100
    snapshot = {
        "run_id": "run-trunc",
        "status": "completed",
        "started_at": "2026-03-15T12:00:00Z",
        "last_event_at": "2026-03-15T12:01:00Z",
        "command": long_command,
        "event_count": 1,
    }
    table = format_runs_table([snapshot])
    # The truncated command should appear (60 chars + "...")
    assert "..." in table
    # The full 100-a string should NOT appear
    assert "a" * 61 not in table


# ---------------------------------------------------------------------------
# Test 14: wea runs with --json and empty dir returns []
# ---------------------------------------------------------------------------


def test_json_flag_empty_dir_returns_empty_array(tmp_path: Path) -> None:
    """Given --json with empty .wea_runs, output is '[]'."""
    runs_base = tmp_path / ".wea_runs"
    runs_base.mkdir()

    result = subprocess.run(
        [sys.executable, "-m", "wea_cli.cli", "runs", "--json", "--runs-dir", str(runs_base)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    parsed = json.loads(result.stdout)
    assert parsed == []


# ---------------------------------------------------------------------------
# Test 15: None started_at values sorted last in list_runs
# ---------------------------------------------------------------------------


def test_none_started_at_sorted_last(tmp_path: Path) -> None:
    """Runs with started_at=None are sorted after all runs with timestamps."""
    runs_base = tmp_path / ".wea_runs"
    runs_base.mkdir()

    # Run with a timestamp
    run_dir_a = _make_run_dir(runs_base, "run-with-time")
    _write_supervisor(run_dir_a, {
        "run_id": "run-with-time",
        "status": "completed",
        "started_at": "2026-03-15T10:00:00Z",
        "command": "echo a",
    })

    # Run with no supervisor.json -> started_at=None
    _make_run_dir(runs_base, "run-no-time")
    # No supervisor.json written for run-no-time

    snapshots = list_runs(runs_base)

    assert len(snapshots) == 2
    assert snapshots[0]["run_id"] == "run-with-time"
    assert snapshots[1]["run_id"] == "run-no-time"
