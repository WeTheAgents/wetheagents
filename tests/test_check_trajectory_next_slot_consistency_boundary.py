"""Boundary-spec tests for scripts/check_trajectory_next_slot_consistency.py.

The checker validates that trajectory_mints.json next_slot values are
consistent with mint events in ledger/history/*.jsonl.  For each T1-T6 it
computes max_minted_slot from history and verifies:
  - next_slot == max_minted_slot + 1  (when history events exist for trajectory)
  - next_slot == 20 (NO_MINT_NEXT_SLOT) (when no history events for trajectory)
It also detects duplicate (trajectory, slot) pairs across all history files.

run_check(root) returns:
  {"status": "PASS"|"FAIL",
   "duplicate_slots": [...],
   "next_slot_violations": [...]}

All test fixtures write real files to tmp_path.

## Gaps

GAP-1  Empty trajectories triggers 6 violations — when trajectory_mints.json
       has `"trajectories": {}` and history is empty, the checker iterates
       TARGET_TRAJECTORIES (T1-T6) and flags every trajectory absent from
       trajectory_info as a missing-declaration violation.  The spec expects
       PASS (no constraints to violate), but the checker returns FAIL with
       six next_slot_violations.
       Severity: MEDIUM — a freshly initialised ledger would fail CI.
       See test_case1_empty_trajectories_gap.

GAP-2  Duplicate slot triggers FAIL even when next_slot is correct — the
       checker reports any (trajectory, slot) pair that appears more than once
       in history as a violation, regardless of whether the declared next_slot
       is still consistent with the max.  The spec expects PASS when the
       next_slot computation is unaffected by the duplicate.
       Severity: LOW — the FAIL is conservative; duplicate events warrant
       investigation even if they do not shift the max.
       See test_case4_duplicate_slot_in_history_gap.
"""
from __future__ import annotations

import json
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from check_trajectory_next_slot_consistency import run_check


# ── helpers ───────────────────────────────────────────────────────────────────

_ALL_DEFAULT = {
    "T1": {"next_slot": 20},
    "T2": {"next_slot": 20},
    "T3": {"next_slot": 20},
    "T4": {"next_slot": 20},
    "T5": {"next_slot": 20},
    "T6": {"next_slot": 20},
}


