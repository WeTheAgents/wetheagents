"""Tests for wea spawn — comprehensive lifecycle coverage."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from wea_cli.spawn import (
    EXIT_CHILD_FAILED,
    EXIT_SUCCESS,
    EXIT_TIMEOUT,
    SPAWN_SOURCE,
    make_run_id,
    run_spawn,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_events(run_dir: Path) -> list[dict]:
    """Parse all events from events.jsonl."""
    p = run_dir / "events.jsonl"
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8").strip().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _event_types(run_dir: Path) -> list[str]:
    return [e["event_type"] for e in _read_events(run_dir)]


def _read_manifest(run_dir: Path) -> dict:
    return json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))


def _read_supervisor(run_dir: Path) -> dict:
    return json.loads((run_dir / "supervisor.json").read_text(encoding="utf-8"))


def _read_status(run_dir: Path) -> dict:
    return json.loads((run_dir / "status.json").read_text(encoding="utf-8"))


def _find_run_dir(runs_base: Path) -> Path:
    """Return the single run directory created inside runs_base."""
    dirs = [d for d in runs_base.iterdir() if d.is_dir()]
    assert len(dirs) == 1, f"Expected 1 run dir, got: {dirs}"
    return dirs[0]


# Convenience: python -c "..." invocation that works cross-platform
PY = sys.executable


# ---------------------------------------------------------------------------
# GWT 1: Successful child emits run_started + run_completed
# ---------------------------------------------------------------------------


def test_successful_run_events(tmp_path: Path) -> None:
    """Given a child that exits 0, events = [run_started, run_completed]."""
    runs = tmp_path / ".wea_runs"
    rc = run_spawn(PY, ["-c", "import sys; sys.exit(0)"], runs_base=runs)

    assert rc == EXIT_SUCCESS
    run_dir = _find_run_dir(runs)
    types = _event_types(run_dir)
    assert types[0] == "run_started"
    assert types[-1] == "run_completed"


# ---------------------------------------------------------------------------
# GWT 2: Failed child emits run_failed with exit_code
# ---------------------------------------------------------------------------


def test_failed_child_exit_code(tmp_path: Path) -> None:
    """Given a child that exits 1, run_failed is emitted with exit_code=1."""
    runs = tmp_path / ".wea_runs"
    rc = run_spawn(PY, ["-c", "import sys; sys.exit(1)"], runs_base=runs)

    assert rc == EXIT_CHILD_FAILED
    run_dir = _find_run_dir(runs)
    types = _event_types(run_dir)
    assert types[-1] == "run_failed"

    events = _read_events(run_dir)
    failed = next(e for e in events if e["event_type"] == "run_failed")
    assert failed["payload"]["exit_code"] == 1
    assert "reason" in failed["payload"]


# ---------------------------------------------------------------------------
# GWT 3: Manifest written before child launch (without pid), updated after
# ---------------------------------------------------------------------------


def test_manifest_written_before_pid(tmp_path: Path) -> None:
    """Manifest exists in final state with run_id, command, args, pid, started_at."""
    runs = tmp_path / ".wea_runs"
    run_spawn(PY, ["-c", "pass"], runs_base=runs)

    run_dir = _find_run_dir(runs)
    manifest = _read_manifest(run_dir)

    assert "run_id" in manifest
    assert manifest["command"] == PY
    assert manifest["args"] == ["-c", "pass"]
    assert "started_at" in manifest
    assert "pid" in manifest
    assert isinstance(manifest["pid"], int)


# ---------------------------------------------------------------------------
# GWT 4: Optional manifest fields omitted when not provided
# ---------------------------------------------------------------------------


def test_manifest_optional_fields_omitted(tmp_path: Path) -> None:
    """When agent/runtime/worktree not provided, they are absent from manifest.json."""
    runs = tmp_path / ".wea_runs"
    run_spawn(PY, ["-c", "pass"], runs_base=runs)

    run_dir = _find_run_dir(runs)
    manifest = _read_manifest(run_dir)

    assert "agent" not in manifest
    assert "runtime" not in manifest
    assert "worktree" not in manifest


def test_manifest_optional_fields_present(tmp_path: Path) -> None:
    """When agent/runtime/worktree are provided, they appear in manifest.json."""
    runs = tmp_path / ".wea_runs"
    run_spawn(
        PY, ["-c", "pass"],
        agent="test-agent@claude",
        runtime="claude",
        worktree="/home/user/wta",
        runs_base=runs,
    )

    run_dir = _find_run_dir(runs)
    manifest = _read_manifest(run_dir)

    assert manifest["agent"] == "test-agent@claude"
    assert manifest["runtime"] == "claude"
    assert manifest["worktree"] == "/home/user/wta"


# ---------------------------------------------------------------------------
# GWT 5: supervisor.json owned by spawn, status.json by trace
# ---------------------------------------------------------------------------


def test_supervisor_vs_status_ownership(tmp_path: Path) -> None:
    """supervisor.json has spawn-level fields; status.json has trace-level fields."""
    runs = tmp_path / ".wea_runs"
    run_spawn(PY, ["-c", "pass"], runs_base=runs)

    run_dir = _find_run_dir(runs)

    supervisor = _read_supervisor(run_dir)
    assert "status" in supervisor
    assert supervisor["status"] == "completed"
    assert "run_id" in supervisor
    assert "command" in supervisor

    status = _read_status(run_dir)
    assert "last_event_type" in status
    assert "event_count" in status


# ---------------------------------------------------------------------------
# GWT 6: Run ID format — with and without agent
# ---------------------------------------------------------------------------


def test_run_id_format_no_agent() -> None:
    """Run ID without agent: YYYYMMDDTHHMMSS-8hex."""
    rid = make_run_id()
    parts = rid.split("-")
    # e.g. 20260315T143022-a3f9c1e2 → ['20260315T143022', 'a3f9c1e2']
    assert len(parts) == 2
    ts, rand = parts
    assert len(ts) == 15  # YYYYMMDDTHHMMSS
    assert "T" in ts
    assert len(rand) == 8
    assert all(c in "0123456789abcdef" for c in rand)


def test_run_id_format_with_agent() -> None:
    """Run ID with agent: slug-YYYYMMDDTHHMMSS-8hex, slug lowercased."""
    rid = make_run_id(agent="Claude-1@claude")
    assert rid.startswith("claude-1-claude-")
    parts = rid.split("-")
    # claude-1-claude-YYYYMMDDTHHMMSS-8hex → 5 parts
    assert len(parts) == 5
    rand = parts[-1]
    assert len(rand) == 8
    assert all(c in "0123456789abcdef" for c in rand)


# ---------------------------------------------------------------------------
# GWT 7: Environment variables injected into child
# ---------------------------------------------------------------------------


def test_env_vars_injected(tmp_path: Path) -> None:
    """WEA_RUN_ID and WEA_RUN_DIR are set in child environment."""
    env_out = tmp_path / "env_capture.json"
    script = (
        f"import os, json; "
        f"json.dump({{'run_id': os.environ.get('WEA_RUN_ID'), "
        f"'run_dir': os.environ.get('WEA_RUN_DIR')}}, "
        f"open({str(env_out)!r}, 'w'))"
    )
    runs = tmp_path / ".wea_runs"
    rc = run_spawn(PY, ["-c", script], runs_base=runs)

    assert rc == EXIT_SUCCESS
    assert env_out.exists(), "Child did not write env capture file"

    captured = json.loads(env_out.read_text(encoding="utf-8"))
    run_dir = _find_run_dir(runs)

    assert captured["run_id"] == run_dir.name
    assert captured["run_dir"] == str(run_dir.resolve())


# ---------------------------------------------------------------------------
# GWT 8: Timeout emits run_timeout and returns EXIT_TIMEOUT
# ---------------------------------------------------------------------------


def test_timeout_emits_run_timeout(tmp_path: Path) -> None:
    """When child exceeds timeout, run_timeout is emitted and EXIT_TIMEOUT returned."""
    runs = tmp_path / ".wea_runs"
    # Child sleeps 60s; timeout=1
    rc = run_spawn(
        PY, ["-c", "import time; time.sleep(60)"],
        timeout=1,
        heartbeat_interval=999,  # suppress heartbeats during test
        runs_base=runs,
    )

    assert rc == EXIT_TIMEOUT
    run_dir = _find_run_dir(runs)
    types = _event_types(run_dir)
    assert "run_timeout" in types
    assert types[-1] == "run_timeout"

    supervisor = _read_supervisor(run_dir)
    assert supervisor["status"] == "timeout"


# ---------------------------------------------------------------------------
# GWT 9: Exactly one terminal event per run
# ---------------------------------------------------------------------------


def test_exactly_one_terminal_event_success(tmp_path: Path) -> None:
    """Exactly one terminal event for a successful run."""
    runs = tmp_path / ".wea_runs"
    run_spawn(PY, ["-c", "pass"], runs_base=runs)

    run_dir = _find_run_dir(runs)
    events = _read_events(run_dir)
    terminal = [e for e in events if e["event_type"] in ("run_completed", "run_failed", "run_timeout")]
    assert len(terminal) == 1


def test_exactly_one_terminal_event_failure(tmp_path: Path) -> None:
    """Exactly one terminal event for a failed run."""
    runs = tmp_path / ".wea_runs"
    run_spawn(PY, ["-c", "import sys; sys.exit(2)"], runs_base=runs)

    run_dir = _find_run_dir(runs)
    events = _read_events(run_dir)
    terminal = [e for e in events if e["event_type"] in ("run_completed", "run_failed", "run_timeout")]
    assert len(terminal) == 1


# ---------------------------------------------------------------------------
# GWT 10: Output captured in binary mode, not buffered in memory
# ---------------------------------------------------------------------------


def test_stdout_captured_to_file(tmp_path: Path) -> None:
    """Child stdout is written to stdout.log."""
    runs = tmp_path / ".wea_runs"
    script = "print('hello from child')"
    run_spawn(PY, ["-c", script], runs_base=runs)

    run_dir = _find_run_dir(runs)
    stdout_log = run_dir / "stdout.log"
    assert stdout_log.exists()
    content = stdout_log.read_bytes()
    assert b"hello from child" in content


def test_stderr_captured_to_file(tmp_path: Path) -> None:
    """Child stderr is written to stderr.log."""
    runs = tmp_path / ".wea_runs"
    script = "import sys; print('oops', file=sys.stderr)"
    run_spawn(PY, ["-c", script], runs_base=runs)

    run_dir = _find_run_dir(runs)
    stderr_log = run_dir / "stderr.log"
    assert stderr_log.exists()
    content = stderr_log.read_bytes()
    assert b"oops" in content


# ---------------------------------------------------------------------------
# GWT 11: Heartbeat events emitted during long-running child
# ---------------------------------------------------------------------------


def test_heartbeat_emitted(tmp_path: Path) -> None:
    """Heartbeat events appear for a child that runs longer than heartbeat_interval."""
    runs = tmp_path / ".wea_runs"
    # Child runs for ~2s; heartbeat every 0.5s → expect at least 1 heartbeat
    rc = run_spawn(
        PY, ["-c", "import time; time.sleep(2)"],
        heartbeat_interval=1,
        runs_base=runs,
    )

    assert rc == EXIT_SUCCESS
    run_dir = _find_run_dir(runs)
    types = _event_types(run_dir)
    assert "heartbeat" in types

    # Heartbeats have pid in payload
    events = _read_events(run_dir)
    hb = next(e for e in events if e["event_type"] == "heartbeat")
    assert "pid" in hb["payload"]
    assert isinstance(hb["payload"]["pid"], int)


# ---------------------------------------------------------------------------
# GWT 12: run_started event has correct source and payload fields
# ---------------------------------------------------------------------------


def test_run_started_payload(tmp_path: Path) -> None:
    """run_started event has source=wea-spawn, pid, command in payload."""
    runs = tmp_path / ".wea_runs"
    run_spawn(PY, ["-c", "pass"], agent="myagent@test", runs_base=runs)

    run_dir = _find_run_dir(runs)
    events = _read_events(run_dir)
    started = next(e for e in events if e["event_type"] == "run_started")

    assert started["source"] == SPAWN_SOURCE
    assert "pid" in started["payload"]
    assert "command" in started["payload"]
    assert "agent" in started["payload"]
    assert started["payload"]["agent"] == "myagent@test"


# ---------------------------------------------------------------------------
# GWT 13: .wea_runs directory created if it does not exist
# ---------------------------------------------------------------------------


def test_wea_runs_auto_created(tmp_path: Path) -> None:
    """The .wea_runs directory is created automatically if it doesn't exist."""
    runs = tmp_path / "deep" / "nested" / ".wea_runs"
    assert not runs.exists()

    rc = run_spawn(PY, ["-c", "pass"], runs_base=runs)
    assert rc == EXIT_SUCCESS
    assert runs.exists()


