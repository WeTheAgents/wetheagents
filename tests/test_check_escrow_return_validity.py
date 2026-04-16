"""Tests for scripts/check_escrow_return_validity.py.

Covers the 12+ required scenarios using in-memory event fixtures only.
"""

from __future__ import annotations

from pathlib import Path

from scripts import check_escrow_return_validity as checker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(events: list[dict]) -> dict:
    """Run the check with an in-memory event list."""
    return checker.run_check(Path("/fake/root"), events=events)


def _create(issue: int, amount: int) -> dict:
    return {"type": "escrow_create", "issue": issue, "amount": amount}


def _escrow(issue: int, amount: int) -> dict:
    """Old-style escrow event (pre-2026-03-19 format)."""
    return {"type": "escrow", "issue": issue, "amount": amount}


def _return(issue: int, amount: int) -> dict:
    return {"type": "escrow_return", "issue": issue, "amount": amount}


def _payment(issue: int, amount: int) -> dict:
    return {"type": "payment", "issue": issue, "amount": amount}


def _bulk_return(issues: list[int], amount: int) -> dict:
    return {"type": "escrow_return_bulk", "issues": issues, "amount": amount}


# ---------------------------------------------------------------------------
# PASS cases
# ---------------------------------------------------------------------------

def test_empty_history_pass() -> None:
    """No events at all — nothing to violate."""
    result = _run([])
    assert result["status"] == "PASS"
    assert result["violations"] == []


def test_valid_return_with_prior_create_pass() -> None:
    """escrow_create precedes escrow_return for same issue → PASS, no warnings."""
    result = _run([_create(100, 30), _return(100, 30)])
    assert result["status"] == "PASS"
    assert result["violations"] == []
    assert result["warnings"] == []


def test_old_escrow_type_counts_as_prior_create_pass() -> None:
    """Old-style 'escrow' event (pre-escrow_create era) counts as a prior create."""
    result = _run([_escrow(200, 15), _return(200, 15)])
    assert result["status"] == "PASS"
    assert result["violations"] == []
    assert result["warnings"] == []


def test_double_return_partial_within_total_pass() -> None:
    """Two partial returns that together do not exceed the total escrow → PASS."""
    result = _run([_create(300, 100), _return(300, 40), _return(300, 50)])
    assert result["status"] == "PASS"
    assert result["violations"] == []
    assert result["warnings"] == []


def test_multiple_create_return_cycles_pass() -> None:
    """An issue can be escrowed, returned, re-escrowed, and returned again."""
    result = _run([
        _create(400, 20),
        _return(400, 20),
        _create(400, 25),   # second cycle
        _return(400, 25),
    ])
    assert result["status"] == "PASS"
    assert result["violations"] == []
    assert result["warnings"] == []


def test_multiple_issues_all_valid_pass() -> None:
    """Multiple independent issues each with valid create → return pairs → PASS."""
    result = _run([
        _create(10, 5), _return(10, 5),
        _create(20, 10), _return(20, 10),
        _create(30, 15), _return(30, 15),
    ])
    assert result["status"] == "PASS"
    assert result["violations"] == []


def test_escrow_return_bulk_not_individually_checked_pass() -> None:
    """escrow_return_bulk events are a different type and are not per-issue checked."""
    # Issue 999 appears only in a bulk return — no prior create for issue 999.
    # Since it is a bulk event (not escrow_return), it must NOT trigger a violation.
    result = _run([_bulk_return([999], 50)])
    assert result["status"] == "PASS"
    assert result["violations"] == []


# ---------------------------------------------------------------------------
# FAIL cases
# ---------------------------------------------------------------------------

def test_return_no_prior_create_no_prior_payment_fail() -> None:
    """escrow_return for an issue with no prior escrow or payment → FAIL."""
    result = _run([_return(500, 20)])
    assert result["status"] == "FAIL"
    assert len(result["violations"]) == 1
    v = result["violations"][0]
    assert v["issue"] == 500
    assert v["return_amount"] == 20
    assert "no prior escrow_create" in v["reason"]


def test_return_for_different_issue_no_create_fail() -> None:
    """escrow_create for issue A, escrow_return for issue B → FAIL for issue B."""
    result = _run([_create(100, 30), _return(999, 30)])
    assert result["status"] == "FAIL"
    assert len(result["violations"]) == 1
    assert result["violations"][0]["issue"] == 999


def test_multiple_violations_fail() -> None:
    """Two fraudulent returns → FAIL with two violations."""
    result = _run([_return(600, 10), _return(700, 20)])
    assert result["status"] == "FAIL"
    assert len(result["violations"]) == 2
    violated_issues = {v["issue"] for v in result["violations"]}
    assert violated_issues == {600, 700}


# ---------------------------------------------------------------------------
# WARNING cases (status still PASS)
# ---------------------------------------------------------------------------

def test_return_no_create_but_prior_payment_warns_not_fails() -> None:
    """Payment evidence that escrow existed (pre-history gap) → WARN, not FAIL."""
    result = _run([_payment(800, 15), _return(800, 5)])
    assert result["status"] == "PASS"
    assert result["violations"] == []
    assert len(result["warnings"]) == 1
    w = result["warnings"][0]
    assert w["issue"] == 800
    assert "pre-history" in w["detail"]


def test_over_return_warns_not_fails() -> None:
    """Return amount exceeds total created for an issue → WARN, status still PASS."""
    result = _run([_create(900, 10), _return(900, 15)])
    assert result["status"] == "PASS"
    assert result["violations"] == []
    assert len(result["warnings"]) == 1
    w = result["warnings"][0]
    assert w["issue"] == 900
    assert "return exceeds" in w["detail"]


def test_double_return_exceeds_creates_warns() -> None:
    """Two returns on same issue that together exceed the total created → WARN."""
    # create=20, return=15 (ok), return=10 (total=25 > 20) → WARN on second return
    result = _run([_create(950, 20), _return(950, 15), _return(950, 10)])
    assert result["status"] == "PASS"
    assert result["violations"] == []
    assert len(result["warnings"]) == 1
    assert result["warnings"][0]["issue"] == 950


# ---------------------------------------------------------------------------
# Output contract
# ---------------------------------------------------------------------------

def test_output_has_required_fields() -> None:
    """Result dict always contains status, violations, warnings, summary."""
    result = _run([])
    for key in ("status", "violations", "warnings", "summary"):
        assert key in result, f"missing key: {key}"


def test_summary_reflects_counts() -> None:
    """summary string reports the correct violation and warning counts."""
    result = _run([_return(1, 5), _create(2, 10), _return(2, 20)])
    # 1 violation (issue 1), 1 warning (issue 2 over-return)
    assert result["status"] == "FAIL"
    assert "1 violation" in result["summary"]
    assert "1 warning" in result["summary"]