def _write_mints(tmp_path: Path, trajectories: dict) -> None:
    ledger = tmp_path / "ledger"
    ledger.mkdir(parents=True, exist_ok=True)
    (ledger / "trajectory_mints.json").write_text(
        json.dumps({"trajectories": trajectories}), encoding="utf-8"
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


def _mint(traj: str, slot: int) -> dict:
    return {"type": "gauntlet_mint", "trajectory": traj, "slot": slot}


# ── 1. Empty trajectories object — GAP-1 ─────────────────────────────────────
# trajectory_mints.json has `"trajectories": {}`.  No history events exist.
# Spec says PASS (no declared next_slot constraints → nothing to violate).
# Actual: FAIL — the checker iterates TARGET_TRAJECTORIES (T1-T6) and flags
# each as missing from trajectory_info, producing 6 next_slot_violations.
#
# Decision table:
# | trajectories | history | dup_slots | violations  | actual | spec |
# |--------------|---------|-----------|-------------|--------|------|
# | {}           | (none)  | []        | T1-T6 (×6)  | FAIL   | PASS |
# GAP-1: empty trajectory dict causes 6 missing-declaration violations.


def test_case1_empty_trajectories_gap(tmp_path: Path) -> None:
    """trajectory_mints.json with empty trajectories dict → FAIL (GAP-1: spec says PASS)."""
    _write_mints(tmp_path, {})
    _history(tmp_path)

    result = run_check(tmp_path)

    # GAP-1: every T1-T6 is absent from trajectory_info → 6 violations
    assert result["status"] == "FAIL"
    assert result["duplicate_slots"] == []
    assert len(result["next_slot_violations"]) == 6
    flagged = {v["trajectory"] for v in result["next_slot_violations"]}
    assert flagged == {"T1", "T2", "T3", "T4", "T5", "T6"}


# ── 2. Single trajectory, one minted slot ────────────────────────────────────
# T1 has next_slot=21.  History contains one gauntlet_mint at T1 slot 20.
# T2-T6 are present with next_slot=20 (no mints).  max(T1)=20 → expected=21.
#
# Decision table:
# | T1.next_slot | T1 history | T2-T6.next_slot | T2-T6 history | dup_slots | violations | expected |
# |--------------|------------|-----------------|---------------|-----------|------------|----------|
# | 21           | [slot 20]  | 20              | (none)        | []        | []         | PASS     |


def test_case2_single_trajectory_one_minted_slot(tmp_path: Path) -> None:
    """T1 next_slot=21 with one gauntlet_mint at slot 20 → PASS."""
    trajectories = {**_ALL_DEFAULT, "T1": {"next_slot": 21}}
    _write_mints(tmp_path, trajectories)
    _write_jsonl(_history(tmp_path) / "2026-04-25.jsonl", [_mint("T1", 20)])

    result = run_check(tmp_path)

    assert result["status"] == "PASS"
    assert result["duplicate_slots"] == []
    assert result["next_slot_violations"] == []


# ── 3. Multi-file history for one trajectory ──────────────────────────────────
# T2's minted slots span two JSONL files: 2026-04-20 has slot 34, 2026-04-21
# has slot 35.  The checker unions events across sorted filenames.
# max(T2)=35 → expected next_slot=36.
#
# Decision table:
# | T2.next_slot | 2026-04-20.jsonl | 2026-04-21.jsonl | max(T2) | expected | dup_slots | expected |
# |--------------|------------------|------------------|---------|----------|-----------|----------|
# | 36           | T2 slot 34       | T2 slot 35       | 35      | 36       | []        | PASS     |


def test_case3_multi_file_history_same_trajectory(tmp_path: Path) -> None:
    """T2 slots spread across two JSONL files → checker unions both, max=35, next_slot=36 → PASS."""
    trajectories = {**_ALL_DEFAULT, "T2": {"next_slot": 36}}
    _write_mints(tmp_path, trajectories)
    hist = _history(tmp_path)
    _write_jsonl(hist / "2026-04-20.jsonl", [_mint("T2", 34)])
    _write_jsonl(hist / "2026-04-21.jsonl", [_mint("T2", 35)])

    result = run_check(tmp_path)

    assert result["status"] == "PASS"
    assert result["duplicate_slots"] == []
    assert result["next_slot_violations"] == []


# ── 4. Duplicate slot in history — GAP-2 ─────────────────────────────────────
# (T3, slot 33) appears twice in the same JSONL file.  max(T3) is still 33,
# so expected next_slot=34 matches declared.
# Spec says PASS (max is correctly computed; duplicate does not skip any slot).
# Actual: FAIL — find_duplicate_slots reports (T3, 33, count=2) as a violation
# regardless of whether next_slot is consistent.
#
# Decision table:
# | T3.next_slot | T3 history    | dup_slots      | violations | actual | spec |
# |--------------|---------------|----------------|------------|--------|------|
# | 34           | [33, 33]      | [(T3,33,×2)]   | []         | FAIL   | PASS |
# GAP-2: duplicate detection is independent of next_slot correctness.


def test_case4_duplicate_slot_in_history_gap(tmp_path: Path) -> None:
    """T3 slot 33 appears twice → FAIL (GAP-2: spec says PASS because next_slot is still correct)."""
    trajectories = {**_ALL_DEFAULT, "T3": {"next_slot": 34}}
    _write_mints(tmp_path, trajectories)
    _write_jsonl(
        _history(tmp_path) / "2026-04-25.jsonl",
        [_mint("T3", 33), _mint("T3", 33)],
    )

    result = run_check(tmp_path)

    # GAP-2: duplicate slot triggers FAIL even though next_slot=34 is correct
    assert result["status"] == "FAIL"
    assert result["next_slot_violations"] == []
    assert len(result["duplicate_slots"]) == 1
    dup = result["duplicate_slots"][0]
    assert dup["trajectory"] == "T3"
    assert dup["slot"] == 33
    assert dup["count"] == 2


# ── 5. Trajectory in ledger but no history events ────────────────────────────
# T5 is declared in trajectory_mints.json with next_slot=20 (the initial
# default).  No gauntlet_mint events exist for T5.  The checker uses
# NO_MINT_NEXT_SLOT=20 as expected when a trajectory has no history, so
# declared=20 matches expected=20 → no violation.
#
# Decision table:
# | T5.next_slot | T5 history | max(T5)  | expected | dup_slots | violations | expected |
# |--------------|------------|----------|----------|-----------|------------|----------|
# | 20           | (none)     | (absent) | 20       | []        | []         | PASS     |


def test_case5_trajectory_in_ledger_no_history_events(tmp_path: Path) -> None:
    """T5 next_slot=20, no history events → matches NO_MINT_NEXT_SLOT=20 → PASS."""
    _write_mints(tmp_path, dict(_ALL_DEFAULT))
    _history(tmp_path)  # empty — no events for any trajectory

    result = run_check(tmp_path)

    assert result["status"] == "PASS"
    assert result["duplicate_slots"] == []
    assert result["next_slot_violations"] == []


# ── 6. Correct next_slot on trajectory with history ───────────────────────────
# T6 has next_slot=37.  History contains one gauntlet_mint at T6 slot 36.
# max(T6)=36 → expected=37 → declared=37 → no violation.
#
# Decision table:
# | T6.next_slot | T6 history max | expected | dup_slots | violations | expected |
# |--------------|----------------|----------|-----------|------------|----------|
# | 37           | 36             | 37       | []        | []         | PASS     |


def test_case6_correct_next_slot_with_history(tmp_path: Path) -> None:
    """T6 next_slot=37, history max=36 → max+1=37=declared → PASS."""
    trajectories = {**_ALL_DEFAULT, "T6": {"next_slot": 37}}
    _write_mints(tmp_path, trajectories)
    _write_jsonl(_history(tmp_path) / "2026-04-25.jsonl", [_mint("T6", 36)])

    result = run_check(tmp_path)

    assert result["status"] == "PASS"
    assert result["duplicate_slots"] == []
    assert result["next_slot_violations"] == []


# ── 7. Off-by-two next_slot ───────────────────────────────────────────────────
# T1 has next_slot=37 but history max is slot 35.  Expected next=max+1=36.
# Declared=37 ≠ 36 → violation (slot 36 was skipped in the declaration).
#
# Decision table:
# | T1.next_slot | T1 history max | expected | declared | dup_slots | violations | expected |
# |--------------|----------------|----------|----------|-----------|------------|----------|
# | 37           | 35             | 36       | 37       | []        | [T1]       | FAIL     |


def test_case7_off_by_two_next_slot(tmp_path: Path) -> None:
    """T1 next_slot=37, history max=35 → expected=36, off-by-two → FAIL."""
    trajectories = {**_ALL_DEFAULT, "T1": {"next_slot": 37}}
    _write_mints(tmp_path, trajectories)
    _write_jsonl(_history(tmp_path) / "2026-04-25.jsonl", [_mint("T1", 35)])

    result = run_check(tmp_path)

    assert result["status"] == "FAIL"
    assert result["duplicate_slots"] == []
    assert len(result["next_slot_violations"]) == 1
    v = result["next_slot_violations"][0]
    assert v["trajectory"] == "T1"
    assert v["declared_next_slot"] == 37
    assert v["expected_next_slot"] == 36
    assert v["history_max_slot"] == 35
