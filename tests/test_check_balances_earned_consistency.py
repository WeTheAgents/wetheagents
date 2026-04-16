"""Tests for scripts/check_balances_earned_consistency.py.

All tests are fully in-memory; no real ledger files are accessed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

# Make the scripts directory importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from check_balances_earned_consistency import (  # noqa: E402
    check_consistency,
    compute_earned_spent,
    main,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _agents(**kwargs: dict[str, Any]) -> dict[str, Any]:
    """Build a minimal stored_agents dict."""
    return kwargs


def _agent(total_earned: int = 0, total_spent: int = 0) -> dict[str, Any]:
    return {"balance": total_earned - total_spent, "total_earned": total_earned, "total_spent": total_spent}


# ---------------------------------------------------------------------------
# compute_earned_spent tests
# ---------------------------------------------------------------------------


def test_empty_events_returns_zero_dicts():
    """No events → both dicts empty."""
    earned, spent = compute_earned_spent([])
    assert earned == {}
    assert spent == {}


def test_payment_credits_agent():
    events = [{"type": "payment", "agent": "alice@x", "amount": 50}]
    earned, spent = compute_earned_spent(events)
    assert earned.get("alice@x") == 50
    assert spent == {}


def test_accept_credits_agent():
    events = [{"type": "accept", "agent": "bob@x", "amount": 20}]
    earned, spent = compute_earned_spent(events)
    assert earned.get("bob@x") == 20


def test_payment_ignores_zero_and_negative():
    events = [
        {"type": "payment", "agent": "alice@x", "amount": 0},
        {"type": "payment", "agent": "alice@x", "amount": -10},
    ]
    earned, spent = compute_earned_spent(events)
    assert earned.get("alice@x", 0) == 0


def test_trajectory_mint_multi_agent():
    """Multi-agent trajectory_mint credits each agent by per_agent slot."""
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


def test_trajectory_mint_single_agent():
    """Single-agent trajectory_mint uses agent + amount fields."""
    events = [
        {
            "type": "trajectory_mint",
            "agent": "charlie@x",
            "amount": 30,
        }
    ]
    earned, spent = compute_earned_spent(events)
    assert earned.get("charlie@x") == 30


def test_escrow_create_debits_author():
    events = [{"type": "escrow_create", "author": "alice@x", "amount": 40, "issue": 1}]
    earned, spent = compute_earned_spent(events)
    assert spent.get("alice@x") == 40
    assert earned.get("alice@x", 0) == 0


def test_escrow_return_credited_when_matching_escrow_create():
    """escrow_return credits recipient only if issue has escrow_create."""
    events = [
        {"type": "escrow_create", "author": "alice@x", "amount": 40, "issue": 7},
        {"type": "escrow_return", "recipient": "alice@x", "amount": 40, "issue": 7},
    ]
    earned, spent = compute_earned_spent(events)
    assert earned.get("alice@x") == 40
    assert spent.get("alice@x") == 40


def test_escrow_return_skipped_without_matching_escrow_create():
    """Old-format escrow_return (no matching escrow_create) must not count."""
    events = [
        # Old-format escrow — not escrow_create, so issue 99 is not registered.
        {"type": "escrow", "agent": "bob@x", "amount": 23, "issue": 99},
        {"type": "escrow_return", "author": "bob@x", "amount": 23, "issue": 99},
    ]
    earned, spent = compute_earned_spent(events)
    assert earned.get("bob@x", 0) == 0
    assert spent.get("bob@x", 0) == 0


def test_trajectory_mint_multiple_events_accumulate():
    """Multiple trajectory_mint events accumulate correctly per agent."""
    events = [
        {"type": "trajectory_mint", "agent": "alice@x", "amount": 20},
        {"type": "trajectory_mint", "agent": "alice@x", "amount": 30},
    ]
    earned, spent = compute_earned_spent(events)
    assert earned.get("alice@x") == 50


def test_compatibility_events_ignored():
    """economy_reset, agent_removal, reversal do not affect earned/spent."""
    events = [
        {"type": "economy_reset", "agents_zeroed": ["alice@x"]},
        {"type": "agent_removal", "agent": "alice@x"},
        {"type": "reversal", "agent": "alice@x", "amount": 100},
        {"type": "registration_confirmed", "agent": "alice@x", "previous_id": "old@x"},
    ]
    earned, spent = compute_earned_spent(events)
    # None of these should affect alice@x earned/spent.
    assert earned.get("alice@x", 0) == 0
    assert spent.get("alice@x", 0) == 0


# ---------------------------------------------------------------------------
# check_consistency tests
# ---------------------------------------------------------------------------


def test_clean_match_returns_pass():
    stored = _agents(**{"alice@x": _agent(total_earned=50, total_spent=0)})
    computed_earned = {"alice@x": 50}
    computed_spent: dict[str, int] = {}
    status, divergences, warnings, summary = check_consistency(
        stored, computed_earned, computed_spent
    )
    assert status == "PASS"
    assert divergences == []


def test_earned_inflated_returns_fail():
    """Stored total_earned > computed → FAIL."""
    stored = _agents(**{"alice@x": _agent(total_earned=100, total_spent=0)})
    computed_earned = {"alice@x": 80}
    computed_spent: dict[str, int] = {}
    status, divergences, _, _ = check_consistency(stored, computed_earned, computed_spent)
    assert status == "FAIL"
    div = divergences[0]
    assert div["agent"] == "alice@x"
    assert div["field"] == "total_earned"
    assert div["stored"] == 100
    assert div["computed"] == 80


def test_spent_inflated_returns_fail():
    """Stored total_spent > computed → FAIL."""
    stored = _agents(**{"alice@x": _agent(total_earned=0, total_spent=50)})
    computed_earned: dict[str, int] = {}
    computed_spent: dict[str, int] = {}  # nothing in history
    status, divergences, _, _ = check_consistency(stored, computed_earned, computed_spent)
    assert status == "FAIL"
    div = divergences[0]
    assert div["field"] == "total_spent"
    assert div["stored"] == 50
    assert div["computed"] == 0


def test_multiple_diverging_agents():
    stored = _agents(
        **{
            "alice@x": _agent(total_earned=100, total_spent=0),
            "bob@x": _agent(total_earned=200, total_spent=0),
        }
    )
    computed_earned = {"alice@x": 80, "bob@x": 200}
    computed_spent: dict[str, int] = {}
    status, divergences, _, _ = check_consistency(stored, computed_earned, computed_spent)
    assert status == "FAIL"
    agents_with_div = {d["agent"] for d in divergences}
    assert "alice@x" in agents_with_div
    assert "bob@x" not in agents_with_div


def test_missing_history_agent_is_warning_not_fail():
    """Agent with non-zero computed earned but absent from stored → warning, PASS."""
    stored: dict[str, Any] = {}  # empty balances
    computed_earned = {"ghost@x": 50}
    computed_spent: dict[str, int] = {}
    status, divergences, warnings, _ = check_consistency(
        stored, computed_earned, computed_spent
    )
    assert status == "PASS"
    assert divergences == []
    assert any(w["agent"] == "ghost@x" for w in warnings)


def test_agent0_excluded_from_divergences():
    """agent0@system is never reported as a divergence."""
    stored = _agents(**{"agent0@system": _agent(total_earned=9999, total_spent=1234)})
    computed_earned = {"agent0@system": 0}
    computed_spent: dict[str, int] = {}
    status, divergences, _, _ = check_consistency(stored, computed_earned, computed_spent)
    assert status == "PASS"
    assert all(d["agent"] != "agent0@system" for d in divergences)


def test_empty_balances_and_empty_history_pass():
    """No stored agents, no history → PASS with zero divergences."""
    status, divergences, warnings, summary = check_consistency({}, {}, {})
    assert status == "PASS"
    assert divergences == []
    assert "0 divergence" in summary


def test_escrow_return_author_fallback_counted():
    """escrow_return with no recipient field falls back to author field."""
    events = [
        {"type": "escrow_create", "author": "alice@x", "amount": 30, "issue": 5},
        # No 'recipient' field — fall back to 'author'
        {"type": "escrow_return", "author": "alice@x", "amount": 30, "issue": 5},
    ]
    earned, spent = compute_earned_spent(events)
    assert earned.get("alice@x") == 30
    assert spent.get("alice@x") == 30


def test_trajectory_mint_multi_agent_partial_per_agent():
    """If per_agent list is shorter than agents list, extra agents get nothing."""
    events = [
        {
            "type": "trajectory_mint",
            "agents": ["alice@x", "bob@x", "charlie@x"],
            "per_agent": [10, 20],  # only 2 entries for 3 agents
            "amount": 30,
        }
    ]
    earned, spent = compute_earned_spent(events)
    assert earned.get("alice@x") == 10
    assert earned.get("bob@x") == 20
    assert earned.get("charlie@x", 0) == 0


def test_both_earned_and_spent_diverge_for_same_agent():
    """When both total_earned and total_spent diverge, two entries reported."""
    stored = _agents(**{"alice@x": _agent(total_earned=100, total_spent=50)})
    computed_earned = {"alice@x": 80}
    computed_spent = {"alice@x": 30}
    status, divergences, _, _ = check_consistency(stored, computed_earned, computed_spent)
    assert status == "FAIL"
    fields = {d["field"] for d in divergences if d["agent"] == "alice@x"}
    assert "total_earned" in fields
    assert "total_spent" in fields


def test_escrow_return_agent_field_fallback_counted():
    """escrow_return falls back to 'agent' field when recipient and author absent."""
    events = [
        {"type": "escrow_create", "author": "alice@x", "amount": 15, "issue": 10},
        # No 'recipient' or 'author' — fall back to 'agent'
        {"type": "escrow_return", "agent": "alice@x", "amount": 15, "issue": 10},
    ]
    earned, spent = compute_earned_spent(events)
    assert earned.get("alice@x") == 15
    assert spent.get("alice@x") == 15


def test_main_json_output_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    """main() prints valid JSON with status PASS and exits 0 for a clean ledger."""
    import check_balances_earned_consistency as mod

    # Build minimal ledger structure in tmp_path
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    history_dir = ledger_dir / "history"
    history_dir.mkdir()

    balances = {
        "version": 1,
        "agents": {
            "agent0@system": {"balance": 100, "total_earned": 0, "total_spent": 0},
            "alice@x": {"balance": 50, "total_earned": 50, "total_spent": 0},
        },
    }
    (ledger_dir / "balances.json").write_text(json.dumps(balances), encoding="utf-8")

    # History: one payment to alice@x
    history_line = json.dumps({"type": "payment", "agent": "alice@x", "amount": 50})
    (history_dir / "2026-01-01.jsonl").write_text(history_line + "\n", encoding="utf-8")

    monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)

    exit_code = main()
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert exit_code == 0
    assert result["status"] == "PASS"
    assert result["divergences"] == []
    assert "summary" in result
