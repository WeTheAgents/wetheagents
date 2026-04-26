"""Boundary-spec tests for scripts/check_trajectory_mint_amount_formula.py.

The checker validates that every gauntlet mint satisfies amount == 19 + slot.
It reads from two sources:
  - ledger/trajectory_mints.json: {"mints": [...]} — list of mint records
  - ledger/history/*.jsonl: events with type "trajectory_mint"

run_check(root) returns:
  {"status": "PASS"|"FAIL",
   "mint_violations": [...],
   "history_violations": [...],
   "summary": {...}}

All test fixtures write real files to tmp_path.

## Gaps

GAP-1  Off-by-one amount not tolerated — the issue spec describes ±1 tolerance
       for multi-agent split remainders (amount = 19 + slot + 1 should PASS),
       but the checker enforces strict equality: any amount != 19 + slot
       is a violation.
       Severity: MEDIUM — a legitimate off-by-one from integer division would
       fail CI.
       See test_case5_off_by_one_above_tolerance_gap.

GAP-2  Per-agent history events fail formula check — when a multi-agent mint
       writes one history event per agent (each carrying that agent's share as
       `amount`), the checker compares each share against 19 + slot (the full
       slot total).  A valid three-way split of slot 30 (16 + 16 + 17 = 49)
       produces three violations because 16 != 49 and 17 != 49.
       Severity: HIGH — any per-agent history record for a shared slot will
       unconditionally fail CI even when the distribution is correct.
       See test_case7_multi_agent_valid_split_gap.
"""
from __future__ import annotations

import json
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from check_trajectory_mint_amount_formula import run_check


# ── helpers ───────────────────────────────────────────────────────────────────

def _write_mints(tmp_path: Path, mints: list[dict]) -> None:
    ledger = tmp_path / "ledger"
    ledger.mkdir(parents=True, exist_ok=True)
    (ledger / "trajectory_mints.json").write_text(
        json.dumps({"mints": mints}), encoding="utf-8"
    )


def _write_jsonl(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(e) for e in events) + "\n",
        encoding="utf-8",
    )


def _history(tmp_path: Path) -> Path:
    p = tmp_path / "ledger" / "history"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _mint(traj: str, slot: int, amount: int) -> dict:
    """A trajectory_mints.json mint record."""
    return {"trajectory": traj, "slot": slot, "amount": amount}


def _event(traj: str, slot: int, amount: int) -> dict:
    """A ledger/history/*.jsonl trajectory_mint event."""
    return {"type": "trajectory_mint", "trajectory": traj, "slot": slot, "amount": amount}


# ── 1. Slot at formula lower boundary (slot = 1 → expected 20 WEA) ───────────
# Single mint record for T1 slot 1 with amount=20.  Formula: 19 + 1 = 20.
#
# Decision table:
# | trajectory | slot | amount | expected | dup | violations | result |
# |------------|------|--------|----------|-----|------------|--------|
# | T1         | 1    | 20     | 20       | []  | []         | PASS   |


def test_case1_slot_lower_boundary_correct(tmp_path: Path) -> None:
    """slot=1, amount=20 (19+1) → no violations → PASS."""
    _write_mints(tmp_path, [_mint("T1", 1, 20)])
    _history(tmp_path)

    result = run_check(tmp_path)

    assert result["status"] == "PASS"
    assert result["mint_violations"] == []
    assert result["history_violations"] == []
    assert result["summary"]["mint_events"] == 1
    assert result["summary"]["total_violations"] == 0


# ── 2. Slot at formula upper boundary (slot = 100 → expected 119 WEA) ─────────
# Single history event for T2 slot 100 with amount=119.  Formula: 19 + 100 = 119.
#
# Decision table:
# | trajectory | slot | amount | expected | dup | violations | result |
# |------------|------|--------|----------|-----|------------|--------|
# | T2         | 100  | 119    | 119      | []  | []         | PASS   |


def test_case2_slot_upper_boundary_correct(tmp_path: Path) -> None:
    """slot=100, amount=119 (19+100) → no violations → PASS."""
    _write_mints(tmp_path, [])
    _write_jsonl(_history(tmp_path) / "2026-04-25.jsonl", [_event("T2", 100, 119)])

    result = run_check(tmp_path)

    assert result["status"] == "PASS"
    assert result["mint_violations"] == []
    assert result["history_violations"] == []
    assert result["summary"]["history_events"] == 1
    assert result["summary"]["total_violations"] == 0


