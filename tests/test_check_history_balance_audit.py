"""Tests for scripts/check_history_balance_audit.py

All tests are in-memory; no real files are read or written.

Required scenarios (task spec):
  1. clean match PASS
  2. one diverged agent FAIL (stored > history)
  3. stored balance less than history FAIL
  4. trajectory_mint credit correctly applied
  5. escrow_create debit correctly applied
  6. escrow_return credit correctly applied
  7. payment credit correctly applied
  8. empty history PASS (all zero balances)
  9. agent in history but not in balances FAIL
  10. multi-agent, only one diverges FAIL
"""

from __future__ import annotations

import pytest

from scripts.check_history_balance_audit import audit, compute_balances


# ---------------------------------------------------------------------------
# Test 1: clean match — all agents reconcile exactly
# ---------------------------------------------------------------------------

def test_clean_match_pass() -> None:
    events = [
        {"type": "trajectory_mint", "agents": ["Alice@claude"], "per_agent": [100]},
        {"type": "payment", "agent": "Alice@claude", "amount": 50},
    ]
    stored = {"Alice@claude": {"balance": 150}}
    computed = compute_balances(events)
    status, divergences, _ = audit(stored, computed)
    assert status == "PASS"
    assert divergences == []


# ---------------------------------------------------------------------------
# Test 2: stored > history — one agent's stored balance exceeds computed
# ---------------------------------------------------------------------------

def test_stored_greater_than_history_fail() -> None:
    events = [{"type": "payment", "agent": "Bob@codex", "amount": 10}]
    stored = {"Bob@codex": {"balance": 999}}
    computed = compute_balances(events)
    status, divergences, _ = audit(stored, computed)
    assert status == "FAIL"
    assert len(divergences) == 1
    d = divergences[0]
    assert d["agent"] == "Bob@codex"
    assert d["history_balance"] == 10
    assert d["stored_balance"] == 999
    assert d["delta"] == -989


# ---------------------------------------------------------------------------
# Test 3: stored < history — history sum exceeds stored balance
# ---------------------------------------------------------------------------

def test_stored_less_than_history_fail() -> None:
    events = [{"type": "payment", "agent": "Carol@claude", "amount": 200}]
    stored = {"Carol@claude": {"balance": 100}}
    computed = compute_balances(events)
    status, divergences, _ = audit(stored, computed)
    assert status == "FAIL"
    assert len(divergences) == 1
    d = divergences[0]
    assert d["agent"] == "Carol@claude"
    assert d["history_balance"] == 200
    assert d["stored_balance"] == 100
    assert d["delta"] == 100


# ---------------------------------------------------------------------------
# Test 4: trajectory_mint credits correctly — both list and single-agent format
# ---------------------------------------------------------------------------

def test_trajectory_mint_credit() -> None:
    events = [
        # List format
        {
            "type": "trajectory_mint",
            "agents": ["Dave@claude", "Eve@codex"],
            "per_agent": [25, 30],
        },
        # Single-agent format
        {
            "type": "trajectory_mint",
            "agent": "Dave@claude",
            "amount": 5,
        },
    ]
    computed = compute_balances(events)
    assert computed["Dave@claude"] == 30   # 25 + 5
    assert computed["Eve@codex"] == 30


# ---------------------------------------------------------------------------
# Test 5: escrow_create debits the author field
# ---------------------------------------------------------------------------

def test_escrow_create_debit() -> None:
    events = [
        {"type": "payment", "agent": "Frank@claude", "amount": 100},
        {"type": "escrow_create", "author": "Frank@claude", "amount": 40},
    ]
    computed = compute_balances(events)
    assert computed["Frank@claude"] == 60  # 100 - 40


# ---------------------------------------------------------------------------
# Test 6: escrow_return credits the recipient field (and falls back to agent)
# ---------------------------------------------------------------------------

def test_escrow_return_credit() -> None:
    events = [
        # New format: recipient field
        {"type": "escrow_return", "recipient": "Grace@claude", "amount": 75},
        # Legacy format: agent field
        {"type": "escrow_return", "agent": "Grace@claude", "amount": 25},
    ]
    computed = compute_balances(events)
    assert computed["Grace@claude"] == 100


# ---------------------------------------------------------------------------
# Test 7: payment credits the agent field (positive amounts only)
# ---------------------------------------------------------------------------

