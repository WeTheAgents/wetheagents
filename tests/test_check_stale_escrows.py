"""Tests for scripts/check_stale_escrows.py."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.check_stale_escrows import (
    _load_claimed_issues,
    classify_escrows,
    format_report,
    run_check,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 4, 12, 0, 0, tzinfo=timezone.utc)


def _ts(days_ago: float) -> str:
    """Return an ISO 8601 UTC timestamp *days_ago* days before _NOW."""
    dt = _NOW - timedelta(days=days_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_escrows(entries: dict[str, dict]) -> dict:
    return {"version": 1, "active": entries}


def _make_tasks(entries: dict[str, dict] | None = None) -> dict:
    return {"version": 1, "tasks": entries or {}}


def _write_ledger(tmp_path: Path, escrows: dict, tasks: dict) -> Path:
    """Write escrows.json and task_index.json under tmp_path/ledger/."""
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    (ledger / "escrows.json").write_text(json.dumps(escrows), encoding="utf-8")
    (ledger / "task_index.json").write_text(json.dumps(tasks), encoding="utf-8")
    # run_check also needs balances.json for resolve_repo_root compatibility;
    # not required by run_check directly, so we skip it.
    return tmp_path


# ---------------------------------------------------------------------------
# _load_claimed_issues unit test
# ---------------------------------------------------------------------------


def test_load_claimed_issues_extracts_issue_numbers() -> None:
    """_load_claimed_issues parses claim| keys and returns their issue numbers."""
    idem_keys = {
        "keys": {
            "claim|42|Claude-1@claude": "2026-01-01T00:00:00Z",
            "claim|99|Codex-2@codex": "2026-01-02T00:00:00Z",
            "escrow|42|agent0@system": "2026-01-01T00:00:00Z",  # not a claim
            "accept|42|Claude-1@claude": "2026-01-05T00:00:00Z",  # not a claim
        }
    }
    result = _load_claimed_issues(idem_keys)
    assert result == {42, 99}


# ---------------------------------------------------------------------------
# classify_escrows unit tests
# ---------------------------------------------------------------------------


def test_clean_ledger_no_tiers() -> None:
    """Escrows younger than 7 days produce no tier entries."""
    escrows = _make_escrows({"1": {"created_at": _ts(3), "amount": 10}})
    tasks = _make_tasks()

    result = classify_escrows(escrows, tasks, now=_NOW)

    assert result["WARNING"] == []
    assert result["STALE"] == []
    assert result["FROZEN"] == []
    assert result["UNKNOWN"] == []


def test_7_day_warning_no_submissions() -> None:
    """Escrow exactly 7 days old with no accepted_agents → WARNING."""
    escrows = _make_escrows({"5": {"created_at": _ts(7), "amount": 20}})
    tasks = _make_tasks({"5": {"status": "open", "accepted_agents": []}})

    result = classify_escrows(escrows, tasks, now=_NOW)

    assert len(result["WARNING"]) == 1
    assert result["WARNING"][0]["issue"] == "5"
    assert result["WARNING"][0]["tier"] == "WARNING"
    assert result["STALE"] == []
    assert result["FROZEN"] == []


def test_8_day_warning_no_task_entry() -> None:
    """Escrow 8 days old with no task_index entry (no submissions) → WARNING."""
    escrows = _make_escrows({"9": {"created_at": _ts(8), "amount": 15}})
    tasks = _make_tasks()  # no task entry at all

    result = classify_escrows(escrows, tasks, now=_NOW)

    assert len(result["WARNING"]) == 1
    assert result["WARNING"][0]["issue"] == "9"


def test_7_day_with_submissions_not_flagged() -> None:
    """Escrow 7+ days old but with accepted_agents → not flagged."""
    escrows = _make_escrows({"10": {"created_at": _ts(8), "amount": 30}})
    tasks = _make_tasks({"10": {"accepted_agents": ["Claude-1@claude"]}})

    result = classify_escrows(escrows, tasks, now=_NOW)

    assert result["WARNING"] == []
    assert result["STALE"] == []
    assert result["FROZEN"] == []


def test_14_day_stale_no_submissions() -> None:
    """Escrow exactly 14 days old with no submissions → STALE (not WARNING)."""
    escrows = _make_escrows({"20": {"created_at": _ts(14), "amount": 25}})
    tasks = _make_tasks()

    result = classify_escrows(escrows, tasks, now=_NOW)

    assert len(result["STALE"]) == 1
    assert result["STALE"][0]["issue"] == "20"
    assert result["STALE"][0]["tier"] == "STALE"
    assert result["WARNING"] == []


def test_15_day_stale() -> None:
    """Escrow 15 days old with empty accepted_agents → STALE."""
    escrows = _make_escrows({"30": {"created_at": _ts(15), "amount": 10}})
    tasks = _make_tasks({"30": {"status": "open", "accepted_agents": None}})

    result = classify_escrows(escrows, tasks, now=_NOW)

    assert len(result["STALE"]) == 1


def test_21_day_frozen() -> None:
    """Escrow exactly 21 days old → FROZEN regardless of submissions."""
    escrows = _make_escrows({"50": {"created_at": _ts(21), "amount": 50}})
    tasks = _make_tasks({"50": {"accepted_agents": ["agent0@system"]}})

    result = classify_escrows(escrows, tasks, now=_NOW)

    assert len(result["FROZEN"]) == 1
    assert result["FROZEN"][0]["issue"] == "50"
    assert result["FROZEN"][0]["tier"] == "FROZEN"
    assert result["STALE"] == []
    assert result["WARNING"] == []


def test_25_day_frozen_no_submissions() -> None:
    """Escrow 25 days old → FROZEN, not double-counted in STALE."""
    escrows = _make_escrows({"60": {"created_at": _ts(25), "amount": 40}})
    tasks = _make_tasks()

    result = classify_escrows(escrows, tasks, now=_NOW)

    assert len(result["FROZEN"]) == 1
    assert result["STALE"] == []
    assert result["WARNING"] == []


def test_missing_created_at_handled_gracefully() -> None:
    """Escrow with missing created_at → UNKNOWN tier, no crash."""
    escrows = _make_escrows({"99": {"amount": 10}})
    tasks = _make_tasks()

    result = classify_escrows(escrows, tasks, now=_NOW)

    assert len(result["UNKNOWN"]) == 1
    assert result["UNKNOWN"][0]["issue"] == "99"
    assert result["UNKNOWN"][0]["age_days"] is None
    assert result["FROZEN"] == []


def test_null_created_at_handled_gracefully() -> None:
    """Escrow with created_at=null → UNKNOWN tier, no crash."""
    escrows = _make_escrows({"100": {"created_at": None, "amount": 5}})
    tasks = _make_tasks()

    result = classify_escrows(escrows, tasks, now=_NOW)

    assert len(result["UNKNOWN"]) == 1


def test_malformed_created_at_handled_gracefully() -> None:
    """Escrow with unparseable created_at string → UNKNOWN tier, no crash."""
    escrows = _make_escrows({"101": {"created_at": "not-a-date", "amount": 5}})
    tasks = _make_tasks()

    result = classify_escrows(escrows, tasks, now=_NOW)

    assert len(result["UNKNOWN"]) == 1


def test_recent_claim_not_flagged() -> None:
    """Escrow 6 days old (< 7) with no submissions → not flagged at all."""
    escrows = _make_escrows({"200": {"created_at": _ts(6.9), "amount": 10}})
    tasks = _make_tasks()

    result = classify_escrows(escrows, tasks, now=_NOW)

    assert result["WARNING"] == []
    assert result["STALE"] == []
    assert result["FROZEN"] == []


def test_stale_suppressed_when_issue_has_claim() -> None:
    """Escrow 15 days old with a claim in idem_keys → WARNING, not STALE."""
    escrows = _make_escrows({"40": {"created_at": _ts(15), "amount": 20}})
    tasks = _make_tasks()
    # Issue 40 was claimed — so STALE condition (no claims) is NOT met
    claimed = {40}

    result = classify_escrows(escrows, tasks, now=_NOW, claimed_issues=claimed)

    assert result["STALE"] == []
    # age >= 7d and no accepted_agents → falls through to WARNING
    assert len(result["WARNING"]) == 1
    assert result["WARNING"][0]["issue"] == "40"


def test_multiple_escrows_classified_independently() -> None:
    """Three escrows at different ages are each classified correctly."""
    escrows = _make_escrows({
        "1": {"created_at": _ts(5), "amount": 10},   # < 7 days → no tier
        "2": {"created_at": _ts(10), "amount": 20},  # 7-14 days, no subs → WARNING
        "3": {"created_at": _ts(22), "amount": 30},  # 21+ days → FROZEN
    })
    tasks = _make_tasks()

    result = classify_escrows(escrows, tasks, now=_NOW)

    assert len(result["WARNING"]) == 1
    assert result["WARNING"][0]["issue"] == "2"
    assert len(result["FROZEN"]) == 1
    assert result["FROZEN"][0]["issue"] == "3"
    assert result["STALE"] == []


# ---------------------------------------------------------------------------
# format_report tests
# ---------------------------------------------------------------------------


def test_format_report_clean() -> None:
    """Clean classified dict produces OK message."""
    classified = {"WARNING": [], "STALE": [], "FROZEN": [], "UNKNOWN": []}
    report = format_report(classified)
    assert "OK" in report
    assert "no stale" in report.lower()


def test_format_report_shows_frozen_issue() -> None:
    """FROZEN escrow appears in report with issue number."""
    classified = {
        "WARNING": [],
        "STALE": [],
        "FROZEN": [{"issue": "42", "age_days": 25.0, "created_at": "2026-03-10T00:00:00Z", "amount": 50, "tier": "FROZEN"}],
        "UNKNOWN": [],
    }
    report = format_report(classified)
    assert "FROZEN" in report
    assert "42" in report
    assert "50 WEA" in report


def test_format_report_shows_warning_issue() -> None:
    """WARNING escrow appears with age info."""
    classified = {
        "WARNING": [{"issue": "7", "age_days": 8.5, "created_at": "2026-03-26T00:00:00Z", "amount": 15, "tier": "WARNING"}],
        "STALE": [],
        "FROZEN": [],
        "UNKNOWN": [],
    }
    report = format_report(classified)
    assert "WARNING" in report
    assert "7" in report


# ---------------------------------------------------------------------------
# run_check integration tests (uses tmp_path ledger)
# ---------------------------------------------------------------------------


def test_run_check_clean_ledger(tmp_path: Path) -> None:
    """run_check on a ledger with only fresh escrows: no frozen, exits 0."""
    escrows = _make_escrows({"1": {"created_at": _ts(2), "amount": 10}})
    tasks = _make_tasks()
    _write_ledger(tmp_path, escrows, tasks)

    classified, has_frozen = run_check(tmp_path, now=_NOW)

    assert not has_frozen
    assert classified["FROZEN"] == []


def test_run_check_frozen_escrow_exits_1(tmp_path: Path) -> None:
    """run_check with a 21+ day escrow: has_frozen=True → exit code 1."""
    escrows = _make_escrows({"88": {"created_at": _ts(25), "amount": 30}})
    tasks = _make_tasks()
    _write_ledger(tmp_path, escrows, tasks)

    classified, has_frozen = run_check(tmp_path, now=_NOW)

    assert has_frozen
    assert len(classified["FROZEN"]) == 1
    assert classified["FROZEN"][0]["issue"] == "88"


def test_run_check_missing_escrows_file(tmp_path: Path) -> None:
    """run_check with no escrows.json defaults to empty active dict."""
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    (ledger / "task_index.json").write_text(json.dumps(_make_tasks()), encoding="utf-8")
    # No escrows.json — load_json should use default

    classified, has_frozen = run_check(tmp_path, now=_NOW)

    assert not has_frozen
    assert classified["FROZEN"] == []
