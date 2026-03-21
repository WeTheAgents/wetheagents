"""wea spawn — generic supervisor for child process lifecycle management."""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from wea_cli.shims import create_shim_dir
from wea_cli.trace import emit_event

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SPAWN_SOURCE = "wea-spawn"

EXIT_SUCCESS = 0
EXIT_CHILD_FAILED = 1
EXIT_TIMEOUT = 2
EXIT_SPAWN_ERROR = 3

DEFAULT_TIMEOUT = 600
DEFAULT_HEARTBEAT_INTERVAL = 10

# Seconds to wait after terminate() before kill()
TERMINATE_GRACE = 5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    """Return current UTC time as ISO 8601 string ending in Z."""
    return _now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")


def make_run_id(agent: str | None = None) -> str:
    """Generate a run ID.

    Format: [<slug>-]<YYYYMMDDTHHMMSS>-<8hex>
    Agent slug: replace @/./space with -, lowercase.
    """
    timestamp = _now_utc().strftime("%Y%m%dT%H%M%S")
    rand = secrets.token_hex(4)
    base = f"{timestamp}-{rand}"
    if agent:
        slug = agent.lower().replace("@", "-").replace(".", "-").replace(" ", "-")
        return f"{slug}-{base}"
    return base


def _atomic_write_json(path: Path, data: dict) -> None:
    """Write a JSON file atomically via tempfile + os.replace()."""
    content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=".tmp_",
        suffix=".json",
    )
    closed = False
    try:
        os.write(fd, content.encode("utf-8"))
        os.close(fd)
        closed = True
        os.replace(tmp_path, str(path))
    except BaseException:
        if not closed:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _write_manifest(
    run_dir: Path,
    run_id: str,
    command: str,
    args: list[str],
    started_at: str,
    pid: int | None,
    agent: str | None,
    runtime: str | None,
    worktree: str | None,
) -> None:
    """Write (or update) manifest.json in the run directory."""
    data: dict = {
        "run_id": run_id,
        "command": command,
        "args": args,
        "started_at": started_at,
    }
    if agent is not None:
        data["agent"] = agent
    if pid is not None:
        data["pid"] = pid
    if runtime is not None:
        data["runtime"] = runtime
    if worktree is not None:
        data["worktree"] = worktree
    _atomic_write_json(run_dir / "manifest.json", data)


def _write_supervisor(
    run_dir: Path,
    status: str,
    run_id: str,
    command: str,
    started_at: str,
    pid: int | None,
    last_heartbeat_at: str | None = None,
    last_milestone_at: str | None = None,
) -> None:
    """Atomically write supervisor.json.

    All fields in the schema are always present.
    last_heartbeat_at and last_milestone_at are null when not yet set.
    """
    data: dict = {
        "run_id": run_id,
        "status": status,
        "started_at": started_at,
        "last_heartbeat_at": last_heartbeat_at,
        "last_milestone_at": last_milestone_at,
        "pid": pid,
        "command": command,
    }
    _atomic_write_json(run_dir / "supervisor.json", data)


def _pid_alive(pid: int, process: subprocess.Popen | None = None) -> bool:
    """Check if a PID is alive. Cross-platform (Windows + POSIX).

    On Windows: prefer process.poll() when process object is available,
    fall back to OpenProcess/GetExitCodeProcess.
    On POSIX: use os.kill(pid, 0).
    """
    if sys.platform == "win32":
        # Prefer process.poll() on Windows as recommended by the spec
        if process is not None:
            return process.poll() is None
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(  # type: ignore[attr-defined]
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid,
        )
        if handle == 0:
            return False
        try:
            exit_code = ctypes.c_ulong(0)
            result = ctypes.windll.kernel32.GetExitCodeProcess(  # type: ignore[attr-defined]
                handle, ctypes.byref(exit_code),
            )
            if not result:
                return False
            # STILL_ACTIVE = 259
            return exit_code.value == 259
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)  # type: ignore[attr-defined]
    else:
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            # Process exists but we don't have permission to signal it
            return True


def _terminate_process(process: subprocess.Popen) -> None:
    """Terminate child process: terminate → 5s grace → kill.

    On Windows: process.terminate() then process.kill() after grace period.
    """
    try:
        process.terminate()
    except OSError:
        pass

    try:
        process.wait(timeout=TERMINATE_GRACE)
        return
    except subprocess.TimeoutExpired:
        pass

    try:
        process.kill()
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Heartbeat thread
# ---------------------------------------------------------------------------


