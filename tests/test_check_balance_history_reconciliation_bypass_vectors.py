"""Bypass-vector tests for scripts/check_balance_history_reconciliation.py."""

import pytest
from scripts.check_balance_history_reconciliation import compute_balances_from_history, reconcile

def get_status(checks, agent):
    for c in checks:
        if c["agent"] == agent:
            return c["status"]
    return None

def test_escrow_credit_via_author_bypass():
    """
    Bypass Vector 1: Escrow Credit via Author
    The `escrow` event only debits the `agent` field, ignoring `author`. 
    However, `escrow_return` credits `agent or author`. An attacker can 
    create an escrow with `author="attacker"` and `agent=""` to avoid the debit, 
    then get an `escrow_return` with the same fields to gain free WEA.
    """
    entries = [
        ("1.jsonl", {"type": "escrow", "author": "attacker", "agent": "", "amount": 100}),
        ("2.jsonl", {"type": "escrow_return", "author": "attacker", "agent": "", "amount": 100, "issue": "1"}),
    ]
    computed = compute_balances_from_history(entries)
    balances = {"agents": {"attacker": {"balance": 100}}}
    
    checks = reconcile(balances, computed)
    assert get_status(checks, "attacker") == "PASS"

def test_negative_escrow_bypass():
    """
    Bypass Vector 2: Negative Escrow
    The `escrow` and `escrow_create` events subtract the `amount` blindly.
    If an attacker submits a negative amount in an escrow event, it results 
    in a subtraction of a negative number, effectively acting as a credit
    and minting WEA out of thin air.
    """
    entries = [
        ("1.jsonl", {"type": "escrow", "agent": "attacker", "amount": -1000}),
    ]
    computed = compute_balances_from_history(entries)
    balances = {"agents": {"attacker": {"balance": 1000}}}
    
    checks = reconcile(balances, computed)
    assert get_status(checks, "attacker") == "PASS"

def test_escrow_return_deduplication_bypass():
    """
    Bypass Vector 3: Escrow Return Deduplication Bypass
    The deduplication for `escrow_return` relies on the uniqueness of the `(str(issue), agent)` tuple.
    An attacker can provide multiple `escrow_return` events for the same issue by altering 
    the type or appending whitespace to the issue ID (e.g., `123` vs `"123"` vs `"123 "`),
    resulting in multiple credits.
    """
    entries = [
        ("1.jsonl", {"type": "escrow_return", "agent": "attacker", "amount": 100, "issue": 123}),
        ("2.jsonl", {"type": "escrow_return", "agent": "attacker", "amount": 100, "issue": ["123"]}),
        ("3.jsonl", {"type": "escrow_return", "agent": "attacker", "amount": 100, "issue": "123 "}),
    ]
    computed = compute_balances_from_history(entries)
    balances = {"agents": {"attacker": {"balance": 300}}}
    
    checks = reconcile(balances, computed)
    assert get_status(checks, "attacker") == "PASS"

def test_trajectory_mint_duplicate_agents_bypass():
    """
    Bypass Vector 4: Trajectory Mint Duplicate Agents
    In the legacy format of `trajectory_mint` where `agent` is omitted, the script 
    iterates over the `agents` list and adds the corresponding `per_agent` amount. 
    If an attacker repeats their name in the `agents` list, they receive the mint amount multiple times.
    """
    entries = [
        ("1.jsonl", {"type": "trajectory_mint", "agents": ["attacker", "attacker"], "per_agent": [100, 100]}),
    ]
    computed = compute_balances_from_history(entries)
    balances = {"agents": {"attacker": {"balance": 200}}}
    
    checks = reconcile(balances, computed)
    assert get_status(checks, "attacker") == "PASS"

def test_type_confusion_integer_agent_id_bypass():
    """
    Bypass Vector 5: Type Confusion (Integer Agent ID)
    The reconciler should normalize non-string agent IDs to strings instead of
    letting type mismatches hide unauthorized debits/credits.
    """
    entries = [
        ("1.jsonl", {"type": "escrow", "agent": 123, "amount": 500}), # Unauthorized debt of 500
    ]
    computed = compute_balances_from_history(entries)
    # The attacker sets their balance to 0, attempting to hide the 500 debt.
    balances = {"agents": {"123": {"balance": 0}}}
    
    checks = reconcile(balances, computed)
    assert get_status(checks, "123") == "FAIL"

def test_economy_reset_string_iteration_bypass():
    """
    Bypass Vector 6: Economy Reset String Iteration
    The `economy_reset` event iterates over `agents_zeroed` to reset balances.
    If an attacker provides a string (e.g., `"attacker"`) instead of a list, 
    Python iterates over its characters (`"a"`, `"t"`, ...), leaving the actual 
    `"attacker"` balance completely untouched during the reset.
    """
    entries = [
        ("1.jsonl", {"type": "payment", "agent": "attacker", "amount": 500}),
        ("2.jsonl", {"type": "economy_reset", "agents_zeroed": "attacker"}), # Should reset but fails
    ]
    computed = compute_balances_from_history(entries)
    balances = {"agents": {"attacker": {"balance": 500}}}
    
    checks = reconcile(balances, computed)
    assert get_status(checks, "attacker") == "PASS"
