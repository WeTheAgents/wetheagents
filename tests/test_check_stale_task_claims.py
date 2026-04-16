"""Tests for scripts/check_stale_task_claims.py."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import scripts.check_stale_task_claims as stale_task_claims
from scripts.check_stale_task_claims import (
    _event_time,
    _latest_activity_by_issue,
    find_stale_claims,
    format_report,
    main,
    run_check,
)

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_stale_task_claims.py"
_NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)


def _ts(days_ago: float) -> str:
    return (_NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_task_index(tasks: dict[str, dict] | None = None) -> dict:
    return {"version": 1, "tasks": tasks or {}}


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + args,
        capture_output=True,
        text=True,
        check=False,
    )


def test_claim_older_than_7_days_with_no_history_after_is_stale() -> None:
    task_index = _make_task_index(
        {"10": {"status": "claimed", "agent": "alice@test", "claimed_at": _ts(8)}}
    )
    history = [{"issue": 10, "type": "claim", "created_at": _ts(8)}]

    result = find_stale_claims(task_index, history, now=_NOW)

    assert len(result) == 1
    assert result[0]["issue"] == 10


def test_claim_exactly_7_days_old_is_not_stale() -> None:
    task_index = _make_task_index(
        {"11": {"status": "claimed", "agent": "alice@test", "claimed_at": _ts(7)}}
    )

    result = find_stale_claims(task_index, [], now=_NOW)

    assert result == []


def test_recent_claim_is_not_stale() -> None:
    task_index = _make_task_index(
        {"12": {"status": "claimed", "agent": "alice@test", "claimed_at": _ts(2)}}
    )

    result = find_stale_claims(task_index, [], now=_NOW)

    assert result == []


def test_activity_after_claim_suppresses_stale_flag() -> None:
    task_index = _make_task_index(
        {"13": {"status": "claimed", "agent": "alice@test", "claimed_at": _ts(9)}}
    )
    history = [
        {"issue": 13, "type": "claim", "created_at": _ts(9)},
        {"issue": 13, "type": "comment", "created_at": _ts(3)},
    ]

    result = find_stale_claims(task_index, history, now=_NOW)

    assert result == []


def test_activity_before_claim_does_not_suppress_stale_flag() -> None:
    task_index = _make_task_index(
        {"14": {"status": "claimed", "agent": "alice@test", "claimed_at": _ts(8)}}
    )
    history = [{"issue": 14, "type": "escrow_create", "created_at": _ts(10)}]

    result = find_stale_claims(task_index, history, now=_NOW)

    assert len(result) == 1
    assert result[0]["issue"] == 14


def test_same_timestamp_as_claim_is_not_post_claim_activity() -> None:
    task_index = _make_task_index(
        {"15": {"status": "claimed", "agent": "alice@test", "claimed_at": _ts(8)}}
    )
    history = [{"issue": 15, "type": "claim", "created_at": _ts(8)}]

    result = find_stale_claims(task_index, history, now=_NOW)

    assert len(result) == 1


def test_non_claimed_tasks_are_ignored() -> None:
    task_index = _make_task_index(
        {"16": {"status": "open", "agent": "alice@test", "claimed_at": _ts(30)}}
    )

    result = find_stale_claims(task_index, [], now=_NOW)

    assert result == []


def test_missing_claimed_at_is_ignored() -> None:
    task_index = _make_task_index({"17": {"status": "claimed", "agent": "alice@test"}})

    result = find_stale_claims(task_index, [], now=_NOW)

    assert result == []


def test_malformed_claimed_at_is_ignored() -> None:
    task_index = _make_task_index(
        {"18": {"status": "claimed", "agent": "alice@test", "claimed_at": "nope"}}
    )

    result = find_stale_claims(task_index, [], now=_NOW)

    assert result == []


def test_non_numeric_issue_key_is_ignored_without_crashing() -> None:
    task_index = _make_task_index(
        {"abc": {"status": "claimed", "agent": "alice@test", "claimed_at": _ts(8)}}
    )

    result = find_stale_claims(task_index, [], now=_NOW)

    assert result == []


def test_timestamp_field_counts_as_activity() -> None:
    task_index = _make_task_index(
        {"19": {"status": "claimed", "agent": "alice@test", "claimed_at": _ts(8)}}
    )
    history = [{"issue": 19, "type": "trajectory_mint", "timestamp": _ts(1)}]

    result = find_stale_claims(task_index, history, now=_NOW)

    assert result == []


def test_event_time_prefers_event_at_then_created_at_then_timestamp() -> None:
    event = {"event_at": "bad", "created_at": "bad", "timestamp": _ts(1)}

    assert _event_time(event) == _NOW - timedelta(days=1)


def test_event_time_uses_event_at_before_timestamp() -> None:
    event = {"event_at": _ts(4), "timestamp": _ts(1)}

    assert _event_time(event) == _NOW - timedelta(days=4)


def test_latest_activity_by_issue_uses_latest_valid_timestamp() -> None:
    history = [
        {"issue": 20, "created_at": _ts(9)},
        {"issue": 20, "timestamp": _ts(2)},
        {"issue": 20, "created_at": "bad"},
        {"issue": "bad", "created_at": _ts(1)},
    ]

    latest = _latest_activity_by_issue(history)

    assert latest[20] == _NOW - timedelta(days=2)


def test_format_report_lists_stale_claim() -> None:
    report = format_report(
        [{"issue": 21, "agent": "alice@test", "claimed_at": _ts(8), "age_days": 8.0}]
    )

    assert "FAIL" in report
    assert "#21" in report
    assert "alice@test" in report


def test_run_check_detects_stale_claim_from_loaded_data(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        stale_task_claims,
        "load_json",
        lambda *_args, **_kwargs: _make_task_index(
            {"22": {"status": "claimed", "agent": "alice@test", "claimed_at": _ts(8)}}
        ),
    )
    monkeypatch.setattr(
        stale_task_claims,
        "_iter_history",
        lambda _root: [{"issue": 22, "type": "claim", "created_at": _ts(8)}],
    )

    stale_claims, has_stale_claims = run_check(Path("unused"), now=_NOW)

    assert has_stale_claims is True
    assert len(stale_claims) == 1


def test_run_check_missing_history_dir_is_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        stale_task_claims,
        "load_json",
        lambda *_args, **_kwargs: _make_task_index(),
    )
    monkeypatch.setattr(stale_task_claims, "_iter_history", lambda _root: [])

    stale_claims, has_stale_claims = run_check(Path("unused"), now=_NOW)

    assert stale_claims == []
    assert has_stale_claims is False


def test_run_check_ignores_invalid_history_timestamps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        stale_task_claims,
        "load_json",
        lambda *_args, **_kwargs: _make_task_index(
            {"23": {"status": "claimed", "agent": "alice@test", "claimed_at": _ts(8)}}
        ),
    )
    monkeypatch.setattr(
        stale_task_claims,
        "_iter_history",
        lambda _root: [
            {"issue": 23, "type": "comment", "event_at": "bad"},
            {"issue": 23, "type": "claim", "created_at": _ts(8)},
        ],
    )

    stale_claims, has_stale_claims = run_check(Path("unused"), now=_NOW)

    assert has_stale_claims is True
    assert len(stale_claims) == 1


def test_main_returns_zero_when_clean(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(stale_task_claims, "run_check", lambda *_args, **_kwargs: ([], False))

    exit_code = main(["--now", _NOW.strftime("%Y-%m-%dT%H:%M:%SZ")])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "OK" in captured.out


def test_main_returns_one_when_stale_claim_exists(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        stale_task_claims,
        "run_check",
        lambda *_args, **_kwargs: (
            [
                {
                    "issue": 24,
                    "agent": "alice@test",
                    "claimed_at": _ts(8),
                    "age_days": 8.0,
                }
            ],
            True,
        ),
    )

    exit_code = main(["--now", _NOW.strftime("%Y-%m-%dT%H:%M:%SZ")])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "#24" in captured.out


def test_cli_subprocess_real_repo_is_clean() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    result = _run(["--root", str(repo_root), "--now", _NOW.strftime("%Y-%m-%dT%H:%M:%SZ")])

    assert result.returncode == 0
    assert "OK" in result.stdout


def test_cli_invalid_now_returns_two() -> None:
    result = _run(["--now", "not-a-date"])

    assert result.returncode == 2
    assert "invalid --now" in result.stderr
