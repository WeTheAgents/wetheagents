"""
Red-team tests for check_escrow_schema.py

Adversarial test cases exploring bypass vectors, edge cases, and logic gaps.
"""

import pytest
from scripts.check_escrow_schema import run

KNOWN_AGENTS = {"agent0@system", "alice@test", "bob@test"}
BALANCES = {"agents": {a: {} for a in KNOWN_AGENTS}}

def _active(entry: dict, issue: str = "42", version: int = 1) -> dict:
    """Helper to wrap entry in top-level escrow JSON structure."""
    data = {"active": {issue: entry}}
    if version is not None:
        data["version"] = version
    return data

def test_amount_as_float():
    """
    Target: amount as float instead of int (1.5 instead of 1)
    Result: GAP
    The checker allows floats explicitly via isinstance(amt, (int, float)), 
    but WEA ledger amounts should probably be strictly integers.
    """
    data = _active({
        "author": "alice@test",
        "amount": 1.5,
        "type": "pod",
        "created_at": "2026-04-13T03:49:25Z",
    })
    result = run(data, BALANCES)
    assert result["status"] == "PASS"

def test_type_mixed_case():
    """
    Target: type field with mixed case ('Pod' vs 'pod')
    Result: FOUND
    The checker correctly rejects 'Pod' because it strictly checks against lowercased VALID_TYPES.
    """
    data = _active({
        "author": "alice@test",
        "amount": 10,
        "type": "Pod",
        "created_at": "2026-04-13T03:49:25Z",
    })
    result = run(data, BALANCES)
    assert result["status"] == "FAIL"
    assert any(v["field"] == "type" for v in result["violations"])

def test_slots_zero_progressive():
    """
    Target: slots=0 on progressive type
    Result: FOUND
    The checker strictly verifies slots > 0 and correctly flags slots=0 as a violation.
    """
    data = _active({
        "author": "alice@test",
        "amount": 10,
        "type": "progressive",
        "created_at": "2026-04-13T03:49:25Z",
        "slots": 0
    })
    result = run(data, BALANCES)
    assert result["status"] == "FAIL"
    assert any(v["field"] == "slots" for v in result["violations"])

def test_paid_count_zero():
    """
    Target: paid_count=0 on progressive (valid boundary)
    Result: FOUND (Working as intended)
    The checker accepts paid_count=0 correctly (must be >= 0).
    """
    data = _active({
        "author": "alice@test",
        "amount": 10,
        "type": "progressive",
        "created_at": "2026-04-13T03:49:25Z",
        "slots": 3,
        "paid_count": 0
    })
    result = run(data, BALANCES)
    assert result["status"] == "PASS"

def test_extra_unexpected_fields():
    """
    Target: extra unexpected fields in escrow entry (strict vs permissive schema)
    Result: GAP
    The checker ignores extra fields like 'malicious_field' without failing, meaning the schema is permissive.
    """
    data = _active({
        "author": "alice@test",
        "amount": 10,
        "type": "pod",
        "created_at": "2026-04-13T03:49:25Z",
        "malicious_field": "exploit"
    })
    result = run(data, BALANCES)
    assert result["status"] == "PASS"

def test_paid_count_on_non_progressive():
    """
    Target: paid_count field on a non-progressive type (unexpected field)
    Result: GAP
    The checker verifies the paid_count type if present, but doesn't restrict it to progressive types only.
    """
    data = _active({
        "author": "alice@test",
        "amount": 10,
        "type": "pod",
        "created_at": "2026-04-13T03:49:25Z",
        "paid_count": 1
    })
    result = run(data, BALANCES)
    assert result["status"] == "PASS"