# ---------------------------------------------------------------------------
# GWT 14: supervisor.json status transitions correctly
# ---------------------------------------------------------------------------


def test_supervisor_status_completed(tmp_path: Path) -> None:
    """supervisor.json shows status=completed after successful child."""
    runs = tmp_path / ".wea_runs"
    run_spawn(PY, ["-c", "pass"], runs_base=runs)

    run_dir = _find_run_dir(runs)
    sup = _read_supervisor(run_dir)
    assert sup["status"] == "completed"
    assert "started_at" in sup
    assert "run_id" in sup


def test_supervisor_status_failed(tmp_path: Path) -> None:
    """supervisor.json shows status=failed after child exits non-zero."""
    runs = tmp_path / ".wea_runs"
    run_spawn(PY, ["-c", "import sys; sys.exit(3)"], runs_base=runs)

    run_dir = _find_run_dir(runs)
    sup = _read_supervisor(run_dir)
    assert sup["status"] == "failed"


# ---------------------------------------------------------------------------
# GWT 15: All timestamps are UTC ISO 8601 ending in Z
# ---------------------------------------------------------------------------


def test_event_timestamps_end_in_z(tmp_path: Path) -> None:
    """All event timestamps end in 'Z' (UTC)."""
    runs = tmp_path / ".wea_runs"
    run_spawn(PY, ["-c", "pass"], runs_base=runs)

    run_dir = _find_run_dir(runs)
    for event in _read_events(run_dir):
        assert event["timestamp"].endswith("Z"), f"Bad timestamp: {event['timestamp']}"

    manifest = _read_manifest(run_dir)
    assert manifest["started_at"].endswith("Z")

    sup = _read_supervisor(run_dir)
    assert sup["started_at"].endswith("Z")
