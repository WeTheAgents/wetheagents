from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import check_last_updated_freshness as checker  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_balances(root: Path, *, last_updated: str | None, include_field: bool = True) -> None:
    payload: dict = {"agents": {"Claude-1@claude": {"balance": 100}}}
    if include_field:
        payload["last_updated"] = last_updated
    ledger_dir = root / "ledger"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    (ledger_dir / "balances.json").write_text(json.dumps(payload), encoding="utf-8")


def _append_history_event(root: Path, *, ts_field: str, ts_value: str, filename: str = "2026-04-24.jsonl") -> None:
    history_dir = root / "ledger" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    line = json.dumps({ts_field: ts_value, "type": "escrow_create", "amount": 10})
    path = history_dir / filename
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(existing + line + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Core cases from the spec
# ---------------------------------------------------------------------------

def test_fresh_timestamp_passes(tmp_path: Path) -> None:
    _write_balances(tmp_path, last_updated="2026-04-24T09:00:00Z")
    _append_history_event(tmp_path, ts_field="ts", ts_value="2026-04-24T08:30:00Z")

    report = checker.check_freshness(tmp_path)

    assert report["pass"] is True
    assert report["last_updated"] == "2026-04-24T09:00:00Z"
    assert report["max_history_ts"] == "2026-04-24T08:30:00Z"
    assert report["delta_seconds"] == pytest.approx(1800.0)


def test_stale_timestamp_fails(tmp_path: Path) -> None:
    _write_balances(tmp_path, last_updated="2026-04-24T08:00:00Z")
    _append_history_event(tmp_path, ts_field="ts", ts_value="2026-04-24T08:30:00Z")

    report = checker.check_freshness(tmp_path)

    assert report["pass"] is False
    assert "1800.0s behind" in report["reason"]
    assert report["delta_seconds"] == pytest.approx(-1800.0)


def test_no_history_events_passes(tmp_path: Path) -> None:
    _write_balances(tmp_path, last_updated="2026-04-24T08:00:00Z")
    (tmp_path / "ledger" / "history").mkdir(parents=True, exist_ok=True)

    report = checker.check_freshness(tmp_path)

    assert report["pass"] is True
    assert report["max_history_ts"] is None
    assert "no history events" in report["reason"]


def test_missing_last_updated_field_fails(tmp_path: Path) -> None:
    _write_balances(tmp_path, last_updated=None, include_field=False)
    _append_history_event(tmp_path, ts_field="ts", ts_value="2026-04-24T08:30:00Z")

    report = checker.check_freshness(tmp_path)

    assert report["pass"] is False
    assert "missing" in report["reason"]


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_equal_timestamps_is_fresh(tmp_path: Path) -> None:
    """last_updated == max_history_ts satisfies the >= condition."""
    _write_balances(tmp_path, last_updated="2026-04-24T08:30:00Z")
    _append_history_event(tmp_path, ts_field="ts", ts_value="2026-04-24T08:30:00Z")

    report = checker.check_freshness(tmp_path)

    assert report["pass"] is True
    assert report["delta_seconds"] == pytest.approx(0.0)


def test_null_last_updated_fails(tmp_path: Path) -> None:
    """JSON null in last_updated is treated as missing."""
    _write_balances(tmp_path, last_updated=None, include_field=True)

    report = checker.check_freshness(tmp_path)

    assert report["pass"] is False
    assert "missing" in report["reason"]


def test_missing_history_dir_passes(tmp_path: Path) -> None:
    """No ledger/history directory at all → no events → pass."""
    _write_balances(tmp_path, last_updated="2026-04-24T08:00:00Z")

    report = checker.check_freshness(tmp_path)

    assert report["pass"] is True
    assert report["max_history_ts"] is None


def test_timestamp_field_picked_up(tmp_path: Path) -> None:
    """Events using 'timestamp' field (trajectory_mint style) must be recognised."""
    _write_balances(tmp_path, last_updated="2026-04-24T05:00:00Z")
    _append_history_event(tmp_path, ts_field="timestamp", ts_value="2026-04-24T04:49:57Z")

    report = checker.check_freshness(tmp_path)

    assert report["pass"] is True
    assert report["max_history_ts"] == "2026-04-24T04:49:57Z"


def test_max_picked_across_multiple_files(tmp_path: Path) -> None:
    _write_balances(tmp_path, last_updated="2026-04-24T09:00:00Z")
    _append_history_event(tmp_path, ts_field="ts", ts_value="2026-04-20T10:00:00Z", filename="2026-04-20.jsonl")
    _append_history_event(tmp_path, ts_field="ts", ts_value="2026-04-24T08:45:00Z", filename="2026-04-24.jsonl")
    _append_history_event(tmp_path, ts_field="ts", ts_value="2026-04-23T23:59:59Z", filename="2026-04-23.jsonl")

    report = checker.check_freshness(tmp_path)

    assert report["pass"] is True
    assert report["max_history_ts"] == "2026-04-24T08:45:00Z"


def test_max_picked_across_multiple_events_same_file(tmp_path: Path) -> None:
    _write_balances(tmp_path, last_updated="2026-04-24T09:00:00Z")
    _append_history_event(tmp_path, ts_field="ts", ts_value="2026-04-24T08:00:00Z")
    _append_history_event(tmp_path, ts_field="ts", ts_value="2026-04-24T08:45:00Z")

    report = checker.check_freshness(tmp_path)

    assert report["pass"] is True
    assert report["max_history_ts"] == "2026-04-24T08:45:00Z"


def test_invalid_json_lines_skipped(tmp_path: Path) -> None:
    """Corrupt lines in history files must not crash the check."""
    _write_balances(tmp_path, last_updated="2026-04-24T09:00:00Z")
    history_dir = tmp_path / "ledger" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    (history_dir / "2026-04-24.jsonl").write_text(
        "not-valid-json\n"
        + json.dumps({"ts": "2026-04-24T08:00:00Z", "type": "escrow_create"}) + "\n",
        encoding="utf-8",
    )

    report = checker.check_freshness(tmp_path)

    assert report["pass"] is True
    assert report["max_history_ts"] == "2026-04-24T08:00:00Z"


def test_main_exit_zero_for_fresh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_balances(tmp_path, last_updated="2026-04-24T09:00:00Z")
    _append_history_event(tmp_path, ts_field="ts", ts_value="2026-04-24T08:30:00Z")

    monkeypatch.setattr(sys, "argv", ["check_last_updated_freshness.py", "--root", str(tmp_path)])
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stdout)

    exit_code = checker.main()

    assert exit_code == 0
    output = stdout.getvalue()
    assert "PASS" in output
    assert "last_updated" in output


def test_main_exit_one_for_stale(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_balances(tmp_path, last_updated="2026-04-24T08:00:00Z")
    _append_history_event(tmp_path, ts_field="ts", ts_value="2026-04-24T08:30:00Z")

    monkeypatch.setattr(sys, "argv", ["check_last_updated_freshness.py", "--root", str(tmp_path)])
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stdout)

    exit_code = checker.main()

    assert exit_code == 1
    assert "FAIL" in stdout.getvalue()
