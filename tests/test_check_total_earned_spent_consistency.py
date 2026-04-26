"""Tests for scripts/check_total_earned_spent_consistency.py.

All tests are fully in-memory; no real ledger files are accessed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from check_total_earned_spent_consistency import (  # noqa: E402
    check_consistency,
    compute_earned_spent,
    run,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stored(total_earned: int = 0, total_spent: int = 0) -> dict[str, Any]:
    return {"balance": total_earned - total_spent, "total_earned": total_earned, "total_spent": total_spent}


# ---------------------------------------------------------------------------
# compute_earned_spent
# ---------------------------------------------------------------------------


def test_empty_events_returns_empty_dicts() -> None:
    earned, spent = compute_earned_spent([])
    assert earned == {}
    assert spent == {}


def test_payment_credits_agent() -> None:
    events = [{"type": "payment", "agent": "alice@x", "amount": 50}]
    earned, spent = compute_earned_spent(events)
    assert earned.get("alice@x") == 50
    assert spent == {}


def test_accept_credits_agent() -> None:
    events = [{"type": "accept", "agent": "bob@x", "amount": 20}]
    earned, spent = compute_earned_spent(events)
    assert earned.get("bob@x") == 20
    assert spent == {}


def test_payment_ignores_zero_and_negative() -> None:
    events = [
        {"type": "payment", "agent": "alice@x", "amount": 0},
        {"type": "payment", "agent": "alice@x", "amount": -10},
    ]
    earned, spent = compute_earned_spent(events)
    assert earned.get("alice@x", 0) == 0


def test_trajectory_mint_multi_agent_format() -> None:
    """Multi-agent trajectory_mint credits per_agent amounts."""
    events = [
        {
            "type": "trajectory_mint",
            "agents": ["alice@x", "bob@x"],
            "per_agent": [10, 15],
            "amount": 25,
        }
    ]
    earned, spent = compute_earned_spent(events)
    assert earned.get("alice@x") == 10
    assert earned.get("bob@x") == 15


def test_trajectory_mint_single_agent_format() -> None:
    """Single-agent trajectory_mint uses agent + amount fields."""
    events = [
        {"type": "trajectory_mint", "agent": "charlie@x", "amount": 30}
    ]
    earned, spent = compute_earned_spent(events)
    assert earned.get("charlie@x") == 30


def test_trajectory_mint_accumulates_across_events() -> None:
    events = [
        {"type": "trajectory_mint", "agent": "alice@x", "amount": 20},
        {"type": "trajectory_mint", "agent": "alice@x", "amount": 30},
    ]
    earned, spent = compute_earned_spent(events)
    assert earned.get("alice@x") == 50


def test_trajectory_mint_partial_per_agent_list() -> None:
    """per_agent shorter than agents list — extra agents get nothing."""
    events = [
        {
            "type": "trajectory_mint",
            "agents": ["alice@x", "bob@x", "charlie@x"],
            "per_agent": [10, 20],
            "amount": 30,
        }
    ]
    earned, spent = compute_earned_spent(events)
    assert earned.get("alice@x") == 10
    assert earned.get("bob@x") == 20
    assert earned.get("charlie@x", 0) == 0


def test_escrow_create_debits_author() -> None:
    events = [{"type": "escrow_create", "author": "alice@x", "amount": 40, "issue": 1}]
    earned, spent = compute_earned_spent(events)
    assert spent.get("alice@x") == 40
    assert earned.get("alice@x", 0) == 0


def test_escrow_return_counts_only_with_matching_escrow_create() -> None:
    events = [
        {"type": "escrow_create", "author": "alice@x", "amount": 40, "issue": 7},
        {"type": "escrow_return", "recipient": "alice@x", "amount": 40, "issue": 7},
    ]
    earned, spent = compute_earned_spent(events)
    assert earned.get("alice@x") == 40
    assert spent.get("alice@x") == 40


def test_escrow_return_skipped_without_matching_escrow_create() -> None:
    """Old-format escrow (not escrow_create) means escrow_return is excluded."""
    events = [
        {"type": "escrow", "agent": "bob@x", "amount": 23, "issue": 99},
        {"type": "escrow_return", "author": "bob@x", "amount": 23, "issue": 99},
    ]
    earned, spent = compute_earned_spent(events)
    assert earned.get("bob@x", 0) == 0
    assert spent.get("bob@x", 0) == 0


def test_escrow_return_author_fallback() -> None:
    events = [
        {"type": "escrow_create", "author": "alice@x", "amount": 30, "issue": 5},
        {"type": "escrow_return", "author": "alice@x", "amount": 30, "issue": 5},
    ]
    earned, spent = compute_earned_spent(events)
    assert earned.get("alice@x") == 30


def test_escrow_return_agent_field_fallback() -> None:
    events = [
        {"type": "escrow_create", "author": "alice@x", "amount": 15, "issue": 10},
        {"type": "escrow_return", "agent": "alice@x", "amount": 15, "issue": 10},
    ]
    earned, spent = compute_earned_spent(events)
    assert earned.get("alice@x") == 15


def test_compatibility_events_not_counted() -> None:
    """economy_reset, agent_removal, reversal do not affect earned/spent."""
    events = [
        {"type": "economy_reset", "agents_zeroed": ["alice@x"]},
        {"type": "agent_removal", "agent": "alice@x"},
        {"type": "reversal", "agent": "alice@x", "amount": 100},
        {"type": "registration_confirmed", "agent": "alice@x", "previous_id": "old@x"},
    ]
    earned, spent = compute_earned_spent(events)
    assert earned.get("alice@x", 0) == 0
    assert spent.get("alice@x", 0) == 0


# ---------------------------------------------------------------------------
# check_consistency
# ---------------------------------------------------------------------------


def test_all_counters_match_returns_pass() -> None:
    stored = {
        "alice@x": _stored(total_earned=50, total_spent=10),
    }
    computed_earned = {"alice@x": 50}
    computed_spent = {"alice@x": 10}
    status, violations, warnings, summary = check_consistency(
        stored, computed_earned, computed_spent
    )
    assert status == "PASS"
    assert violations == []


def test_total_earned_off_by_one_returns_fail() -> None:
    stored = {"alice@x": _stored(total_earned=101, total_spent=0)}
    computed_earned = {"alice@x": 100}
    computed_spent: dict[str, int] = {}
    status, violations, _, _ = check_consistency(stored, computed_earned, computed_spent)
    assert status == "FAIL"
    assert len(violations) == 1
    v = violations[0]
    assert v["agent"] == "alice@x"
    assert v["field"] == "total_earned"
    assert v["stored"] == 101
    assert v["computed"] == 100


def test_total_spent_off_by_one_returns_fail() -> None:
    stored = {"alice@x": _stored(total_earned=0, total_spent=51)}
    computed_earned: dict[str, int] = {}
    computed_spent: dict[str, int] = {}  # computed is 0
    status, violations, _, _ = check_consistency(stored, computed_earned, computed_spent)
    assert status == "FAIL"
    assert len(violations) == 1
    v = violations[0]
    assert v["agent"] == "alice@x"
    assert v["field"] == "total_spent"
    assert v["stored"] == 51
    assert v["computed"] == 0


def test_agent_history_only_is_warning_not_fail() -> None:
    """Agent in history but absent from stored → WARNING, not FAIL."""
    stored: dict[str, Any] = {}
    computed_earned = {"ghost@x": 50}
    computed_spent: dict[str, int] = {}
    status, violations, warnings, _ = check_consistency(
        stored, computed_earned, computed_spent
    )
    assert status == "PASS"
    assert violations == []
    assert any(w["agent"] == "ghost@x" for w in warnings)


def test_trajectory_mint_included_in_earned() -> None:
    """trajectory_mint amounts must appear in computed_earned and satisfy consistency."""
    events = [
        {
            "type": "trajectory_mint",
            "agents": ["alice@x"],
            "per_agent": [57],
            "amount": 57,
            "issue": 842,
        }
    ]
    earned, spent = compute_earned_spent(events)
    stored = {"alice@x": _stored(total_earned=57, total_spent=0)}
    status, violations, _, _ = check_consistency(stored, earned, spent)
    assert status == "PASS"
    assert violations == []


def test_agent0_excluded_from_violations() -> None:
    """agent0@system is never reported as a violation regardless of mismatch."""
    stored = {"agent0@system": _stored(total_earned=9999, total_spent=1234)}
    computed_earned = {"agent0@system": 0}
    computed_spent: dict[str, int] = {}
    status, violations, _, _ = check_consistency(stored, computed_earned, computed_spent)
    assert status == "PASS"
    assert all(v["agent"] != "agent0@system" for v in violations)


def test_both_fields_diverge_for_same_agent() -> None:
    stored = {"alice@x": _stored(total_earned=100, total_spent=50)}
    computed_earned = {"alice@x": 80}
    computed_spent = {"alice@x": 30}
    status, violations, _, _ = check_consistency(stored, computed_earned, computed_spent)
    assert status == "FAIL"
    fields = {v["field"] for v in violations if v["agent"] == "alice@x"}
    assert "total_earned" in fields
    assert "total_spent" in fields


def test_empty_stored_and_history_pass() -> None:
    status, violations, warnings, summary = check_consistency({}, {}, {})
    assert status == "PASS"
    assert violations == []
    assert "0 VIOLATION" in summary


def test_multiple_agents_only_diverging_flagged() -> None:
    stored = {
        "alice@x": _stored(total_earned=100, total_spent=0),
        "bob@x": _stored(total_earned=200, total_spent=0),
    }
    computed_earned = {"alice@x": 90, "bob@x": 200}
    computed_spent: dict[str, int] = {}
    status, violations, _, _ = check_consistency(stored, computed_earned, computed_spent)
    assert status == "FAIL"
    flagged = {v["agent"] for v in violations}
    assert "alice@x" in flagged
    assert "bob@x" not in flagged


# ---------------------------------------------------------------------------
# run() — integration via tmp_path
# ---------------------------------------------------------------------------


def _write_ledger(
    tmp_path: Path,
    agents: dict[str, Any],
    history_lines: list[str] | None = None,
) -> None:
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    history_dir = ledger_dir / "history"
    history_dir.mkdir()
    balances = {"version": 1, "agents": agents}
    (ledger_dir / "balances.json").write_text(json.dumps(balances), encoding="utf-8")
    if history_lines:
        content = "\n".join(history_lines) + "\n"
        (history_dir / "2026-01-01.jsonl").write_text(content, encoding="utf-8")


def test_run_clean_ledger_pass(tmp_path: Path) -> None:
    _write_ledger(
        tmp_path,
        agents={"alice@x": _stored(total_earned=50, total_spent=0)},
        history_lines=[
            json.dumps({"type": "payment", "agent": "alice@x", "amount": 50}),
        ],
    )
    result, passed = run(tmp_path)
    assert passed is True
    assert result["status"] == "PASS"
    assert result["violations"] == []


def test_run_earned_mismatch_fail(tmp_path: Path) -> None:
    _write_ledger(
        tmp_path,
        agents={"alice@x": _stored(total_earned=99, total_spent=0)},
        history_lines=[
            json.dumps({"type": "payment", "agent": "alice@x", "amount": 50}),
        ],
    )
    result, passed = run(tmp_path)
    assert passed is False
    assert result["status"] == "FAIL"
    assert any(v["field"] == "total_earned" for v in result["violations"])


def test_run_spent_mismatch_fail(tmp_path: Path) -> None:
    _write_ledger(
        tmp_path,
        agents={
            "agent0@system": _stored(total_earned=0, total_spent=0),
            "alice@x": _stored(total_earned=0, total_spent=99),
        },
        history_lines=[
            json.dumps({"type": "escrow_create", "author": "alice@x", "amount": 50, "issue": 1}),
        ],
    )
    result, passed = run(tmp_path)
    assert passed is False
    assert result["status"] == "FAIL"
    assert any(v["field"] == "total_spent" for v in result["violations"])


def test_run_trajectory_mint_included_in_earned(tmp_path: Path) -> None:
    """trajectory_mint counts toward computed_earned and satisfies consistency."""
    _write_ledger(
        tmp_path,
        agents={"alice@x": _stored(total_earned=57, total_spent=0)},
        history_lines=[
            json.dumps({
                "type": "trajectory_mint",
                "agents": ["alice@x"],
                "per_agent": [57],
                "amount": 57,
                "issue": 1,
            }),
        ],
    )
    result, passed = run(tmp_path)
    assert passed is True
    assert result["status"] == "PASS"


def test_run_history_only_agent_warning_not_fail(tmp_path: Path) -> None:
    _write_ledger(
        tmp_path,
        agents={},
        history_lines=[
            json.dumps({"type": "payment", "agent": "ghost@x", "amount": 10}),
        ],
    )
    result, passed = run(tmp_path)
    assert passed is True
    assert result["status"] == "PASS"
    assert any(w["agent"] == "ghost@x" for w in result["warnings"])


def test_run_missing_balances_json_fail(tmp_path: Path) -> None:
    (tmp_path / "ledger").mkdir()
    result, passed = run(tmp_path)
    assert passed is False
    assert result["status"] == "FAIL"
