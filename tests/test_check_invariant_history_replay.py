"""
Tests for scripts/check_invariant_history_replay.py

Covers the 8 scenarios required by the task spec plus edge cases.
Uses only pytest-native fixtures; no unittest.mock.
"""

import json
import os
import subprocess
import sys

import pytest

# Allow importing the script directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from check_invariant_history_replay import (
    AGENT0,
    BASE_SUPPLY,
    apply_event,
    check_step,
    load_events,
    replay,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts(n: int) -> str:
    """Generate deterministic ISO timestamps for test fixtures."""
    return f"2026-01-01T{n:02d}:00:00Z"


def _run_replay(events: list[dict], initial_balances=None):
    """Thin wrapper for replay() with default initial state."""
    return replay(events, initial_balances=initial_balances)


# ---------------------------------------------------------------------------
# Test 1 — Single payment funded by an escrow → PASS
# ---------------------------------------------------------------------------

def test_single_payment_pass():
    """Escrow created, then paid out once — invariant holds at every step."""
    events = [
        {"type": "escrow", "author": AGENT0, "amount": 20, "issue": "1", "timestamp": _ts(1)},
        {"type": "payment", "agent": "Claude-1@claude", "amount": 20, "issue": "1", "timestamp": _ts(2)},
    ]
    result = _run_replay(events)
    assert result["status"] == "PASS"
    assert result["events_replayed"] == 2
    assert result["violations"] == []


# ---------------------------------------------------------------------------
# Test 2 — Escrow then payment sequence → PASS
# ---------------------------------------------------------------------------

def test_escrow_then_payment_pass():
    """Explicit escrow-then-payment lifecycle including return of unused funds."""
    events = [
        {"type": "escrow", "author": AGENT0, "amount": 50, "issue": "2", "timestamp": _ts(1)},
        {"type": "payment", "agent": "Claude-5@claude", "amount": 45, "issue": "2", "timestamp": _ts(2)},
        {"type": "escrow_return", "agent": AGENT0, "amount": 5, "issue": "2", "timestamp": _ts(3)},
    ]
    result = _run_replay(events)
    assert result["status"] == "PASS"
    assert result["events_replayed"] == 3
    assert result["violations"] == []


# ---------------------------------------------------------------------------
# Test 3 — Escrow without resolution → PASS (valid intermediate state)
# ---------------------------------------------------------------------------

def test_escrow_without_resolution_pass():
    """An open escrow (not yet paid out) is a valid intermediate state."""
    events = [
        {"type": "escrow", "author": AGENT0, "amount": 30, "issue": "3", "timestamp": _ts(1)},
    ]
    result = _run_replay(events)
    assert result["status"] == "PASS"
    assert result["events_replayed"] == 1
    assert result["violations"] == []


# ---------------------------------------------------------------------------
# Test 4 — Double payment without sufficient escrow → FAIL
# ---------------------------------------------------------------------------

def test_double_payment_no_escrow_fail():
    """Two payments with only one escrow — second payment drains pool negative."""
    events = [
        {"type": "escrow", "author": AGENT0, "amount": 100, "issue": "4", "timestamp": _ts(1)},
        # First payment consumes the escrow fully
        {"type": "payment", "agent": "Claude-1@claude", "amount": 100, "issue": "4", "timestamp": _ts(2)},
        # Second payment: no funds left in escrow pool → violation
        {"type": "payment", "agent": "Claude-1@claude", "amount": 100, "issue": "4", "timestamp": _ts(3)},
    ]
    result = replay(events, strict_pool=True)
    assert result["status"] == "FAIL"
    assert len(result["violations"]) >= 1
    # Violation should be at the second payment
    assert result["violations"][0]["event_type"] == "payment"


# ---------------------------------------------------------------------------
# Test 5 — Trajectory mint → increases expected RHS → PASS
# ---------------------------------------------------------------------------

def test_trajectory_mint_pass():
    """Minting new WEA increases total_minted (RHS) and agent balance (LHS) equally."""
    events = [
        {
            "type": "trajectory_mint",
            "trajectory": "T1",
            "slot": 1,
            "amount": 25,
            "agents": ["Claude-1@claude"],
            "per_agent": [25],
            "issue": 100,
            "timestamp": _ts(1),
        }
    ]
    result = _run_replay(events)
    assert result["status"] == "PASS"
    assert result["events_replayed"] == 1
    assert result["violations"] == []


# ---------------------------------------------------------------------------
# Test 6 — Wrong payment amount (exceeds escrow) → FAIL
# ---------------------------------------------------------------------------

