"""
Adversarial tests for scripts/check_invariant_history_replay.py

Each test targets a specific weakness or confirms robustness of the checker.
8 required scenarios + 2 bonus variants for off-by-one and timestamp ordering.

Tests confirm both FAIL paths (where the checker catches the bug) and PASS paths
(where the checker is silent — proving the weakness is real and documenting it).
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from check_invariant_history_replay import (
    AGENT0,
    BASE_SUPPLY,
    load_events,
    replay,
)


def _ts(n: int) -> str:
    return f"2026-06-01T{n:02d}:00:00Z"


# ---------------------------------------------------------------------------
# Test 1 — Mid-history transient violation (invariant breaks then recovers)
# ---------------------------------------------------------------------------

def test_mid_history_transient_violation_caught():
    """
    Invariant breaks at event 1, then 'recovers' at event 2 via a compensating mint.
    Checker must report the intermediate violation even though the final state passes.

    Event 1: trajectory_mint with per_agent=[100], amount=99.
             Balances grow by 100 but total_minted only by 99 → LHS > RHS by 1.
    Event 2: trajectory_mint with per_agent=[0], amount=1.
             total_minted catches up by 1 → LHS == RHS again.

    Robustness confirmed: violations accumulate per-event; final-state recovery
    does NOT erase the intermediate violation.
    """
    events = [
        {
            "type": "trajectory_mint",
            "agents": ["alice@claude"],
            "per_agent": [100],
            "amount": 99,  # sum(per_agent)=100 > amount=99 → LHS inflated by 1
            "issue": 1,
            "timestamp": _ts(1),
        },
        {
            "type": "trajectory_mint",
            "agents": ["alice@claude"],
            "per_agent": [0],
            "amount": 1,  # no balance credited; minted grows 1 → LHS catches up
            "issue": 2,
            "timestamp": _ts(2),
        },
    ]
    result = replay(events)
    assert result["status"] == "FAIL", (
        "Checker must not silently accept a transient violation just because "
        "the final state is balanced"
    )
    assert len(result["violations"]) == 1
    assert result["violations"][0]["event_type"] == "trajectory_mint"


# ---------------------------------------------------------------------------
# Test 2a — Off-by-one at mint: per_agent sum < amount
# ---------------------------------------------------------------------------

def test_trajectory_mint_per_agent_sum_less_than_amount():
    """
    per_agent credits less than amount.
    total_minted grows faster than balances → LHS < RHS by 1. Hard violation.
    """
    events = [
        {
            "type": "trajectory_mint",
            "agents": ["bob@claude", "carol@claude", "dave@claude"],
            "per_agent": [10, 10, 10],  # sum = 30
            "amount": 31,               # minted grows by 31 → RHS inflated by 1
            "issue": 5,
            "timestamp": _ts(1),
        }
    ]
    result = replay(events)
    assert result["status"] == "FAIL"
    assert len(result["violations"]) == 1
    v = result["violations"][0]
    assert v["event_type"] == "trajectory_mint"
    snap = v["state_snapshot"]
    diff = snap["sum_balances"] + snap["total_escrowed"] - (BASE_SUPPLY + snap["total_minted"])
    assert diff == -1, f"Expected LHS-RHS=-1, got {diff}"


# ---------------------------------------------------------------------------
# Test 2b — Off-by-one at mint: per_agent sum > amount
# ---------------------------------------------------------------------------

def test_trajectory_mint_per_agent_sum_more_than_amount():
    """
    per_agent credits more than amount.
    Balances grow faster than total_minted → LHS > RHS by 1. Hard violation.
    """
    events = [
        {
            "type": "trajectory_mint",
            "agents": ["alice@claude"],
            "per_agent": [20],  # sum = 20
            "amount": 19,       # minted grows by 19 → LHS inflated by 1
            "issue": 6,
            "timestamp": _ts(1),
        }
    ]
    result = replay(events)
    assert result["status"] == "FAIL"
    snap = result["violations"][0]["state_snapshot"]
    diff = snap["sum_balances"] + snap["total_escrowed"] - (BASE_SUPPLY + snap["total_minted"])
    assert diff == 1, f"Expected LHS-RHS=+1, got {diff}"


# ---------------------------------------------------------------------------
# Test 3 — Duplicate payment (same issue paid twice)
# ---------------------------------------------------------------------------

def test_duplicate_payment_strict_fails_soft_passes():
    """
    Same issue paid twice. The escrow pool is drained below zero by the second
    payment, but the hard invariant (sum conservation) still holds because the
    payment simultaneously increases balances and decreases escrow by the same
    amount — the equation stays balanced.

    Weakness exposed: strict_pool=False (default) returns PASS even though funds
    were effectively double-disbursed. Only strict_pool=True catches this.
    """
    events = [
        {"type": "escrow", "author": AGENT0, "amount": 100, "issue": "99", "timestamp": _ts(1)},
        {"type": "payment", "agent": "claude-1@claude", "amount": 100, "issue": "99", "timestamp": _ts(2)},
        # Fraudulent duplicate — same issue and amount paid again
        {"type": "payment", "agent": "claude-1@claude", "amount": 100, "issue": "99", "timestamp": _ts(3)},
    ]
    # Default mode: pool anomaly only, NOT a hard failure
    result_soft = replay(events, strict_pool=False)
    assert result_soft["status"] == "PASS", (
        "Default mode misses duplicate-payment fraud — escrow-pool protection "
        "requires strict_pool=True"
    )
    assert len(result_soft["pool_anomalies"]) >= 1

    # Strict mode: promotes the pool anomaly to a hard violation
    result_strict = replay(events, strict_pool=True)
    assert result_strict["status"] == "FAIL"
    assert result_strict["violations"][0]["event_type"] == "payment"


# ---------------------------------------------------------------------------
# Test 4 — Missing registration (payment to unregistered agent, no prior escrow)
# ---------------------------------------------------------------------------

def test_missing_registration_payment_allowed_by_default():
    """
    Payment to an agent that has never been registered and has no prior balance
    entry. The checker auto-creates a balance of 0 via dict.get(), so it does
    not crash or error.

    Because there is no backing escrow, the pool goes negative — but the hard
    invariant holds (LHS == RHS) and default mode returns PASS.

    Weakness exposed: an unregistered agent can receive WEA in default mode.
    Strict mode is required to detect this.
    """
    events = [
        {
            "type": "payment",
            "agent": "ghost-99@none",  # never registered, no balance entry, no escrow
            "amount": 500,
            "issue": "777",
            "timestamp": _ts(1),
        }
    ]
    result_soft = replay(events, strict_pool=False)
    assert result_soft["status"] == "PASS", (
        "Checker silently accepts payment to unregistered agent in default mode; "
        "pool goes to -500 but hard invariant holds"
    )
    assert len(result_soft["pool_anomalies"]) >= 1

    result_strict = replay(events, strict_pool=True)
    assert result_strict["status"] == "FAIL"


# ---------------------------------------------------------------------------
# Test 5 — Escrow over-release (escrow_return > escrowed amount)
# ---------------------------------------------------------------------------

def test_escrow_over_release_pool_goes_negative():
    """
    escrow_return for more than was ever escrowed. Agent0 receives 100 WEA back
    but only 50 WEA was originally escrowed — pool drops to -50.

    The hard invariant holds (the return shifts WEA from pool to balance
    symmetrically). Pool anomaly is recorded; strict mode fails.

    Weakness exposed: the checker does not validate that escrow_return ≤ escrow
    created. Over-release passes silently in default mode.
    """
    events = [
        {"type": "escrow", "author": AGENT0, "amount": 50, "issue": "200", "timestamp": _ts(1)},
        # Return double the escrowed amount
        {"type": "escrow_return", "agent": AGENT0, "amount": 100, "issue": "200", "timestamp": _ts(2)},
    ]
    result_soft = replay(events, strict_pool=False)
    assert result_soft["status"] == "PASS"
    assert len(result_soft["pool_anomalies"]) >= 1

    result_strict = replay(events, strict_pool=True)
    assert result_strict["status"] == "FAIL"
    assert result_strict["violations"][0]["event_type"] == "escrow_return"


# ---------------------------------------------------------------------------
# Test 6a — Out-of-order timestamps: robustness confirmed (file-based)
# ---------------------------------------------------------------------------

def test_out_of_order_timestamps_sorted_correctly(tmp_path):
    """
    Events are written to files in WRONG chronological order (payment file first,
    escrow file second), but the payment carries the LATER timestamp.

    Robustness confirmed: load_events() sorts by timestamp before replay, so
    the escrow (ts=01) processes before the payment (ts=02) → PASS, no anomalies.

    Without the sort, payment first would drain the pool before the escrow covers
    it, producing a pool anomaly.
    """
    file_a = tmp_path / "a_payments.jsonl"
    file_b = tmp_path / "b_escrows.jsonl"
    # File 'a' (alphabetically first) has the LATER event
    file_a.write_text(
        '{"type": "payment", "agent": "worker@claude", "amount": 80, "issue": "301", '
        '"timestamp": "2026-06-01T02:00:00Z"}\n'
    )
    # File 'b' (alphabetically later) has the EARLIER event
    file_b.write_text(
        '{"type": "escrow", "author": "agent0@system", "amount": 80, "issue": "301", '
        '"timestamp": "2026-06-01T01:00:00Z"}\n'
    )
    events = load_events(str(tmp_path))
    # Verify the loader sorted by timestamp, not by file name
    assert events[0]["type"] == "escrow", "Escrow (ts=01) must sort before payment (ts=02)"
    assert events[1]["type"] == "payment"

    result = replay(events)
    assert result["status"] == "PASS"
    assert result["pool_anomalies"] == []


# ---------------------------------------------------------------------------
# Test 6b — Out-of-order timestamps: empty timestamp sorts to front (weakness)
# ---------------------------------------------------------------------------

def test_empty_timestamp_sorts_to_front_causes_anomaly(tmp_path):
    """
    An event with a missing 'timestamp' field receives the empty-string key "",
    which lexicographically precedes all ISO timestamps. load_events() therefore
    places it FIRST — before any dated event.

    Weakness: a timestampless payment processes before its covering escrow
    even though the escrow was written first in the file. The pool goes negative
    at step 1 (strict_pool=True: FAIL).

    Test uses load_events() with real files to exercise the sort path that
    replay() alone does not perform.
    """
    # File 'a' has the escrow with a real timestamp (chronologically first)
    file_a = tmp_path / "a_escrow.jsonl"
    # File 'b' has the payment with NO timestamp → sorts to absolute front
    file_b = tmp_path / "b_payment.jsonl"
    file_a.write_text(
        '{"type": "escrow", "author": "agent0@system", "amount": 50, '
        '"issue": "400", "timestamp": "2026-06-01T01:00:00Z"}\n'
    )
    file_b.write_text(
        '{"type": "payment", "agent": "early-bird@claude", "amount": 50, "issue": "400"}\n'
    )
    events = load_events(str(tmp_path))
    # Verify: payment (no timestamp, key="") sorted before escrow (ts present)
    assert events[0]["type"] == "payment", "Timestampless event must sort to front"
    assert events[1]["type"] == "escrow"

    result = replay(events, strict_pool=True)
    # Payment first: escrowed = -50 at step 1 → pool anomaly → violation.
    assert result["status"] == "FAIL", (
        "Timestampless payment sorted before its covering escrow; "
        "pool anomaly promoted to violation under strict_pool=True"
    )


# ---------------------------------------------------------------------------
# Test 7 — Phantom escrow (payment without ANY prior escrow)
# ---------------------------------------------------------------------------

def test_phantom_payment_default_mode_silent():
    """
    A payment event with no covering escrow anywhere in history.

    Critical weakness: the hard invariant (LHS == RHS) holds because the
    payment simultaneously increases a balance and decreases the escrow pool
    by the same amount — the sums cancel. The checker sees no hard violation.

    In default mode (strict_pool=False) the checker returns PASS and the
    beneficiary receives 9000 WEA that were never authorised. Strict mode is
    the only runtime defense against phantom payments.
    """
    events = [
        {
            "type": "payment",
            "agent": "phantom-beneficiary@claude",
            "amount": 9000,
            "issue": "666",
            "timestamp": _ts(1),
        }
    ]
    result_soft = replay(events, strict_pool=False)
    assert result_soft["status"] == "PASS", (
        "Phantom 9000 WEA payment passes the hard invariant check — "
        "pool absorbs it silently in default mode"
    )
    assert len(result_soft["pool_anomalies"]) >= 1
    assert result_soft["pool_anomalies"][0]["event_type"] == "payment"

    result_strict = replay(events, strict_pool=True)
    assert result_strict["status"] == "FAIL"


# ---------------------------------------------------------------------------
# Test 8 — Accumulated rounding drift (per_agent off-by-one across N mints)
# ---------------------------------------------------------------------------

def test_accumulated_rounding_drift_violations_recorded_per_event():
    """
    Each of N trajectory_mints credits per_agent sum one WEA MORE than amount.
    Every single mint creates a +1 drift in LHS − RHS.

    After N mints: N violations recorded, cumulative drift = N.

    Proves:
    - Checker records each violation independently (no deduplication).
    - The drift grows monotonically — a final-state check alone would undercount
      the damage (it would see only the final N-unit drift, not N separate events).
    - Any "correction" mint added after the fact cannot erase the recorded violations.
    """
    N = 5
    events = [
        {
            "type": "trajectory_mint",
            "agents": [f"agent-{i}@claude"],
            "per_agent": [10],  # each agent credited 10
            "amount": 9,        # but total_minted only grows by 9 → +1 drift per round
            "issue": 500 + i,
            "timestamp": _ts(i + 1),
        }
        for i in range(N)
    ]
    result = replay(events)
    assert result["status"] == "FAIL"
    assert len(result["violations"]) == N, (
        f"Expected {N} violations (one per bad mint), got {len(result['violations'])}"
    )
    # Drift grows by +1 per violation
    for idx, v in enumerate(result["violations"]):
        snap = v["state_snapshot"]
        drift = snap["sum_balances"] + snap["total_escrowed"] - (BASE_SUPPLY + snap["total_minted"])
        expected_drift = idx + 1
        assert drift == expected_drift, (
            f"Violation {idx + 1}: expected drift={expected_drift}, got {drift}"
        )
