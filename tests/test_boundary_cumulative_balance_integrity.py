"""Boundary-spec tests for scripts/check_history_cumulative_balance_integrity.py.

These tests close every ambiguous edge case for the per-agent cumulative balance
checker (T1S41, issue #871). They are the executable spec: each scenario
documents the invariant, uses synthetic minimal data, and asserts the exact
expected behavior at the boundary.

9 boundary scenarios (issue #874):
  1. balance_floor_zero       — debit to exactly 0 is valid → PASS
  2. balance_floor_minus_one  — debit to -1 triggers violation → FAIL
  3. first_event_debit        — debit before any credit → FAIL
  4. same_timestamp           — tied ts values → deterministic order, no exception
  5. escrow_exceeds_balance   — escrow amount > available balance → FAIL
  6. escrow_return_after_dereg — return after agent_removal → FAIL with mismatch, no crash
  7. future_dated_file        — 2099-01-01.jsonl included without crashing → PASS
  8. credits_only             — no debits at all → PASS, final matches balances.json
  9. partial_escrow_mismatch  — computed > stored by exactly active escrow → PASS
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.check_history_cumulative_balance_integrity import run


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hist(root: Path, filename: str, events: list[dict]) -> None:
    """Write events as a JSONL file inside ledger/history/."""
    hist_dir = root / "ledger" / "history"
    hist_dir.mkdir(parents=True, exist_ok=True)
    (hist_dir / filename).write_text(
        "\n".join(json.dumps(e) for e in events) + "\n",
        encoding="utf-8",
    )


def _set_balances(root: Path, agents: dict[str, int]) -> None:
    """Overwrite ledger/balances.json with a minimal agents dict."""
    (root / "ledger" / "balances.json").write_text(
        json.dumps({
            "version": 1,
            "agents": {k: {"balance": v} for k, v in agents.items()},
        }),
        encoding="utf-8",
    )


def _set_escrows(root: Path, active: dict) -> None:
    """Overwrite ledger/escrows.json with the given active escrow entries."""
    (root / "ledger" / "escrows.json").write_text(
        json.dumps({"version": 1, "active": active}),
        encoding="utf-8",
    )


# =============================================================================
# Scenario 1: Balance floor = 0 → PASS
# =============================================================================
# Invariant: a balance at exactly 0 after a debit event is valid.
# The floor is 0 — the violation threshold is strictly < 0.
# Reaching zero must not trigger a negative-balance error.
#
# Event sequence:
#   payment(100) → escrow_create(100) → balance = 0
#
# Decision table:
#   | event          | before | amount | after | violation? |
#   |----------------|--------|--------|-------|------------|
#   | payment(100)   | 0      | +100   | 100   | no         |
#   | escrow_create  | 100    | -100   | 0     | no  ← spec |
#
# The check is balance < 0 (strict); balance == 0 must PASS.
# =============================================================================


def test_balance_floor_zero_is_valid(temp_repo: Path) -> None:
    """Debit reducing balance to exactly 0 must PASS (floor is 0, violation is < 0)."""
    _set_balances(temp_repo, {"alice@test": 0})
    _hist(temp_repo, "2026-01-01.jsonl", [
        {"type": "payment",       "agent": "alice@test", "amount": 100,
         "ts": "2026-01-01T01:00:00Z"},
        {"type": "escrow_create", "author": "alice@test", "amount": 100, "issue": 1,
         "ts": "2026-01-01T02:00:00Z"},
    ])
    result, passed = run(temp_repo)
    assert passed is True
    assert result["status"] == "PASS"
    assert result["negative_violations"] == []
    assert result["final_mismatches"] == []


# =============================================================================
# Scenario 2: Balance floor = -1 → FAIL
# =============================================================================
# Invariant: any debit that pushes a balance below 0 is a violation.
# A balance of -1 must be detected and reported immediately after the
# event that caused it.
#
# Event sequence:
#   payment(50) → escrow_create(51) → balance = -1
#
# Decision table:
#   | event         | before | amount | after | violation? |
#   |---------------|--------|--------|-------|------------|
#   | payment(50)   | 0      | +50    | 50    | no         |
#   | escrow_create | 50     | -51    | -1    | YES ← spec |
# =============================================================================


def test_balance_floor_minus_one_triggers_violation(temp_repo: Path) -> None:
    """Debit reducing balance to -1 must FAIL with a negative-balance violation."""
    _hist(temp_repo, "2026-01-01.jsonl", [
        {"type": "payment",       "agent": "alice@test", "amount": 50,
         "ts": "2026-01-01T01:00:00Z"},
        {"type": "escrow_create", "author": "alice@test", "amount": 51, "issue": 2,
         "ts": "2026-01-01T02:00:00Z"},
    ])
    result, passed = run(temp_repo)
    assert passed is False
    assert result["status"] == "FAIL"
    violating_agents = {v["agent"] for v in result["negative_violations"]}
    assert "alice@test" in violating_agents
    alice_balances = [
        v["balance"] for v in result["negative_violations"]
        if v["agent"] == "alice@test"
    ]
    assert any(b < 0 for b in alice_balances)


# =============================================================================
# Scenario 3: First event is a debit with no prior credit → FAIL
# =============================================================================
# Invariant: agents start at balance 0. Any debit before the first credit
# is a violation, even in legacy data where a debit appears as the very
# first event. The checker must detect and report this immediately.
#
# Event sequence:
#   escrow_create(10) for alice (no payment before it) → balance = -10
#
# Decision table:
#   | event          | before | amount | after | violation? |
#   |----------------|--------|--------|-------|------------|
#   | escrow_create  | 0      | -10    | -10   | YES ← spec |
# =============================================================================


def test_first_event_debit_no_prior_credit_fails(temp_repo: Path) -> None:
    """First history event is a debit with no prior credit → FAIL with clear violation."""
    _hist(temp_repo, "2026-01-01.jsonl", [
        {"type": "escrow_create", "author": "alice@test", "amount": 10, "issue": 3,
         "ts": "2026-01-01T01:00:00Z"},
    ])
    result, passed = run(temp_repo)
    assert passed is False
    assert result["status"] == "FAIL"
    violating_agents = {v["agent"] for v in result["negative_violations"]}
    assert "alice@test" in violating_agents


# =============================================================================
# Scenario 4: Same-timestamp events → deterministic order, no exception
# =============================================================================
# Invariant: when two events share the same ts value, the checker applies
# them in a consistent deterministic order — sorted by (filename, line_number)
# as a tiebreaker — without raising an exception. The result must be
# reproducible: identical inputs produce identical outputs across calls.
#
# Design: two same-timestamp escrow_creates whose combined total stays within
# alice's balance, so any ordering produces PASS. This isolates the
# "no ordering ambiguity" invariant from the balance-floor invariant.
#
# Event sequence (all in one file, T1 = T2):
#   payment(100) at T0
#   escrow_create(40) at T1  (line 2)
#   escrow_create(40) at T1  (line 3) — same ts as line 2
#   combined debit = 80 ≤ 100 → PASS under any ordering
#
# Decision table (line 2 before line 3 by line-number sort):
#   | event        | before | after | floor? |
#   |--------------|--------|-------|--------|
#   | escrow(40)   | 100    | 60    | OK     |
#   | escrow(40)   | 60     | 20    | OK     |
# =============================================================================


def test_same_timestamp_events_handled_deterministically(temp_repo: Path) -> None:
    """Same-ts events apply in a consistent order without exception; combined within budget → PASS."""
    _set_balances(temp_repo, {"alice@test": 20})
    _hist(temp_repo, "2026-01-01.jsonl", [
        {"type": "payment",       "agent": "alice@test", "amount": 100,
         "ts": "2026-01-01T01:00:00Z"},
        {"type": "escrow_create", "author": "alice@test", "amount": 40, "issue": 4,
         "ts": "2026-01-01T02:00:00Z"},
        {"type": "escrow_create", "author": "alice@test", "amount": 40, "issue": 5,
         "ts": "2026-01-01T02:00:00Z"},
    ])
    result1, passed1 = run(temp_repo)
    result2, passed2 = run(temp_repo)
    # No exception raised; both calls PASS
    assert passed1 is True
    assert passed2 is True
    assert result1["status"] == "PASS"
    # Determinism: two calls produce identical output
    assert result2["status"] == result1["status"]
    assert result2["negative_violations"] == result1["negative_violations"]


# =============================================================================
# Scenario 5: Escrow amount > available balance → FAIL
# =============================================================================
# Invariant: an escrow_create that debits more than the agent holds at that
# moment drives the balance negative and must be caught immediately.
#
# Event sequence:
#   payment(50) → escrow_create(100) → balance = -50
#
# Decision table:
#   | event          | before | amount | after | violation? |
#   |----------------|--------|--------|-------|------------|
#   | payment(50)    | 0      | +50    | 50    | no         |
#   | escrow_create  | 50     | -100   | -50   | YES ← spec |
# =============================================================================


def test_escrow_exceeds_balance_triggers_violation(temp_repo: Path) -> None:
    """escrow_create for more than available balance → FAIL; violation shows balance = -50."""
    _hist(temp_repo, "2026-01-01.jsonl", [
        {"type": "payment",       "agent": "alice@test", "amount": 50,
         "ts": "2026-01-01T01:00:00Z"},
        {"type": "escrow_create", "author": "alice@test", "amount": 100, "issue": 6,
         "ts": "2026-01-01T02:00:00Z"},
    ])
    result, passed = run(temp_repo)
    assert passed is False
    assert result["status"] == "FAIL"
    alice_violations = [
        v for v in result["negative_violations"] if v["agent"] == "alice@test"
    ]
    assert len(alice_violations) >= 1
    assert alice_violations[0]["balance"] == -50


# =============================================================================
# Scenario 6: Escrow return after agent deregistration → FAIL with mismatch, no crash
# =============================================================================
# Invariant: an escrow_return event for a previously deregistered agent must
# not raise an exception. The checker handles it gracefully by applying the
# credit normally, but since the agent is absent from balances.json the
# non-zero computed balance becomes a final-balance mismatch.
#
# Specified behavior: FAIL — reported as "agent present in history but absent
# from balances.json". No crash; the mismatch is deterministic and actionable.
#
# Event sequence:
#   payment(30) → agent_removal(alice, balance_returned=0) → escrow_return(alice, 20)
#   After removal:   alice.balance = 0  (set to 0 by agent_removal)
#   After return:    alice.balance = 20
#   balances.json:   alice absent  →  computed=20 ≠ absent → final_mismatch → FAIL
# =============================================================================


def test_escrow_return_after_deregistration_fails_gracefully(temp_repo: Path) -> None:
    """escrow_return for a deregistered agent must not crash; FAIL with final mismatch."""
    _set_balances(temp_repo, {})  # alice removed from ledger
    _hist(temp_repo, "2026-01-01.jsonl", [
        {"type": "payment",       "agent": "alice@test", "amount": 30,
         "ts": "2026-01-01T01:00:00Z"},
        {"type": "agent_removal", "agent": "alice@test", "balance_returned": 0,
         "ts": "2026-01-01T02:00:00Z"},
        {"type": "escrow_return", "agent": "alice@test", "amount": 20, "issue": 7,
         "ts": "2026-01-01T03:00:00Z"},
    ])
    # Must not raise; must FAIL with a mismatch for alice's ghost balance
    result, passed = run(temp_repo)
    assert passed is False
    assert result["status"] == "FAIL"
    mismatch_agents = {m["agent"] for m in result["final_mismatches"]}
    assert "alice@test" in mismatch_agents


# =============================================================================
# Scenario 7: History file dated in the future (2099) → included, no crash
# =============================================================================
# Invariant: the checker must include all *.jsonl files in ledger/history/
# regardless of their filename date, including dates far in the future.
# A file named 2099-01-01.jsonl with valid events must be replayed without
# crashing. Future-dated files are unusual but not invalid — their filename
# date is used only as a sort-key tiebreaker when the event's ts is absent.
#
# Event sequence:
#   2099-01-01.jsonl: payment(50) for alice with explicit ts 2099-01-01T00:00:00Z
#   balances.json: alice.balance = 50 → PASS
# =============================================================================


def test_future_dated_history_file_included_without_crash(temp_repo: Path) -> None:
    """2099-dated history file must be included in replay without exception → PASS."""
    _set_balances(temp_repo, {"alice@test": 50})
    _hist(temp_repo, "2099-01-01.jsonl", [
        {"type": "payment", "agent": "alice@test", "amount": 50,
         "ts": "2099-01-01T00:00:00Z"},
    ])
    result, passed = run(temp_repo)
    assert passed is True
    assert result["status"] == "PASS"
    assert result["events_replayed"] >= 1


# =============================================================================
# Scenario 8: All events are credits only → PASS
# =============================================================================
# Invariant: a history containing only credit events (payment, mint,
# trajectory_mint) with no debits must always PASS. No agent can go negative
# if only positive amounts are applied. The final computed balance must match
# balances.json exactly.
#
# Event sequence:
#   payment(30) + trajectory_mint(20) + mint(10) for alice → final = 60
#   balances.json: alice.balance = 60 → exact match → PASS
# =============================================================================


def test_credits_only_history_passes(temp_repo: Path) -> None:
    """History with only credit events (no debits) always PASSes; final balance matches exactly."""
    _set_balances(temp_repo, {"alice@test": 60})
    _hist(temp_repo, "2026-01-01.jsonl", [
        {"type": "payment",         "agent": "alice@test", "amount": 30,
         "ts": "2026-01-01T01:00:00Z"},
        {"type": "trajectory_mint", "agent": "alice@test", "amount": 20,
         "ts": "2026-01-01T02:00:00Z"},
        {"type": "mint",            "agent": "alice@test", "amount": 10,
         "ts": "2026-01-01T03:00:00Z"},
    ])
    result, passed = run(temp_repo)
    assert passed is True
    assert result["status"] == "PASS"
    assert result["negative_violations"] == []
    assert result["final_mismatches"] == []


# =============================================================================
# Scenario 9: Partial mismatch by active escrow amount → PASS (escrow tolerance)
# =============================================================================
# Invariant: when an agent's final computed balance (from history replay)
# exceeds their stored balance in balances.json by exactly the sum of their
# active escrow obligations, this is expected and must PASS.
#
# This arises when balances.json already reflects a deduction for a recently
# created escrow, but the escrow_create event has not yet been written to a
# history file. The active escrows.json records the pending obligation; the
# checker uses it as a tolerance buffer.
#
# Setup:
#   history: payment(100) for alice (no escrow_create in history)
#   balances.json: alice.balance = 70  (escrow already deducted in ledger)
#   escrows.json:  active = {"1": {author: alice, amount: 30}}
#   computed = 100, stored = 70, diff = 30 = escrow total → tolerated → PASS
#
# Decision table:
#   | computed | stored | diff | escrow_total | tolerated? |
#   |----------|--------|------|--------------|------------|
#   | 100      | 70     | 30   | 30           | YES ← spec |
#   | 100      | 65     | 35   | 30           | NO  ← guard|
# =============================================================================


def test_partial_mismatch_within_active_escrow_tolerance_passes(temp_repo: Path) -> None:
    """Computed > stored by exactly active escrow amount → PASS (diff == escrow_total)."""
    _set_balances(temp_repo, {"alice@test": 70})
    _set_escrows(temp_repo, {
        "1": {"author": "alice@test", "amount": 30, "type": "standard"},
    })
    _hist(temp_repo, "2026-01-01.jsonl", [
        {"type": "payment", "agent": "alice@test", "amount": 100,
         "ts": "2026-01-01T01:00:00Z"},
    ])
    result, passed = run(temp_repo)
    assert passed is True
    assert result["status"] == "PASS"
    assert result["final_mismatches"] == []


def test_partial_mismatch_exceeding_escrow_tolerance_fails(temp_repo: Path) -> None:
    """Computed > stored by more than active escrow total → FAIL (not tolerated).

    Boundary guard: diff=35 with escrow_total=30 is not covered and must FAIL.
    This ensures the tolerance is exact, not an upper bound.
    """
    _set_balances(temp_repo, {"alice@test": 65})
    _set_escrows(temp_repo, {
        "1": {"author": "alice@test", "amount": 30, "type": "standard"},
    })
    _hist(temp_repo, "2026-01-01.jsonl", [
        {"type": "payment", "agent": "alice@test", "amount": 100,
         "ts": "2026-01-01T01:00:00Z"},
    ])
    result, passed = run(temp_repo)
    assert passed is False
    assert result["status"] == "FAIL"