class _HeartbeatThread(threading.Thread):
    """Daemon thread that emits heartbeat events at a fixed interval.

    Stops when stop_event is set or PID is no longer alive.
    """

    def __init__(
        self,
        run_dir: Path,
        run_id: str,
        pid: int,
        process: subprocess.Popen,
        interval: int,
        supervisor_state: dict,
    ) -> None:
        super().__init__(daemon=True, name=f"heartbeat-{run_id}")
        self._run_dir = run_dir
        self._run_id = run_id
        self._pid = pid
        self._process = process
        self._interval = interval
        self._supervisor_state = supervisor_state  # shared mutable dict
        self.stop_event = threading.Event()

    def run(self) -> None:
        while not self.stop_event.wait(timeout=self._interval):
            if not _pid_alive(self._pid, self._process):
                break
            try:
                emit_event(
                    run_dir=self._run_dir,
                    event_type="heartbeat",
                    source=SPAWN_SOURCE,
                    payload={"pid": self._pid},
                )
                now_iso = _now_iso()
                self._supervisor_state["last_heartbeat_at"] = now_iso
                _write_supervisor(
                    run_dir=self._run_dir,
                    status="running",
                    run_id=self._run_id,
                    command=self._supervisor_state["command"],
                    started_at=self._supervisor_state["started_at"],
                    pid=self._pid,
                    last_heartbeat_at=now_iso,
                    last_milestone_at=self._supervisor_state.get("last_milestone_at"),
                )
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Core spawn logic
# ---------------------------------------------------------------------------