# ── 3. Slot boundary violation (one correct, one wrong) ───────────────────────
# T1 slot 1 correct (amount=20), T2 slot 100 wrong (amount=120, expected 119).
# Only T2 should appear in violations.
#
# Decision table:
# | trajectory | slot | amount | expected | violation |
# |------------|------|--------|----------|-----------|
# | T1         | 1    | 20     | 20       | no        |
# | T2         | 100  | 120    | 119      | yes       |
# Expected: FAIL, 1 mint_violation for T2 slot 100.


def test_case3_slot_boundary_violation(tmp_path: Path) -> None:
    """slot=1 correct + slot=100 with amount=120 (expected 119) → 1 violation → FAIL."""
    _write_mints(tmp_path, [_mint("T1", 1, 20), _mint("T2", 100, 120)])
    _history(tmp_path)

    result = run_check(tmp_path)

    assert result["status"] == "FAIL"
    assert len(result["mint_violations"]) == 1
    v = result["mint_violations"][0]
    assert v["trajectory"] == "T2"
    assert v["slot"] == 100
    assert v["amount"] == 120
    assert v["expected_amount"] == 119
    assert result["history_violations"] == []


# ── 4. Off-by-one below expected amount ──────────────────────────────────────
# T3 slot 30: formula gives 49.  amount=48 is one below — both spec and checker
# treat this as a violation.
#
# Decision table:
# | trajectory | slot | amount | expected | violation | spec  | actual |
# |------------|------|--------|----------|-----------|-------|--------|
# | T3         | 30   | 48     | 49       | yes       | FAIL  | FAIL   |
# No gap — checker and spec agree.


def test_case4_off_by_one_below_expected(tmp_path: Path) -> None:
    """slot=30, amount=48 (expected 49) → 1 violation → FAIL."""
    _write_mints(tmp_path, [_mint("T3", 30, 48)])
    _history(tmp_path)

    result = run_check(tmp_path)

    assert result["status"] == "FAIL"
    assert len(result["mint_violations"]) == 1
    v = result["mint_violations"][0]
    assert v["slot"] == 30
    assert v["amount"] == 48
    assert v["expected_amount"] == 49


# ── 5. Off-by-one above expected — GAP-1 ─────────────────────────────────────
# T4 slot 30: formula gives 49.  amount=50 is one above.  The issue spec says
# ±1 tolerance should be allowed for multi-agent split remainders → PASS.
# Actual: FAIL — the checker enforces exact equality; 50 != 49 is a violation.
#
# Decision table:
# | trajectory | slot | amount | expected | tolerance | spec  | actual |
# |------------|------|--------|----------|-----------|-------|--------|
# | T4         | 30   | 50     | 49       | ±1        | PASS  | FAIL   |
# GAP-1: off-by-one tolerance not implemented.


def test_case5_off_by_one_above_tolerance_gap(tmp_path: Path) -> None:
    """slot=30, amount=50 (19+30+1) → FAIL (GAP-1: spec says ±1 tolerance → PASS)."""
    _write_mints(tmp_path, [_mint("T4", 30, 50)])
    _history(tmp_path)

    result = run_check(tmp_path)

    # GAP-1: checker rejects amount=50 even though it's within ±1 of expected 49
    assert result["status"] == "FAIL"
    assert len(result["mint_violations"]) == 1
    v = result["mint_violations"][0]
    assert v["slot"] == 30
    assert v["amount"] == 50
    assert v["expected_amount"] == 49


# ── 6. Off-by-two above expected ─────────────────────────────────────────────
# T5 slot 30: amount=51 is two above expected 49.  Both spec and checker agree
# this exceeds any reasonable tolerance.
#
# Decision table:
# | trajectory | slot | amount | expected | spec  | actual |
# |------------|------|--------|----------|-------|--------|
# | T5         | 30   | 51     | 49       | FAIL  | FAIL   |
# No gap.


def test_case6_off_by_two_above_expected(tmp_path: Path) -> None:
    """slot=30, amount=51 (19+30+2) → 1 violation → FAIL."""
    _write_mints(tmp_path, [_mint("T5", 30, 51)])
    _history(tmp_path)

    result = run_check(tmp_path)

    assert result["status"] == "FAIL"
    assert len(result["mint_violations"]) == 1
    v = result["mint_violations"][0]
    assert v["slot"] == 30
    assert v["amount"] == 51
    assert v["expected_amount"] == 49


