"""wea health — agent health scoring and spawn fail-safe."""

from __future__ import annotations

import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HEALTH_FILE = "ledger/agent_health.json"

STATUS_AVAILABLE = "available"
STATUS_COOLDOWN = "cooldown"
STATUS_OFFLINE = "offline"
STATUS_UNKNOWN = "unknown"

VALID_STATUSES = {STATUS_AVAILABLE, STATUS_COOLDOWN, STATUS_OFFLINE, STATUS_UNKNOWN}

VALID_EVENTS = {"error", "rate-limit", "recovered", "offline"}

# Cooldown decay: score * 0.8^(elapsed_minutes / 5), floored to int
DECAY_BASE = 0.8
DECAY_PERIOD_MINUTES = 5

SPAWN_WARN_THRESHOLD = 50


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(ts: str) -> datetime:
    """Parse ISO 8601 timestamp (Z suffix)."""
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def compute_cooldown(stored_score: int, last_error_at: str | None, now: datetime | None = None) -> int:
    """Compute live cooldown score applying exponential decay.

    Formula: floor(stored_score * 0.8^(elapsed_minutes / 5))
    Returns 0 if last_error_at is None or stored_score is 0.
    """
    if not last_error_at or stored_score == 0:
        return 0
    if now is None:
        now = _now_utc()
    try:
        error_time = _parse_iso(last_error_at)
    except ValueError:
        return 0
    elapsed_seconds = (now - error_time).total_seconds()
    elapsed_minutes = max(0.0, elapsed_seconds / 60.0)
    decayed = stored_score * (DECAY_BASE ** (elapsed_minutes / DECAY_PERIOD_MINUTES))
    return max(0, math.floor(decayed))


def _atomic_write_json(path: Path, data: dict) -> None:
    content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_", suffix=".json")
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


def _empty_health() -> dict:
    return {"version": 1, "agents": {}}


def load_health(root: Path) -> dict:
    """Load agent_health.json, returning empty structure if missing or corrupt."""
    path = root / HEALTH_FILE
    if not path.exists():
        return _empty_health()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _empty_health()


def save_health(root: Path, data: dict) -> None:
    """Atomically save agent_health.json, creating ledger/ if needed."""
    path = root / HEALTH_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(path, data)


def now_iso() -> str:
    """Public alias for current UTC timestamp in ISO 8601 format."""
    return _now_iso()


def default_agent_record() -> dict:
    """Return a fresh agent record with unknown status and zero cooldown."""
    return {
        "status": STATUS_UNKNOWN,
        "cooldown_score": 0,
        "last_activity_at": None,
        "last_error_at": None,
        "last_error_reason": None,
        "updated_at": None,
    }


def get_live_status(record: dict, now: datetime | None = None) -> tuple[str, int]:
    """Return (status, live_cooldown_score) for a record, computing decay."""
    stored_score = record.get("cooldown_score", 0)
    last_error_at = record.get("last_error_at")
    live_score = compute_cooldown(stored_score, last_error_at, now)
    return record.get("status", STATUS_UNKNOWN), live_score


def get_health_indicator(status: str, cooldown: int) -> str:
    """Return emoji indicator for a given status + cooldown."""
    if status == STATUS_OFFLINE:
        return "🔴"
    if status == STATUS_COOLDOWN or cooldown > SPAWN_WARN_THRESHOLD:
        return "🟡"
    if status == STATUS_AVAILABLE:
        return "🟢"
    return "⚪"


def apply_event(record: dict, event: str, now_iso: str) -> dict:
    """Return updated record for a given event. Does not mutate input."""
    r = dict(record)
    r["updated_at"] = now_iso
    r["last_activity_at"] = now_iso
    if event in ("error", "rate-limit"):
        r["status"] = STATUS_COOLDOWN
        r["cooldown_score"] = 100
        r["last_error_at"] = now_iso
        r["last_error_reason"] = event
    elif event == "recovered":
        r["status"] = STATUS_AVAILABLE
        r["cooldown_score"] = 0
    elif event == "offline":
        r["status"] = STATUS_OFFLINE
    return r


def check_spawn_warning(root: Path, agent_id: str) -> str | None:
    """Return a warning string if agent should not be spawned, else None."""
    data = load_health(root)
    agents = data.get("agents", {})
    if agent_id not in agents:
        return None  # unknown → no warning
    record = agents[agent_id]
    status, live_score = get_live_status(record)
    if status in (STATUS_OFFLINE, STATUS_COOLDOWN) or live_score > SPAWN_WARN_THRESHOLD:
        return (
            f"Agent {agent_id} is in cooldown (score: {live_score}). "
            "Consider using a healthier agent."
        )
    return None
