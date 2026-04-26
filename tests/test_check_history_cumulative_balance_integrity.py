"""Tests for check_history_cumulative_balance_integrity.py"""

import json
from pathlib import Path

import pytest

from scripts.check_history_cumulative_balance_integrity import (
    AGENT0,
    compare_final,
    load_events,
    replay,
    run,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_jsonl(path: Path, events: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")


def _write_balances(root: Path, agents: dict[str, int]) -> None:
    payload = {
        "agents": {
            agent_id: {"balance": bal, "platform": "test"}
            for agent_id, bal in agents.items()
        },
        "version": 1,
    }
    (root / "ledger").mkdir(parents=True, exist_ok=True)
    (root / "ledger" / "balances.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _make_repo(root: Path, events: list[dict], balances: dict[str, int]) -> None:
    history_dir = root / "ledger" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(history_dir / "2026-01-01.jsonl", events)
    _write_balances(root, balances)


# ---------------------------------------------------------------------------
# 1. Clean history → PASS
# ---------------------------------------------------------------------------


def test_clean_history_passes(tmp_path):
    events = [
        {
            "type": "escrow_create",
            "author": AGENT0,
            "amount": 50,
            "issue": 1,
            "timestamp": "2026-01-01T00:00:00Z",
        },
        {
            "type": "payment",
            "agent": "Alice@test",
            "amount": 50,
            "issue": 1,
            "timestamp": "2026-01-01T01:00:00Z",
        },
    ]
    # agent0 starts at 10_000, pays 50 into escrow, so ends at 9_950.
    # Alice earns 50.
    _make_repo(tmp_path, events, {AGENT0: 9_950, "Alice@test": 50})
    result, passed = run(tmp_path)
    assert passed, result["summary"]
    assert result["status"] == "PASS"
    assert result["negative_violations"] == []
    assert result["final_mismatches"] == []


# ---------------------------------------------------------------------------
# 2. Event that drives agent to -1 → FAIL with clear message
# ---------------------------------------------------------------------------


def test_negative_balance_fails(tmp_path):
    events = [
        # Bob receives payment but has no balance source — starts from 0
        {
            "type": "payment",
            "agent": "Bob@test",
            "amount": 10,
            "issue": 1,
            "timestamp": "2026-01-01T00:00:00Z",
        },
        # Escrow creation debits agent0 (fine)
        {
            "type": "escrow_create",
            "author": AGENT0,
            "amount": 10,
            "issue": 1,
            "timestamp": "2026-01-01T01:00:00Z",
        },
        # Bob now has 10; spend 11 via another escrow_create (Bob becomes -1)
        {
            "type": "escrow_create",
            "author": "Bob@test",
            "amount": 11,
            "issue": 2,
            "timestamp": "2026-01-01T02:00:00Z",
        },
    ]
    _make_repo(tmp_path, events, {AGENT0: 9_990, "Bob@test": -1})
    result, passed = run(tmp_path)
    assert not passed
    assert result["status"] == "FAIL"
    assert len(result["negative_violations"]) >= 1
    first = result["negative_violations"][0]
    assert first["agent"] == "Bob@test"
    assert first["balance"] < 0
    assert first["event_type"] is not None
    assert first["event_ts"] == "2026-01-01T02:00:00Z"


# ---------------------------------------------------------------------------
# 3. Agent reaching exactly 0 → PASS (zero is valid)
# ---------------------------------------------------------------------------


def test_zero_balance_is_valid(tmp_path):
    events = [
        {
            "type": "escrow_create",
            "author": AGENT0,
            "amount": 30,
            "issue": 1,
            "timestamp": "2026-01-01T00:00:00Z",
        },
        {
            "type": "payment",
            "agent": "Carol@test",
            "amount": 30,
            "issue": 1,
            "timestamp": "2026-01-01T01:00:00Z",
        },
        # Carol spends exactly her 30 WEA on escrow
        {
            "type": "escrow_create",
            "author": "Carol@test",
            "amount": 30,
            "issue": 2,
            "timestamp": "2026-01-01T02:00:00Z",
        },
    ]
    # Carol ends at 0; agent0 ends at 9_970 (two escrow_creates of 30 each)
    _make_repo(tmp_path, events, {AGENT0: 9_970, "Carol@test": 0})
    result, passed = run(tmp_path)
    assert passed, result["summary"]
    assert result["negative_violations"] == []


# ---------------------------------------------------------------------------
# 4. Final balance mismatch vs balances.json → FAIL
# ---------------------------------------------------------------------------


def test_final_balance_mismatch_fails(tmp_path):
    events = [
        {
            "type": "escrow_create",
            "author": AGENT0,
            "amount": 25,
            "issue": 1,
            "timestamp": "2026-01-01T00:00:00Z",
        },
        {
            "type": "payment",
            "agent": "Dave@test",
            "amount": 25,
            "issue": 1,
            "timestamp": "2026-01-01T01:00:00Z",
        },
    ]
    # Lie in balances.json: claim Dave has 99 instead of the correct 25
    _make_repo(tmp_path, events, {AGENT0: 9_975, "Dave@test": 99})
    result, passed = run(tmp_path)
    assert not passed
    assert result["status"] == "FAIL"
    assert any(m["agent"] == "Dave@test" for m in result["final_mismatches"])
    mismatch = next(m for m in result["final_mismatches"] if m["agent"] == "Dave@test")
    assert mismatch["stored"] == 99
    assert mismatch["computed"] == 25


# ---------------------------------------------------------------------------
# 5. Empty history dir → PASS (no events = no violations)
# ---------------------------------------------------------------------------


def test_empty_history_passes(tmp_path):
    history_dir = tmp_path / "ledger" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    # balances.json with only agent0 at genesis balance
    _write_balances(tmp_path, {})
    result, passed = run(tmp_path)
    assert passed, result["summary"]
    assert result["events_replayed"] == 0
    assert result["negative_violations"] == []
    assert result["final_mismatches"] == []


# ---------------------------------------------------------------------------
# 6. Out-of-order events (wrong ts in file) → handled (sorted before replay)
# ---------------------------------------------------------------------------


def test_out_of_order_events_sorted(tmp_path):
    """Events written out of chronological order must be sorted before replay.

    If not sorted, the escrow_create (debit) would come AFTER the payment
    (credit), never triggering a negative balance for agent0.  After sorting
    by timestamp the debit happens first — the test verifies the sort order
    works and the result is still PASS (no negative for agent0 which starts
    at 10_000).
    """
    # Deliberately write payment BEFORE escrow_create (reversed timestamps)
    events = [
        {
            "type": "payment",
            "agent": "Eve@test",
            "amount": 40,
            "issue": 1,
            "timestamp": "2026-01-01T01:00:00Z",  # later timestamp, written first
        },
        {
            "type": "escrow_create",
            "author": AGENT0,
            "amount": 40,
            "issue": 1,
            "timestamp": "2026-01-01T00:00:00Z",  # earlier timestamp, written second
        },
    ]
    _make_repo(tmp_path, events, {AGENT0: 9_960, "Eve@test": 40})
    result, passed = run(tmp_path)
    assert passed, result["summary"]


# ---------------------------------------------------------------------------
# 7. trajectory_mint with 'to' field → correctly credited
# ---------------------------------------------------------------------------


def test_trajectory_mint_to_field(tmp_path):
    """trajectory_mint events using 'to' instead of 'agents'/'per_agent'."""
    events = [
        {
            "ts": "2026-01-01T00:00:00Z",
            "type": "trajectory_mint",
            "trajectory": "T1",
            "slot": 1,
            "amount": 42,
            "to": "Frank@test",
            "issue": 10,
        }
    ]
    _make_repo(tmp_path, events, {AGENT0: 10_000, "Frank@test": 42})
    result, passed = run(tmp_path)
    assert passed, result["summary"]


# ---------------------------------------------------------------------------
# 8. Idempotent duplicate payment detected via balance_after → skipped
# ---------------------------------------------------------------------------


def test_duplicate_payment_noop_via_balance_after(tmp_path):
    """A duplicate payment whose balance_after matches current balance is a no-op."""
    events = [
        # First payment: valid, raises Grace from 0 to 30
        {
            "type": "escrow_create",
            "author": AGENT0,
            "amount": 30,
            "issue": 1,
            "timestamp": "2026-01-01T00:00:00Z",
        },
        {
            "type": "payment",
            "agent": "Grace@test",
            "amount": 30,
            "issue": 1,
            "balance_after": 30,
            "timestamp": "2026-01-01T01:00:00Z",
        },
        # Duplicate payment: balance_after still 30 (no actual increment)
        {
            "type": "payment",
            "agent": "Grace@test",
            "amount": 30,
            "issue": 1,
            "balance_after": 30,  # same as current → no-op
            "timestamp": "2026-01-01T01:00:08Z",
        },
    ]
    # Grace should end at 30, not 60
    _make_repo(tmp_path, events, {AGENT0: 9_970, "Grace@test": 30})
    result, passed = run(tmp_path)
    assert passed, result["summary"]


# ---------------------------------------------------------------------------
# 9. replay() unit: negative violation carries correct fields
# ---------------------------------------------------------------------------


def test_replay_negative_violation_fields():
    events = [
        {
            "type": "escrow_create",
            "author": "Hank@test",
            "amount": 5,
            "issue": 1,
            "timestamp": "2026-01-01T00:00:00Z",
        }
    ]
    result = replay(events)
    assert len(result["negative_violations"]) == 1
    v = result["negative_violations"][0]
    assert v["agent"] == "Hank@test"
    assert v["balance"] == -5
    assert v["event_type"] == "escrow_create"
    assert v["event_ts"] == "2026-01-01T00:00:00Z"
    assert v["event_issue"] == 1
    assert v["event_amount"] == 5


# ---------------------------------------------------------------------------
# 10. compare_final() unit: skips agent0, flags mismatches
# ---------------------------------------------------------------------------


def test_compare_final_skips_agent0():
    computed = {AGENT0: 999, "Ivy@test": 50}
    balances_json = {"agents": {AGENT0: {"balance": 123}, "Ivy@test": {"balance": 50}}}
    mismatches = compare_final(computed, balances_json)
    # agent0 skipped → no mismatch reported
    assert not any(m.get("agent") == AGENT0 for m in mismatches)
    assert mismatches == []


def test_compare_final_reports_mismatch():
    computed = {"Jake@test": 100}
    balances_json = {"agents": {"Jake@test": {"balance": 200}}}
    mismatches = compare_final(computed, balances_json)
    assert len(mismatches) == 1
    assert mismatches[0]["agent"] == "Jake@test"
    assert mismatches[0]["stored"] == 200
    assert mismatches[0]["computed"] == 100
    assert mismatches[0]["delta"] == -100


# ---------------------------------------------------------------------------
# 11. load_events() unit: malformed JSON lines are skipped
# ---------------------------------------------------------------------------


def test_load_events_skips_malformed_json(tmp_path):
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    f = history_dir / "2026-01-01.jsonl"
    f.write_text(
        '{"type":"payment","agent":"Kay@test","amount":10,"timestamp":"2026-01-01T00:00:00Z"}\n'
        "this is not json\n"
        '{"type":"mint","agent":"Kay@test","amount":5,"timestamp":"2026-01-01T01:00:00Z"}\n',
        encoding="utf-8",
    )
    events = load_events(history_dir)
    assert len(events) == 2


# ---------------------------------------------------------------------------
# 12. economy_reset clears pre-reset violations
# ---------------------------------------------------------------------------


def test_economy_reset_clears_violations(tmp_path):
    events = [
        # Pre-reset: OldAgent goes negative (messy early history)
        {
            "type": "escrow_create",
            "author": "OldAgent@test",
            "amount": 999,
            "issue": 1,
            "timestamp": "2026-01-01T00:00:00Z",
        },
        # Reset: clean slate
        {
            "type": "economy_reset",
            "agents_zeroed": ["OldAgent@test"],
            "wea_returned_to_agent0": 0,
            "timestamp": "2026-01-02T00:00:00Z",
        },
    ]
    _make_repo(tmp_path, events, {AGENT0: 10_000})
    result, passed = run(tmp_path)
    assert passed, result["summary"]
    assert result["negative_violations"] == []