def run_spawn(
    command: str,
    args: list[str],
    *,
    agent: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    runtime: str | None = None,
    worktree: str | None = None,
    heartbeat_interval: int = DEFAULT_HEARTBEAT_INTERVAL,
    runs_base: Path | None = None,
) -> int:
    """Launch command, monitor it, emit lifecycle events.

    Args:
        command: Executable to run.
        args: Arguments for the executable.
        agent: Optional agent identifier.
        timeout: Wall-clock timeout in seconds.
        runtime: Optional runtime label string.
        worktree: Optional worktree path string.
        heartbeat_interval: Seconds between heartbeat PID checks.
        runs_base: Override for .wea_runs base directory (for testing).

    Returns:
        Exit code: 0=success, 1=child failed, 2=timeout, 3=spawn error.
    """
    # Determine .wea_runs location
    if runs_base is None:
        runs_base = Path.cwd() / ".wea_runs"
    runs_base.mkdir(parents=True, exist_ok=True)

    run_id = make_run_id(agent)
    run_dir = runs_base / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    started_at = _now_iso()
    full_cmd = [command, *args]
    cmd_str = " ".join(full_cmd)

    # --- Write manifest (without pid yet) ---
    _write_manifest(
        run_dir=run_dir,
        run_id=run_id,
        command=command,
        args=args,
        started_at=started_at,
        pid=None,
        agent=agent,
        runtime=runtime,
        worktree=worktree,
    )

    # Shared state for heartbeat thread
    supervisor_state: dict = {
        "command": cmd_str,
        "started_at": started_at,
        "last_heartbeat_at": None,
        "last_milestone_at": None,
    }

    # Open stdout/stderr log files (binary mode, streamed — kept open until process exits)
    stdout_log = run_dir / "stdout.log"
    stderr_log = run_dir / "stderr.log"

    process: subprocess.Popen | None = None
    heartbeat: _HeartbeatThread | None = None
    fout = None
    ferr = None

    try:
        env = os.environ.copy()
        env["WEA_RUN_ID"] = run_id
        env["WEA_RUN_DIR"] = str(run_dir.resolve())

        # Prepend shim directory to PATH so milestone events fire for matching
        # git/gh/wea sub-commands executed by the child process.
        shim_dir = create_shim_dir(run_dir)
        env["PATH"] = str(shim_dir) + os.pathsep + env.get("PATH", "")

        # Open log files in binary mode BEFORE Popen so they stay open for the
        # duration of the child's life (streamed, not buffered in memory).
        fout = open(stdout_log, "wb")
        ferr = open(stderr_log, "wb")

        try:
            process = subprocess.Popen(
                full_cmd,
                stdout=fout,
                stderr=ferr,
                env=env,
            )
        except FileNotFoundError:
            # Command not found — emit run_failed with specific reason
            try:
                emit_event(
                    run_dir=run_dir,
                    event_type="run_failed",
                    source=SPAWN_SOURCE,
                    payload={"exit_code": -1, "reason": "command_not_found"},
                )
            except Exception:
                pass
            _write_supervisor(
                run_dir=run_dir,
                status="failed",
                run_id=run_id,
                command=cmd_str,
                started_at=started_at,
                pid=None,
            )
            return EXIT_SPAWN_ERROR
        except (PermissionError, OSError):
            # Other OS-level spawn errors
            try:
                emit_event(
                    run_dir=run_dir,
                    event_type="run_failed",
                    source=SPAWN_SOURCE,
                    payload={"exit_code": -1, "reason": "spawn_error"},
                )
            except Exception:
                pass
            _write_supervisor(
                run_dir=run_dir,
                status="failed",
                run_id=run_id,
                command=cmd_str,
                started_at=started_at,
                pid=None,
            )
            return EXIT_SPAWN_ERROR

        pid = process.pid

        # --- Update manifest with pid ---
        _write_manifest(
            run_dir=run_dir,
            run_id=run_id,
            command=command,
            args=args,
            started_at=started_at,
            pid=pid,
            agent=agent,
            runtime=runtime,
            worktree=worktree,
        )

        # --- Emit run_started (step 7) ---
        started_payload: dict = {"pid": pid, "command": cmd_str}
        if agent is not None:
            started_payload["agent"] = agent
        emit_event(
            run_dir=run_dir,
            event_type="run_started",
            source=SPAWN_SOURCE,
            payload=started_payload,
        )

        # --- Write initial supervisor.json: running (step 8) ---
        _write_supervisor(
            run_dir=run_dir,
            status="running",
            run_id=run_id,
            command=cmd_str,
            started_at=started_at,
            pid=pid,
            last_heartbeat_at=None,
            last_milestone_at=None,
        )

        # --- Start heartbeat thread ---
        heartbeat = _HeartbeatThread(
            run_dir=run_dir,
            run_id=run_id,
            pid=pid,
            process=process,
            interval=heartbeat_interval,
            supervisor_state=supervisor_state,
        )
        heartbeat.start()

        # --- Wait with timeout ---
        try:
            return_code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            # Stop heartbeat first
            heartbeat.stop_event.set()

            _terminate_process(process)
            try:
                process.wait(timeout=TERMINATE_GRACE + 2)
            except subprocess.TimeoutExpired:
                pass

            elapsed = timeout
            emit_event(
                run_dir=run_dir,
                event_type="run_timeout",
                source=SPAWN_SOURCE,
                payload={"elapsed_seconds": elapsed},
            )
            _write_supervisor(
                run_dir=run_dir,
                status="timeout",
                run_id=run_id,
                command=cmd_str,
                started_at=started_at,
                pid=pid,
                last_heartbeat_at=supervisor_state.get("last_heartbeat_at"),
                last_milestone_at=supervisor_state.get("last_milestone_at"),
            )
            return EXIT_TIMEOUT

        # --- Child exited normally ---
        heartbeat.stop_event.set()

        if return_code == 0:
            emit_event(
                run_dir=run_dir,
                event_type="run_completed",
                source=SPAWN_SOURCE,
                payload={"exit_code": 0},
            )
            _write_supervisor(
                run_dir=run_dir,
                status="completed",
                run_id=run_id,
                command=cmd_str,
                started_at=started_at,
                pid=pid,
                last_heartbeat_at=supervisor_state.get("last_heartbeat_at"),
                last_milestone_at=supervisor_state.get("last_milestone_at"),
            )
            return EXIT_SUCCESS
        else:
            emit_event(
                run_dir=run_dir,
                event_type="run_failed",
                source=SPAWN_SOURCE,
                payload={"exit_code": return_code, "reason": "non_zero_exit"},
            )
            _write_supervisor(
                run_dir=run_dir,
                status="failed",
                run_id=run_id,
                command=cmd_str,
                started_at=started_at,
                pid=pid,
                last_heartbeat_at=supervisor_state.get("last_heartbeat_at"),
                last_milestone_at=supervisor_state.get("last_milestone_at"),
            )
            return EXIT_CHILD_FAILED

    except Exception:
        # Supervisor crash: emit run_failed with supervisor_crash reason, return EXIT_SPAWN_ERROR
        if heartbeat is not None:
            heartbeat.stop_event.set()

        pid_on_crash = process.pid if process is not None else None
        try:
            emit_event(
                run_dir=run_dir,
                event_type="run_failed",
                source=SPAWN_SOURCE,
                payload={"exit_code": -1, "reason": "supervisor_crash"},
            )
        except Exception:
            pass

        _write_supervisor(
            run_dir=run_dir,
            status="failed",
            run_id=run_id,
            command=cmd_str,
            started_at=started_at,
            pid=pid_on_crash,
            last_heartbeat_at=supervisor_state.get("last_heartbeat_at"),
            last_milestone_at=supervisor_state.get("last_milestone_at"),
        )
        return EXIT_SPAWN_ERROR

    finally:
        if heartbeat is not None and heartbeat.is_alive():
            heartbeat.stop_event.set()
            heartbeat.join(timeout=2)
        # Close log files after child has finished (or been terminated)
        if fout is not None:
            try:
                fout.close()
            except OSError:
                pass
        if ferr is not None:
            try:
                ferr.close()
            except OSError:
                pass