# ── 7. Multi-agent valid split — GAP-2 ───────────────────────────────────────
# 3-agent team, slot 30: total payout = 49, split [16, 16, 17] (remainder to
# last agent).  The issue spec says each individual share is valid because the
# sum equals 19 + slot.  Three separate history events carry per-agent amounts.
# Actual: FAIL — the checker compares each event's amount against 19+30=49,
# so 16 != 49 and 17 != 49 produce 3 violations.
#
# Decision table:
# | agent   | slot | amount | expected | spec  | actual |
# |---------|------|--------|----------|-------|--------|
# | agent-1 | 30   | 16     | 49       | PASS  | FAIL   |
# | agent-2 | 30   | 16     | 49       | PASS  | FAIL   |
# | agent-3 | 30   | 17     | 49       | PASS  | FAIL   |
# GAP-2: per-agent history events fail formula check.


def test_case7_multi_agent_valid_split_gap(tmp_path: Path) -> None:
    """3 history events for T1 slot 30 with amounts [16,16,17] (sum=49) → FAIL (GAP-2)."""
    _write_mints(tmp_path, [])
    _write_jsonl(
        _history(tmp_path) / "2026-04-25.jsonl",
        [
            _event("T1", 30, 16),
            _event("T1", 30, 16),
            _event("T1", 30, 17),
        ],
    )

    result = run_check(tmp_path)

    # GAP-2: valid split rejected because checker expects each amount == 49
    assert result["status"] == "FAIL"
    assert result["mint_violations"] == []
    assert len(result["history_violations"]) == 3
    amounts = sorted(v["amount"] for v in result["history_violations"])
    assert amounts == [16, 16, 17]
    assert all(v["expected_amount"] == 49 for v in result["history_violations"])


# ── 8. Multi-agent invalid split ─────────────────────────────────────────────
# 3-agent team, slot 30: amounts [15, 17, 17], sum=49.  Agent-1 receives 15
# which is below floor(49/3)=16 — an invalid distribution.  Both spec and
# checker agree this should fail.  (Checker fails for the same reason as the
# valid split: each amount != 49.)
#
# Decision table:
# | agent   | slot | amount | expected | spec  | actual |
# |---------|------|--------|----------|-------|--------|
# | agent-1 | 30   | 15     | 49       | FAIL  | FAIL   |
# | agent-2 | 30   | 17     | 49       | FAIL  | FAIL   |
# | agent-3 | 30   | 17     | 49       | FAIL  | FAIL   |
# No gap — both agree on FAIL (though for different reasons).


def test_case8_multi_agent_invalid_split(tmp_path: Path) -> None:
    """3 history events for T1 slot 30 with amounts [15,17,17] (sum=49) → FAIL."""
    _write_mints(tmp_path, [])
    _write_jsonl(
        _history(tmp_path) / "2026-04-25.jsonl",
        [
            _event("T1", 30, 15),
            _event("T1", 30, 17),
            _event("T1", 30, 17),
        ],
    )

    result = run_check(tmp_path)

    assert result["status"] == "FAIL"
    assert len(result["history_violations"]) == 3
    amounts = sorted(v["amount"] for v in result["history_violations"])
    assert amounts == [15, 17, 17]


# ── 9. Empty trajectory_mints.json, no history ───────────────────────────────
# trajectory_mints.json has an empty mints list.  No history events exist.
# Nothing to validate → PASS.
#
# Decision table:
# | mints | history | violations | result |
# |-------|---------|------------|--------|
# | []    | (none)  | []         | PASS   |


def test_case9_empty_mints_no_history(tmp_path: Path) -> None:
    """Empty mints list and no history events → nothing to check → PASS."""
    _write_mints(tmp_path, [])
    _history(tmp_path)

    result = run_check(tmp_path)

    assert result["status"] == "PASS"
    assert result["mint_violations"] == []
    assert result["history_violations"] == []
    assert result["summary"]["mint_events"] == 0
    assert result["summary"]["history_events"] == 0


# ── 10. One trajectory absent from all records ────────────────────────────────
# T1-T5 have correct mint records and history events.  T6 has no records at
# all.  The checker only validates records that exist — absent trajectories are
# not violations.
#
# Decision table:
# | trajectory | in mints | in history | violations | result |
# |------------|----------|------------|------------|--------|
# | T1-T5      | yes (✓)  | yes (✓)    | []         | PASS   |
# | T6         | no       | no         | []         | PASS   |