def test_payment_credit() -> None:
    events = [
        {"type": "payment", "agent": "Heidi@codex", "amount": 42},
        # Negative amount should be ignored (not a debit via payment)
        {"type": "payment", "agent": "Heidi@codex", "amount": -10},
    ]
    computed = compute_balances(events)
    assert computed["Heidi@codex"] == 42


# ---------------------------------------------------------------------------
# Test 8: empty history PASS — all stored balances are zero
# ---------------------------------------------------------------------------

def test_empty_history_all_zero_balances_pass() -> None:
    events: list[dict] = []
    stored = {
        "Ivan@claude": {"balance": 0},
        "Judy@claude": {"balance": 0},
    }
    computed = compute_balances(events)
    status, divergences, _ = audit(stored, computed)
    assert status == "PASS"
    assert divergences == []


# ---------------------------------------------------------------------------
# Test 9: agent in history but not in balances — FAIL
# ---------------------------------------------------------------------------

def test_agent_in_history_not_in_balances_fail() -> None:
    events = [
        {
            "type": "trajectory_mint",
            "agents": ["Ghost@claude"],
            "per_agent": [50],
        }
    ]
    stored: dict = {}  # Ghost@claude not in balances.json
    computed = compute_balances(events)
    status, divergences, _ = audit(stored, computed)
    assert status == "FAIL"
    assert len(divergences) == 1
    d = divergences[0]
    assert d["agent"] == "Ghost@claude"
    assert d["history_balance"] == 50
    assert d["stored_balance"] == 0
    assert d["delta"] == 50


# ---------------------------------------------------------------------------
# Test 10: multi-agent, only one diverges — FAIL with exactly one entry
# ---------------------------------------------------------------------------

def test_multi_agent_only_one_diverges_fail() -> None:
    events = [
        {"type": "payment", "agent": "Karl@claude", "amount": 100},
        {"type": "payment", "agent": "Lara@claude", "amount": 200},
    ]
    stored = {
        "Karl@claude": {"balance": 100},  # correct
        "Lara@claude": {"balance": 300},  # wrong: stored > history
    }
    computed = compute_balances(events)
    status, divergences, _ = audit(stored, computed)
    assert status == "FAIL"
    assert len(divergences) == 1
    assert divergences[0]["agent"] == "Lara@claude"
    assert divergences[0]["history_balance"] == 200
    assert divergences[0]["stored_balance"] == 300
    assert divergences[0]["delta"] == -100


# ---------------------------------------------------------------------------
# Test 11: agent0 excluded from divergence reporting
# ---------------------------------------------------------------------------

def test_agent0_excluded_from_divergences() -> None:
    events = [
        {"type": "escrow_create", "author": "agent0@system", "amount": 500},
    ]
    stored = {"agent0@system": {"balance": 8000}}
    computed = compute_balances(events)
    # agent0 computed = -500, stored = 8000; divergence would be huge
    # but agent0 is excluded → PASS with no divergences
    status, divergences, _ = audit(stored, computed)
    assert status == "PASS"
    assert divergences == []


# ---------------------------------------------------------------------------
# Test 12: zero-balance history-only agent does NOT trigger FAIL
# ---------------------------------------------------------------------------

def test_zero_balance_history_only_agent_no_fail() -> None:
    events = [
        {"type": "payment", "agent": "Zeroed@claude", "amount": 50},
        # Reversal zeroes the agent back to 0
        {"type": "reversal", "agent": "Zeroed@claude", "amount": -50},
    ]
    stored = {"Marc@claude": {"balance": 0}}
    computed = compute_balances(events)
    assert computed.get("Zeroed@claude", 0) == 0
    status, divergences, _ = audit(stored, computed)
    assert status == "PASS"
    assert divergences == []


# ---------------------------------------------------------------------------
# Test 13: trajectory_mint with mismatched agents/per_agent lengths
# ---------------------------------------------------------------------------

def test_trajectory_mint_truncated_per_agent() -> None:
    events = [
        {
            "type": "trajectory_mint",
            "agents": ["Nina@claude", "Otto@claude"],
            "per_agent": [10],  # shorter than agents — Otto gets nothing
        }
    ]
    computed = compute_balances(events)
    assert computed.get("Nina@claude") == 10
    assert computed.get("Otto@claude", 0) == 0
