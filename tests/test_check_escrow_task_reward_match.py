"""Tests for scripts/check_escrow_task_reward_match.py."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import check_escrow_task_reward_match as checker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _escrows(active: dict) -> dict:
    return {"version": 1, "active": active}


def _tasks(entries: dict) -> dict:
    return entries


def _run(
    active: dict | None = None,
    task_entries: dict | None = None,
    events: list | None = None,
) -> dict:
    """Helper to run the check with synthetic data."""
    escrows = _escrows(active or {})
    tasks = _tasks(task_entries or {})
    return checker.run_check(
        Path("/fake/root"),
        escrows=escrows,
        tasks=tasks,
        events=events or [],
    )


# ---------------------------------------------------------------------------
# Active escrow checks
# ---------------------------------------------------------------------------

def test_active_exact_match_reward_wea_pass() -> None:
    """Escrow amount == reward_wea → PASS."""
    result = _run(
        active={"100": {"amount": 32, "type": "pod"}},
        task_entries={"100": {"reward_wea": 32, "reward_type": "pod"}},
    )
    assert result["status"] == "PASS"
    assert result["violations"] == []


def test_active_exact_match_legacy_reward_pass() -> None:
    """Escrow amount == legacy reward field → PASS."""
    result = _run(
        active={"200": {"amount": 25, "type": "pod"}},
        task_entries={"200": {"reward": 25, "mechanic": "best_x"}},
    )
    assert result["status"] == "PASS"
    assert result["violations"] == []


def test_active_amount_exceeds_reward_fail() -> None:
    """Escrow amount > task reward → FAIL."""
    result = _run(
        active={"300": {"amount": 40, "type": "pod"}},
        task_entries={"300": {"reward_wea": 32}},
    )
    assert result["status"] == "FAIL"
    assert len(result["violations"]) == 1
    v = result["violations"][0]
    assert v["source"] == "active"
    assert v["issue"] == "300"
    assert v["escrow_amount"] == 40
    assert v["expected_reward"] == 32


def test_active_amount_below_reward_nonprogressive_fail() -> None:
    """Escrow amount < task reward (non-progressive) → FAIL."""
    result = _run(
        active={"400": {"amount": 20, "type": "pod"}},
        task_entries={"400": {"reward_wea": 25}},
    )
    assert result["status"] == "FAIL"
    assert result["violations"][0]["escrow_amount"] == 20
    assert result["violations"][0]["expected_reward"] == 25


def test_active_progressive_remaining_budget_pass() -> None:
    """Progressive escrow with amount < reward (remaining budget) → PASS."""
    result = _run(
        active={"308": {"amount": 8, "type": "progressive", "slots": 3, "paid_count": 2}},
        task_entries={"308": {"reward": 10, "mechanic": "progressive"}},
    )
    assert result["status"] == "PASS"
    assert result["violations"] == []


def test_active_linear_remaining_budget_pass() -> None:
    """Linear escrow with amount < reward (remaining budget) → PASS."""
    result = _run(
        active={"500": {"amount": 3, "type": "linear", "paid_count": 1}},
        task_entries={"500": {"reward": 6}},
    )
    assert result["status"] == "PASS"
    assert result["violations"] == []


def test_active_progressive_exceeds_reward_fail() -> None:
    """Progressive escrow amount > reward → FAIL (over-escrowed)."""
    result = _run(
        active={"600": {"amount": 15, "type": "progressive"}},
        task_entries={"600": {"reward_wea": 10}},
    )
    assert result["status"] == "FAIL"
    v = result["violations"][0]
    assert v["source"] == "active"
    assert "progressive" in v["detail"]


def test_active_task_missing_from_index_skipped() -> None:
    """Active escrow for task not in task_index → skipped, not a violation."""
    result = _run(
        active={"999": {"amount": 34, "type": "pod"}},
        task_entries={},
    )
    assert result["status"] == "PASS"
    assert result["violations"] == []
    assert any(s["issue"] == "999" for s in result["skipped"])
    skipped = [s for s in result["skipped"] if s["issue"] == "999"][0]
    assert "not in task_index" in skipped["reason"]


def test_active_task_no_reward_field_skipped() -> None:
    """Task in index but with no reward field → skipped gracefully."""
    result = _run(
        active={"700": {"amount": 20, "type": "pod"}},
        task_entries={"700": {"title": "No reward here", "status": "open"}},
    )
    assert result["status"] == "PASS"
    assert result["violations"] == []
    assert any(s["issue"] == "700" for s in result["skipped"])


def test_active_gauntlet_task_exact_match_pass() -> None:
    """Gauntlet task: reward = 19 + slot stored in task_index, escrow matches → PASS."""
    # T4S13: reward = 19 + 13 = 32
    result = _run(
        active={"516": {"amount": 32, "type": "pod"}},
        task_entries={"516": {"reward": 32, "mechanic": "every_good",
                               "title": "[Gauntlet T4S13] task_index.json schema validator"}},
    )
    assert result["status"] == "PASS"
    assert result["violations"] == []


def test_active_gauntlet_task_mismatch_fail() -> None:
    """Gauntlet task: reward = 19 + slot, escrow has wrong amount → FAIL."""
    # T1S15: reward = 19 + 15 = 34; escrow wrongly says 30
    result = _run(
        active={"513": {"amount": 30, "type": "pod"}},
        task_entries={"513": {"reward_wea": 34, "reward_type": "pod",
                               "title": "[Gauntlet T1S15] check_balances_earned_consistency.py"}},
    )
    assert result["status"] == "FAIL"
    v = result["violations"][0]
    assert v["issue"] == "513"
    assert v["escrow_amount"] == 30
    assert v["expected_reward"] == 34


# ---------------------------------------------------------------------------
# History escrow_create checks
# ---------------------------------------------------------------------------

def test_history_exact_match_pass() -> None:
    """History escrow_create amount == task reward → PASS."""
    events = [{"type": "escrow_create", "issue": 257, "amount": 25}]
    result = _run(
        task_entries={"257": {"reward": 25, "mechanic": "best_x"}},
        events=events,
    )
    assert result["status"] == "PASS"
    assert result["violations"] == []


def test_history_mismatch_fail() -> None:
    """History escrow_create amount != task reward → FAIL."""
    events = [{"type": "escrow_create", "issue": 101, "amount": 20}]
    result = _run(
        task_entries={"101": {"reward_wea": 25}},
        events=events,
    )
    assert result["status"] == "FAIL"
    v = result["violations"][0]
    assert v["source"] == "history"
    assert v["issue"] == "101"
    assert v["escrow_amount"] == 20
    assert v["expected_reward"] == 25


def test_history_task_missing_from_index_skipped() -> None:
    """History escrow_create for task not in task_index → skipped."""
    events = [{"type": "escrow_create", "issue": 999, "amount": 32}]
    result = _run(
        task_entries={},
        events=events,
    )
    assert result["status"] == "PASS"
    assert result["violations"] == []
    assert any(s["issue"] == "999" for s in result["skipped"])


def test_history_non_escrow_create_ignored() -> None:
    """Non escrow_create events in history are not checked."""
    events = [
        {"type": "payment", "issue": 102, "amount": 999},
        {"type": "escrow_return", "issue": 102, "amount": 999},
    ]
    result = _run(
        task_entries={"102": {"reward": 25}},
        events=events,
    )
    assert result["status"] == "PASS"
    assert result["violations"] == []


def test_multiple_violations_accumulate() -> None:
    """Multiple mismatches accumulate into the violations list."""
    result = _run(
        active={
            "10": {"amount": 50, "type": "pod"},
            "20": {"amount": 1, "type": "pod"},
        },
        task_entries={
            "10": {"reward_wea": 30},
            "20": {"reward_wea": 30},
        },
        events=[
            {"type": "escrow_create", "issue": 30, "amount": 5},
        ],
    )
    # tasks dict has no entry for 30, so skipped. Both active violations remain.
    assert result["status"] == "FAIL"
    assert len(result["violations"]) == 2
    issues = {v["issue"] for v in result["violations"]}
    assert issues == {"10", "20"}


def test_empty_escrows_pass() -> None:
    """No active escrows and no history events → PASS."""
    result = _run()
    assert result["status"] == "PASS"
    assert result["violations"] == []
    assert result["skipped"] == []


def test_reward_wea_takes_precedence_over_reward() -> None:
    """reward_wea field takes precedence over legacy reward field."""
    # reward_wea=32, reward=20 — escrow matches reward_wea → PASS
    result = _run(
        active={"888": {"amount": 32, "type": "pod"}},
        task_entries={"888": {"reward_wea": 32, "reward": 20}},
    )
    assert result["status"] == "PASS"

    # escrow matches legacy reward (20) but not reward_wea (32) → FAIL
    result2 = _run(
        active={"888": {"amount": 20, "type": "pod"}},
        task_entries={"888": {"reward_wea": 32, "reward": 20}},
    )
    assert result2["status"] == "FAIL"


def test_real_ledger_passes(tmp_path: Path) -> None:
    """Script exits 0 on the real ledger (integration smoke test)."""
    repo_root = Path(__file__).resolve().parent.parent
    result = checker.run_check(repo_root)
    assert result["status"] == "PASS", (
        f"Real ledger check failed:\n{result}"
    )