def test_case10_one_trajectory_absent_from_all_records(tmp_path: Path) -> None:
    """T1-T5 all correct; T6 completely absent → no violations for T6 → PASS."""
    mints = [
        _mint("T1", 35, 54),
        _mint("T2", 36, 55),
        _mint("T3", 33, 52),
        _mint("T4", 34, 53),
        _mint("T5", 30, 49),
    ]
    _write_mints(tmp_path, mints)
    history_events = [
        _event("T1", 35, 54),
        _event("T2", 36, 55),
        _event("T3", 33, 52),
        _event("T4", 34, 53),
        _event("T5", 30, 49),
    ]
    _write_jsonl(_history(tmp_path) / "2026-04-25.jsonl", history_events)

    result = run_check(tmp_path)

    assert result["status"] == "PASS"
    assert result["mint_violations"] == []
    assert result["history_violations"] == []


# ── 11. Duplicate slot — both entries correct ─────────────────────────────────
# (T1, slot 30) appears twice in history, both with amount=49 (correct).
# The checker validates each entry independently; both pass.
#
# Decision table:
# | event | trajectory | slot | amount | expected | violation | result |
# |-------|------------|------|--------|----------|-----------|--------|
# | 1     | T1         | 30   | 49     | 49       | no        |        |
# | 2     | T1         | 30   | 49     | 49       | no        | PASS   |


def test_case11_duplicate_slot_both_correct(tmp_path: Path) -> None:
    """T1 slot 30 appears twice in history both with amount=49 → both valid → PASS."""
    _write_mints(tmp_path, [])
    _write_jsonl(
        _history(tmp_path) / "2026-04-25.jsonl",
        [_event("T1", 30, 49), _event("T1", 30, 49)],
    )

    result = run_check(tmp_path)

    assert result["status"] == "PASS"
    assert result["mint_violations"] == []
    assert result["history_violations"] == []
    assert result["summary"]["history_events"] == 2


# ── 12. Duplicate slot — second entry wrong ───────────────────────────────────
# (T1, slot 30) appears twice: first with correct amount=49, second with
# wrong amount=50.  The checker validates each independently; the second fails.
#
# Decision table:
# | event | trajectory | slot | amount | expected | violation | result |
# |-------|------------|------|--------|----------|-----------|--------|
# | 1     | T1         | 30   | 49     | 49       | no        |        |
# | 2     | T1         | 30   | 50     | 49       | yes       | FAIL   |


def test_case12_duplicate_slot_second_entry_wrong(tmp_path: Path) -> None:
    """T1 slot 30 twice: first amount=49 (correct), second amount=50 → 1 violation → FAIL."""
    _write_mints(tmp_path, [])
    _write_jsonl(
        _history(tmp_path) / "2026-04-25.jsonl",
        [_event("T1", 30, 49), _event("T1", 30, 50)],
    )

    result = run_check(tmp_path)

    assert result["status"] == "FAIL"
    assert result["mint_violations"] == []
    assert len(result["history_violations"]) == 1
    v = result["history_violations"][0]
    assert v["trajectory"] == "T1"
    assert v["slot"] == 30
    assert v["amount"] == 50
    assert v["expected_amount"] == 49


# ── 13. Non-integer slot ──────────────────────────────────────────────────────
# A mint record carries slot="30" (string) instead of int 30.  The checker's
# coerce helper rejects non-integer slot values with a descriptive error,
# records a violation, and continues — it does not raise an exception.
#
# Decision table:
# | trajectory | slot    | amount | coerce_slot | violation       | result |
# |------------|---------|--------|-------------|-----------------|--------|
# | T1         | "30"    | 49     | error       | slot not int    | FAIL   |


def test_case13_non_integer_slot(tmp_path: Path) -> None:
    """slot='30' (string) → coerce rejects non-integer → 1 violation → FAIL."""
    ledger = tmp_path / "ledger"
    ledger.mkdir(parents=True, exist_ok=True)
    (ledger / "trajectory_mints.json").write_text(
        json.dumps({"mints": [{"trajectory": "T1", "slot": "30", "amount": 49}]}),
        encoding="utf-8",
    )
    _history(tmp_path)

    result = run_check(tmp_path)

    assert result["status"] == "FAIL"
    assert len(result["mint_violations"]) == 1
    v = result["mint_violations"][0]
    assert v["trajectory"] == "T1"
    assert v["slot"] == "30"
    assert v["expected_amount"] is None
    assert "not an integer" in v["detail"]
