"""Tests for check_task_spec_completeness — task spec field completeness."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_task_spec_completeness import ERRORS, validate_task


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clear_errors():
    ERRORS.clear()
    yield
    ERRORS.clear()


def _make_open_task(**overrides) -> dict:
    """Minimal valid open task using the current schema field names."""
    base = {
        "title": "Some Task",
        "author": "agent0@system",
        "status": "open",
        "mechanic": "best_x",   # satisfies reward_type
        "reward": 10,            # satisfies budget
    }
    base.update(overrides)
    return base


def _make_claimed_task(**overrides) -> dict:
    base = _make_open_task(
        status="claimed",
        agent="alice@test",
        escrow_idem_key="idem-abc-123",
    )
    base.update(overrides)
    return base


def _make_paid_task(**overrides) -> dict:
    base = _make_open_task(status="paid")
    base.update(overrides)
    return base


def _make_paid_tracked_task(**overrides) -> dict:
    """Paid task that went through the tracked claim flow (has `agent`)."""
    base = _make_open_task(
        status="paid",
        agent="alice@test",
        accepted_at="2026-04-01T00:00:00Z",
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Tier 1 — All tasks
# ---------------------------------------------------------------------------

class TestAllTasksBase:
    def test_valid_open_task_no_errors(self):
        """A fully-specified open task should produce zero errors."""
        validate_task("100", _make_open_task())
        assert ERRORS == []

    def test_missing_reward_type_fails(self):
        """Task with neither reward_type nor mechanic must be flagged."""
        task = _make_open_task()
        del task["mechanic"]
        validate_task("101", task)
        assert any("reward_type" in e for e in ERRORS)

    def test_reward_type_field_accepted(self):
        """Spec-canonical `reward_type` field satisfies the reward-type check."""
        task = _make_open_task()
        del task["mechanic"]
        task["reward_type"] = "every_good"
        validate_task("102", task)
        assert ERRORS == []

    def test_missing_budget_fails(self):
        """Task with neither budget nor reward must be flagged."""
        task = _make_open_task()
        del task["reward"]
        validate_task("103", task)
        assert any("budget" in e for e in ERRORS)

    def test_budget_field_accepted(self):
        """Spec-canonical `budget` field satisfies the budget check."""
        task = _make_open_task()
        del task["reward"]
        task["budget"] = 15
        validate_task("104", task)
        assert ERRORS == []

    def test_missing_status_fails(self):
        """Task without a status field must be flagged."""
        task = _make_open_task()
        del task["status"]
        validate_task("105", task)
        assert any("status" in e for e in ERRORS)


# ---------------------------------------------------------------------------
# Tier 2 — Claimed / accepted
# ---------------------------------------------------------------------------

class TestClaimedAcceptedTier:
    def test_valid_claimed_task_no_errors(self):
        """A fully-specified claimed task should produce zero errors."""
        validate_task("200", _make_claimed_task())
        assert ERRORS == []

    def test_claimed_without_agent_fails(self):
        """Claimed task missing `agent` must be flagged."""
        task = _make_claimed_task()
        del task["agent"]
        validate_task("201", task)
        assert any("agent" in e for e in ERRORS)

    def test_claimed_without_escrow_idem_key_fails(self):
        """Claimed task missing `escrow_idem_key` must be flagged."""
        task = _make_claimed_task()
        del task["escrow_idem_key"]
        validate_task("202", task)
        assert any("escrow_idem_key" in e for e in ERRORS)

    def test_accepted_task_same_requirements(self):
        """Accepted task without escrow_idem_key must also be flagged."""
        task = _make_claimed_task(status="accepted")
        del task["escrow_idem_key"]
        validate_task("203", task)
        assert any("escrow_idem_key" in e for e in ERRORS)

    def test_open_task_not_subject_to_tier2(self):
        """Open task without agent/escrow_idem_key must NOT be flagged for those."""
        validate_task("204", _make_open_task())
        assert not any("escrow_idem_key" in e for e in ERRORS)
        assert not any("agent" in e for e in ERRORS)


# ---------------------------------------------------------------------------
# Tier 3 — Paid tasks
# ---------------------------------------------------------------------------

class TestPaidTier:
    def test_valid_paid_tracked_task_no_errors(self):
        """Paid task with agent + accepted_at should produce zero errors."""
        validate_task("300", _make_paid_tracked_task())
        assert ERRORS == []

    def test_paid_tracked_task_paid_at_accepted(self):
        """paid_at also satisfies the timestamp requirement."""
        task = _make_paid_tracked_task()
        del task["accepted_at"]
        task["paid_at"] = "2026-04-02T00:00:00Z"
        validate_task("301", task)
        assert ERRORS == []

    def test_paid_tracked_task_without_timestamp_fails(self):
        """Paid task with agent but no accepted_at/paid_at must be flagged."""
        task = _make_paid_tracked_task()
        del task["accepted_at"]
        validate_task("302", task)
        assert any("accepted_at" in e or "paid_at" in e for e in ERRORS)

    def test_paid_legacy_task_no_agent_exempt(self):
        """Paid task without agent (legacy) must NOT be flagged for missing timestamps."""
        task = _make_paid_task()
        # no agent, no accepted_at, no paid_at — legacy task
        validate_task("303", task)
        assert not any("accepted_at" in e or "paid_at" in e for e in ERRORS)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_tasks_dict_passes(self):
        """Iterating validate_task over zero tasks produces no errors."""
        # Simulates main()'s loop: `for issue, task in {}.items(): validate_task(...)`
        for issue, task in {}.items():
            validate_task(str(issue), task)
        assert ERRORS == []

    def test_non_dict_task_entry_flagged(self):
        """A task entry that is not a dict must be reported."""
        validate_task("400", "not-a-dict")  # type: ignore[arg-type]
        assert len(ERRORS) == 1
        assert "not a JSON object" in ERRORS[0]

    def test_multiple_gaps_all_reported(self):
        """Multiple missing fields must all be individually reported."""
        task = {"status": "claimed"}  # missing mechanic, reward, agent, escrow_idem_key
        validate_task("401", task)
        error_text = " ".join(ERRORS)
        assert "reward_type" in error_text
        assert "budget" in error_text
        assert "agent" in error_text
        assert "escrow_idem_key" in error_text

    def test_mixed_statuses_gated_correctly(self):
        """Each task is checked independently; errors are per-task."""
        good_open = _make_open_task()
        bad_claimed = _make_claimed_task()
        del bad_claimed["escrow_idem_key"]

        validate_task("500", good_open)
        count_after_open = len(ERRORS)
        validate_task("501", bad_claimed)
        count_after_claimed = len(ERRORS)

        assert count_after_open == 0
        assert count_after_claimed > count_after_open


# ---------------------------------------------------------------------------
# Integration test — run against the real task_index.json
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_real_task_index_passes(self):
        """Running the script on the actual ledger/task_index.json must exit 0."""
        script = Path(__file__).parent.parent / "scripts" / "check_task_spec_completeness.py"
        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"check_task_spec_completeness.py exited {result.returncode} on real data.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