def test_payment_exceeds_escrow_fail():
    """Payment larger than escrowed amount drains the escrow pool below zero.

    With strict_pool=True the anomaly is promoted to a hard violation and
    status is FAIL.  Without strict_pool (default) the pool anomaly is
    recorded in pool_anomalies but does not change the status.
    """
    events = [
        {"type": "escrow", "author": AGENT0, "amount": 40, "issue": "5", "timestamp": _ts(1)},
        # Payment is 60 but only 40 was escrowed
        {"type": "payment", "agent": "Claude-2@codex", "amount": 60, "issue": "5", "timestamp": _ts(2)},
    ]
    # strict_pool=True: pool violation → FAIL
    result = replay(events, strict_pool=True)
    assert result["status"] == "FAIL"
    assert len(result["violations"]) >= 1
    assert result["violations"][0]["event_type"] == "payment"
    # strict_pool=False (default): pool anomaly recorded but status stays PASS
    result_soft = _run_replay(events)
    assert result_soft["status"] == "PASS"
    assert len(result_soft["pool_anomalies"]) >= 1


# ---------------------------------------------------------------------------
# Test 7 — Empty history → PASS (initial state seeded with agent0=10000)
# ---------------------------------------------------------------------------

def test_empty_history_pass():
    """No events — initial state (agent0=10000, escrows=0, minted=0) satisfies invariant."""
    result = _run_replay([])
    assert result["status"] == "PASS"
    assert result["events_replayed"] == 0
    assert result["violations"] == []


# ---------------------------------------------------------------------------
# Test 8 — Multi-agent interleaved events → PASS
# ---------------------------------------------------------------------------

def test_multi_agent_interleaved_pass():
    """Several agents create escrows, receive payments, and mint — all balanced."""
    events = [
        # Agent0 creates two task escrows
        {"type": "escrow", "author": AGENT0, "amount": 30, "issue": "10", "timestamp": _ts(1)},
        {"type": "escrow", "author": AGENT0, "amount": 50, "issue": "11", "timestamp": _ts(2)},
        # Payments to two different agents
        {"type": "payment", "agent": "Claude-1@claude", "amount": 30, "issue": "10", "timestamp": _ts(3)},
        {"type": "payment", "agent": "Claude-5@claude", "amount": 50, "issue": "11", "timestamp": _ts(4)},
        # Gauntlet mint creates fresh WEA
        {
            "type": "trajectory_mint",
            "trajectory": "T2",
            "slot": 1,
            "amount": 20,
            "agents": ["Claude-1@claude"],
            "per_agent": [20],
            "issue": 200,
            "timestamp": _ts(5),
        },
        # Claude-1 posts a task, Claude-5 solves it
        {"type": "escrow", "author": "Claude-1@claude", "amount": 10, "issue": "12", "timestamp": _ts(6)},
        {"type": "payment", "agent": "Claude-5@claude", "amount": 10, "issue": "12", "timestamp": _ts(7)},
    ]
    result = _run_replay(events)
    assert result["status"] == "PASS"
    assert result["events_replayed"] == 7
    assert result["violations"] == []


# ---------------------------------------------------------------------------
# Test 9 — Escrow return restores funds correctly → PASS
# ---------------------------------------------------------------------------

def test_escrow_return_pass():
    """Escrow return credits the agent without violating the invariant."""
    events = [
        {"type": "escrow", "author": AGENT0, "amount": 25, "issue": "20", "timestamp": _ts(1)},
        {"type": "escrow_return", "agent": AGENT0, "amount": 25, "issue": "20", "timestamp": _ts(2)},
    ]
    result = _run_replay(events)
    assert result["status"] == "PASS"
    assert result["events_replayed"] == 2
    assert result["violations"] == []


# ---------------------------------------------------------------------------
# Test 10 — Output JSON has required fields
# ---------------------------------------------------------------------------

def test_result_has_required_fields():
    """Result dict always contains status, events_replayed, violations, summary."""
    result = _run_replay([])
    assert "status" in result
    assert "events_replayed" in result
    assert "violations" in result
    assert "summary" in result
    assert result["status"] in ("PASS", "FAIL")
    assert isinstance(result["events_replayed"], int)
    assert isinstance(result["violations"], list)
    assert isinstance(result["summary"], str)


# ---------------------------------------------------------------------------
# Test 11 — apply_event skips no-op types
# ---------------------------------------------------------------------------

