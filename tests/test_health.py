"""Tests for wea health — agent health scoring system.

Coverage:
1. Cooldown decay math (T+0, T+5, T+10, T+30, T+60)
2. wea health mark writes correct state
3. wea health report computes live decay
4. Spawn warning triggers at correct threshold
5. Missing agent_health.json defaults gracefully to unknown
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from wea_cli.health import (
    SPAWN_WARN_THRESHOLD,
    STATUS_AVAILABLE,
    STATUS_COOLDOWN,
    STATUS_OFFLINE,
    STATUS_UNKNOWN,
    apply_event,
    check_spawn_warning,
    compute_cooldown,
    default_agent_record,
    get_health_indicator,
    get_live_status,
    load_health,
    now_iso,
    save_health,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


@pytest.fixture
def temp_repo(tmp_path: Path) -> Path:
    """Minimal repo with ledger/balances.json."""
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    _write_json(
        ledger / "balances.json",
        {
            "version": 1,
            "last_updated": "2026-03-01T00:00:00Z",
            "agents": {
                "agent0@system": {"balance": 10000, "total_earned": 10000, "total_spent": 0,
                                  "tasks_completed": 0, "tasks_created": 0},
                "Claude-9@claude": {"balance": 100, "total_earned": 100, "total_spent": 0,
                                    "tasks_completed": 1, "tasks_created": 0,
                                    "platform": "claude", "operator": "test",
                                    "github_username": "tester"},
            },
        },
    )
    return tmp_path


# ---------------------------------------------------------------------------
# 1. Cooldown decay math
# ---------------------------------------------------------------------------

def _at_minutes(base_iso: str, minutes: float) -> datetime:
    """Return a datetime that is `minutes` after base_iso."""
    base = datetime.strptime(base_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    from datetime import timedelta
    return base + timedelta(minutes=minutes)


class TestCooldownDecay:
    """Verify the exponential decay formula: floor(score * 0.8^(elapsed/5))."""

    ERROR_TS = "2026-01-01T00:00:00Z"

    def test_t0(self):
        """At T+0, score should be the stored value (100)."""
        now = _at_minutes(self.ERROR_TS, 0)
        assert compute_cooldown(100, self.ERROR_TS, now) == 100

    def test_t5(self):
        """At T+5min, score = floor(100 * 0.8^1) = 80."""
        now = _at_minutes(self.ERROR_TS, 5)
        assert compute_cooldown(100, self.ERROR_TS, now) == 80

    def test_t10(self):
        """At T+10min, score = floor(100 * 0.8^2) = 64."""
        now = _at_minutes(self.ERROR_TS, 10)
        assert compute_cooldown(100, self.ERROR_TS, now) == 64

    def test_t30(self):
        """At T+30min, score = floor(100 * 0.8^6) = floor(26.21) = 26."""
        now = _at_minutes(self.ERROR_TS, 30)
        assert compute_cooldown(100, self.ERROR_TS, now) == 26

    def test_t60(self):
        """At T+60min, score = floor(100 * 0.8^12) = floor(6.87) = 6 (near zero)."""
        now = _at_minutes(self.ERROR_TS, 60)
        result = compute_cooldown(100, self.ERROR_TS, now)
        # Score must be below warn threshold (50) — effectively non-triggering
        assert result < SPAWN_WARN_THRESHOLD
        # And very low — formula gives 6
        assert result <= 10

    def test_zero_score_stays_zero(self):
        """A stored score of 0 decays to 0 regardless of elapsed time."""
        now = _at_minutes(self.ERROR_TS, 0)
        assert compute_cooldown(0, self.ERROR_TS, now) == 0

    def test_no_error_timestamp_returns_zero(self):
        """If last_error_at is None, cooldown is always 0."""
        now = _at_minutes(self.ERROR_TS, 5)
        assert compute_cooldown(100, None, now) == 0

    def test_score_below_warn_threshold_at_t15(self):
        """At T+15min, score = floor(100 * 0.8^3) = 51 — still above threshold."""
        now = _at_minutes(self.ERROR_TS, 15)
        score = compute_cooldown(100, self.ERROR_TS, now)
        # 100 * 0.8^3 = 51.2, floored to 51
        assert score == 51

    def test_score_below_warn_threshold_at_t20(self):
        """At T+20min, score = floor(100 * 0.8^4) = 40 — below warning threshold."""
        now = _at_minutes(self.ERROR_TS, 20)
        score = compute_cooldown(100, self.ERROR_TS, now)
        assert score <= SPAWN_WARN_THRESHOLD


# ---------------------------------------------------------------------------
# 2. wea health mark writes correct state
# ---------------------------------------------------------------------------

class TestHealthMark:
    """Verify that apply_event produces correct state for each event type."""

    def _base_record(self) -> dict:
        return default_agent_record()

    def test_error_sets_cooldown_100_and_status(self):
        """error event → cooldown=100, status=cooldown."""
        record = self._base_record()
        updated = apply_event(record, "error", "2026-01-01T12:00:00Z")
        assert updated["cooldown_score"] == 100
        assert updated["status"] == STATUS_COOLDOWN
        assert updated["last_error_at"] == "2026-01-01T12:00:00Z"
        assert updated["last_error_reason"] == "error"

    def test_rate_limit_sets_cooldown_100_and_status(self):
        """rate-limit event → cooldown=100, status=cooldown."""
        record = self._base_record()
        updated = apply_event(record, "rate-limit", "2026-01-01T12:00:00Z")
        assert updated["cooldown_score"] == 100
        assert updated["status"] == STATUS_COOLDOWN
        assert updated["last_error_reason"] == "rate-limit"

    def test_recovered_resets_cooldown_and_status(self):
        """recovered event → cooldown=0, status=available."""
        record = apply_event(self._base_record(), "error", "2026-01-01T12:00:00Z")
        recovered = apply_event(record, "recovered", "2026-01-01T12:30:00Z")
        assert recovered["cooldown_score"] == 0
        assert recovered["status"] == STATUS_AVAILABLE

    def test_offline_sets_status(self):
        """offline event → status=offline."""
        record = self._base_record()
        updated = apply_event(record, "offline", "2026-01-01T12:00:00Z")
        assert updated["status"] == STATUS_OFFLINE

    def test_mark_creates_health_file_on_first_call(self, temp_repo: Path):
        """First wea health mark creates ledger/agent_health.json."""
        health_path = temp_repo / "ledger" / "agent_health.json"
        assert not health_path.exists()

        data = load_health(temp_repo)
        data.setdefault("agents", {})
        record = default_agent_record()
        data["agents"]["Claude-9@claude"] = apply_event(record, "error", now_iso())
        save_health(temp_repo, data)

        assert health_path.exists()
        saved = json.loads(health_path.read_text(encoding="utf-8"))
        assert saved["agents"]["Claude-9@claude"]["status"] == STATUS_COOLDOWN
        assert saved["agents"]["Claude-9@claude"]["cooldown_score"] == 100

    def test_mark_does_not_mutate_input_record(self):
        """apply_event must not mutate the input record."""
        record = default_agent_record()
        original_status = record["status"]
        apply_event(record, "error", "2026-01-01T00:00:00Z")
        assert record["status"] == original_status


# ---------------------------------------------------------------------------
# 3. wea health report computes live decay
# ---------------------------------------------------------------------------

class TestHealthReport:
    """Verify that get_live_status applies decay correctly at read time."""

    def test_live_score_is_decayed_not_stored(self):
        """get_live_status returns live decayed score, not stored score."""
        record = default_agent_record()
        record = apply_event(record, "error", "2026-01-01T00:00:00Z")
        # Simulate reading 10 minutes later
        now = _at_minutes("2026-01-01T00:00:00Z", 10)
        status, live_score = get_live_status(record, now)
        assert status == STATUS_COOLDOWN
        assert live_score == 64  # floor(100 * 0.8^2)

    def test_report_for_agent_not_in_file(self, temp_repo: Path):
        """Agent not in health file → load_health returns empty agents dict."""
        data = load_health(temp_repo)
        assert "unknown-agent@test" not in data.get("agents", {})


# ---------------------------------------------------------------------------
# 4. Spawn warning triggers at correct threshold
# ---------------------------------------------------------------------------

class TestSpawnWarning:
    """Verify check_spawn_warning fires correctly."""

    def _seed_health(self, root: Path, agent_id: str, record: dict) -> None:
        data = load_health(root)
        data.setdefault("agents", {})[agent_id] = record
        save_health(root, data)

    def test_warning_fires_when_status_cooldown(self, temp_repo: Path):
        """Status=cooldown with high score triggers warning."""
        record = apply_event(default_agent_record(), "error", "2026-01-01T00:00:00Z")
        self._seed_health(temp_repo, "Claude-9@claude", record)
        warning = check_spawn_warning(temp_repo, "Claude-9@claude")
        assert warning is not None
        assert "Claude-9@claude" in warning

    def test_warning_fires_when_status_offline(self, temp_repo: Path):
        """Status=offline triggers warning regardless of score."""
        record = apply_event(default_agent_record(), "offline", "2026-01-01T00:00:00Z")
        self._seed_health(temp_repo, "Claude-9@claude", record)
        warning = check_spawn_warning(temp_repo, "Claude-9@claude")
        assert warning is not None

    def test_no_warning_when_available(self, temp_repo: Path):
        """Status=available with cooldown=0 → no warning."""
        record = apply_event(default_agent_record(), "recovered", "2026-01-01T00:00:00Z")
        self._seed_health(temp_repo, "Claude-9@claude", record)
        warning = check_spawn_warning(temp_repo, "Claude-9@claude")
        assert warning is None

    def test_no_warning_for_unknown_agent(self, temp_repo: Path):
        """Agent not in health file → no warning (unknown defaults gracefully)."""
        warning = check_spawn_warning(temp_repo, "Ghost-99@nowhere")
        assert warning is None


# ---------------------------------------------------------------------------
# 5. Missing agent_health.json defaults gracefully to unknown
# ---------------------------------------------------------------------------

class TestMissingHealthFile:
    """Verify graceful fallback when health file is absent."""

    def test_load_health_missing_file_returns_empty(self, temp_repo: Path):
        """load_health on missing file returns version=1 with empty agents."""
        health_path = temp_repo / "ledger" / "agent_health.json"
        assert not health_path.exists()
        data = load_health(temp_repo)
        assert data["version"] == 1
        assert data["agents"] == {}

    def test_load_health_corrupt_file_returns_empty(self, temp_repo: Path):
        """load_health on corrupt JSON returns empty structure without crashing."""
        health_path = temp_repo / "ledger" / "agent_health.json"
        health_path.write_text("not valid json", encoding="utf-8")
        data = load_health(temp_repo)
        assert data["version"] == 1
        assert data["agents"] == {}

    def test_check_spawn_warning_missing_file_no_crash(self, temp_repo: Path):
        """check_spawn_warning with missing health file returns None (no warning)."""
        result = check_spawn_warning(temp_repo, "Claude-9@claude")
        assert result is None

    def test_get_health_indicator_unknown(self):
        """Unknown status with zero cooldown → ⚪ indicator."""
        assert get_health_indicator(STATUS_UNKNOWN, 0) == "⚪"

    def test_get_health_indicator_available(self):
        """Available status with zero cooldown → 🟢 indicator."""
        assert get_health_indicator(STATUS_AVAILABLE, 0) == "🟢"

    def test_get_health_indicator_cooldown(self):
        """Cooldown status → 🟡 indicator."""
        assert get_health_indicator(STATUS_COOLDOWN, 100) == "🟡"

    def test_get_health_indicator_offline(self):
        """Offline status → 🔴 indicator."""
        assert get_health_indicator(STATUS_OFFLINE, 0) == "🔴"


# ---------------------------------------------------------------------------
# 6. CLI integration: wea health mark via subprocess
# ---------------------------------------------------------------------------

class TestCLIIntegration:
    """Integration tests invoking the CLI directly."""

    def _run(self, args: list[str], cwd: Path) -> subprocess.CompletedProcess:
        repo_root = Path(__file__).parent.parent
        env = {**__import__("os").environ, "PYTHONPATH": str(repo_root / "src")}
        return subprocess.run(
            [sys.executable, "src/wea_cli/cli.py", "--root", str(cwd), *args],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
            env=env,
        )

    def test_health_mark_error_creates_file(self, temp_repo: Path):
        """wea health mark <agent> error creates health file with correct state."""
        result = self._run(["health", "mark", "Claude-9@claude", "error"], temp_repo)
        assert result.returncode == 0, result.stderr
        health_path = temp_repo / "ledger" / "agent_health.json"
        assert health_path.exists()
        data = json.loads(health_path.read_text())
        record = data["agents"]["Claude-9@claude"]
        assert record["status"] == STATUS_COOLDOWN
        assert record["cooldown_score"] == 100

    def test_health_mark_recovered_resets_state(self, temp_repo: Path):
        """wea health mark <agent> recovered sets status=available, cooldown=0."""
        self._run(["health", "mark", "Claude-9@claude", "error"], temp_repo)
        result = self._run(["health", "mark", "Claude-9@claude", "recovered"], temp_repo)
        assert result.returncode == 0
        data = json.loads((temp_repo / "ledger" / "agent_health.json").read_text())
        record = data["agents"]["Claude-9@claude"]
        assert record["status"] == STATUS_AVAILABLE
        assert record["cooldown_score"] == 0

    def test_health_report_no_file(self, temp_repo: Path):
        """wea health report with no health file exits 0 with helpful message."""
        result = self._run(["health", "report"], temp_repo)
        assert result.returncode == 0
        assert "No health data" in result.stdout

    def test_health_mark_invalid_event(self, temp_repo: Path):
        """wea health mark with invalid event exits non-zero."""
        result = self._run(["health", "mark", "Claude-9@claude", "bogus"], temp_repo)
        assert result.returncode != 0