def test_skip_types_not_counted():
    """claim, verification, settle events are skipped — events_replayed unchanged."""
    skip_events = [
        {"type": "claim", "agent": "Claude-1@claude", "issue": "1", "timestamp": _ts(1)},
        {"type": "verification", "agent": "Claude-1@claude", "issue": "1", "timestamp": _ts(2)},
        {"type": "registration", "agent": "Claude-99@claude", "timestamp": _ts(3)},
        {"type": "settle", "issue": "99", "escrow_amount": 50, "distributed": 50, "timestamp": _ts(4)},
    ]
    result = _run_replay(skip_events)
    assert result["status"] == "PASS"
    assert result["events_replayed"] == 0  # none handled
    assert result["violations"] == []


# ---------------------------------------------------------------------------
# Test 12 — Economy reset zeros agents and burns minted → PASS
# ---------------------------------------------------------------------------

def test_economy_reset_pass():
    """economy_reset zeroes specified agents, returns WEA to agent0, burns minted."""
    events = [
        # Mint WEA for two agents
        {"type": "mint", "agent": "OldAgent-A@cursor", "amount": 100, "timestamp": _ts(1)},
        {"type": "mint", "agent": "OldAgent-B@cursor", "amount": 50, "timestamp": _ts(2)},
        # Economy reset: zero both agents, return their earned WEA to agent0, burn mints
        {
            "type": "economy_reset",
            "agents_zeroed": ["OldAgent-A@cursor", "OldAgent-B@cursor"],
            "wea_returned_to_agent0": 0,  # they earned 0 (mint is burned separately)
            "mint_burned": 150,           # burn the 150 minted WEA
            "new_supply": 10000,
            "timestamp": _ts(3),
        },
    ]
    result = _run_replay(events)
    assert result["status"] == "PASS"
    # economy_reset resets events_replayed counter to 0 (genesis wipe)
    assert result["events_replayed"] == 0
    assert result["violations"] == []


# ---------------------------------------------------------------------------
# Test 13 — load_events sorts by timestamp across multiple files
# ---------------------------------------------------------------------------

def test_load_events_sorted(tmp_path):
    """Events from multiple files are sorted chronologically by timestamp."""
    file_a = tmp_path / "2026-01-02.jsonl"
    file_b = tmp_path / "2026-01-01.jsonl"
    file_a.write_text(
        '{"type": "payment", "agent": "X", "amount": 10, "timestamp": "2026-01-02T00:00:00Z"}\n'
    )
    file_b.write_text(
        '{"type": "escrow", "author": "agent0@system", "amount": 10, "issue": "1", "timestamp": "2026-01-01T00:00:00Z"}\n'
    )
    events = load_events(str(tmp_path))
    assert len(events) == 2
    assert events[0]["timestamp"] < events[1]["timestamp"]
    assert events[0]["type"] == "escrow"
    assert events[1]["type"] == "payment"


# ---------------------------------------------------------------------------
# Test 14 — check_step returns violation when invariant broken
# ---------------------------------------------------------------------------

def test_check_step_detects_invariant_break():
    """check_step flags when LHS != RHS."""
    # Corrupt state: balances sum to 10100 but no minting → LHS=10100 ≠ RHS=10000
    balances = {AGENT0: 9000, "Rouge@rouge": 1100}
    ok, all_msgs, anomalies = check_step(balances, total_escrowed=0, total_minted=0)
    assert not ok
    assert any("invariant broken" in m for m in all_msgs)


def test_check_step_detects_negative_escrow():
    """check_step flags negative total_escrowed (payment without escrow)."""
    balances = {AGENT0: 10100, "Agent-X@x": 100}
    # total_escrowed = -100 (two payments of 100 with only 100 initial escrow)
    ok, all_msgs, anomalies = check_step(balances, total_escrowed=-100, total_minted=0)
    assert not ok
    assert any("negative escrow" in m for m in all_msgs)
    assert any("negative escrow" in m for m in anomalies)


# ---------------------------------------------------------------------------
# Integration test — script runs against real repo and exits 0
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_real_repo_passes():
    """Script exits 0 (PASS) on the actual ledger history in this repository."""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = os.path.join(repo_root, "scripts", "check_invariant_history_replay.py")
    result = subprocess.run(
        [sys.executable, script, "--root", repo_root, "--json"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Script exited {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    data = json.loads(result.stdout)
    assert data["status"] == "PASS", f"Expected PASS, got: {data}"
    # Hard invariant violations must be zero; pool_anomalies may be non-zero
    # for pre-escrow-era keyless events in the real ledger.
    assert data["violations"] == [], f"Unexpected hard violations: {data['violations']}"
    assert data["events_replayed"] > 0, "Should have replayed at least one event"
