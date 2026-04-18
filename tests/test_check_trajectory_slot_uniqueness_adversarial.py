"""Adversarial bypass tests for scripts/check_trajectory_slot_uniqueness.py.

Each test names a specific bypass vector — inputs that either:
  (a) cause a real violation to be reported as PASS (false negative / GAP), or
  (b) confirm that a tricky encoding variant is correctly detected (FAIL).

Bypass vectors covered:
  1.  [GAP] Case-sensitive trajectory: 'T1' ≠ 't1' → double-mint bypasses
              detection because str() preserves case → PASS
  2.  [GAP] Slot gap not detected: only max_slot is tracked; gaps in the minted
              sequence (e.g. [1, 3] missing 2) are invisible → PASS
  3.  [GAP] Null slot event skipped: slot=None drops event silently; a second
              mint whose slot field was corrupted to null evades detection → PASS
  4.  [GAP] Large slot gap [1,2,5]: multiple holes (3 and 4 absent) are invisible
              because only max_slot determines expected next_slot → PASS
  5.  Timestamp collision: different timestamps, same (traj, slot) → FAIL
  6.  Whitespace leading slot: ' 22' normalised to 22 by int() → FAIL
  7.  Whitespace trailing slot: '22 ' normalised to 22 by int() → FAIL
  8.  String-typed slot: '5' coerced to int 5 → duplicate detected → FAIL
  9.  Float-typed slot: 5.0 coerced to int 5 → duplicate detected → FAIL
 10.  Bool slot True == 1: int(True)=1, duplicate with slot=1 detected → FAIL
 11.  next_slot = max_slot (off-by-one): expected max+1, declared max → FAIL
 12.  next_slot = max_slot - 1 (regression): expected max+1, declared max-1 → FAIL
 13.  next_slot skips forward by two: expected max+1, declared max+2 → FAIL
 14.  Duplicate across multiple JSONL files: same (traj, slot) in two separate
              files → FAIL
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from check_trajectory_slot_uniqueness import (
    find_double_mints,
    find_next_slot_drift,
    run_check,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_ledger(tmp_path: Path, events: list[dict], trajectories: dict) -> Path:
    """Write a minimal fake ledger under tmp_path and return the root.

    All events are written to a single JSONL file.  For multi-file scenarios
    use make_ledger_two_files instead.
    """
    history_dir = tmp_path / "ledger" / "history"
    history_dir.mkdir(parents=True)
    with (history_dir / "2026-01-01.jsonl").open("w", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev) + "\n")
    mints_data = {
        "version": 1,
        "total_minted": 0,
        "trajectories": trajectories,
        "mints": [],
    }
    with (tmp_path / "ledger" / "trajectory_mints.json").open("w", encoding="utf-8") as fh:
        json.dump(mints_data, fh)
    return tmp_path


def make_ledger_two_files(
    tmp_path: Path,
    events_a: list[dict],
    events_b: list[dict],
    trajectories: dict,
) -> Path:
    """Write two separate JSONL history files under tmp_path."""
    history_dir = tmp_path / "ledger" / "history"
    history_dir.mkdir(parents=True)
    with (history_dir / "2026-01-01.jsonl").open("w", encoding="utf-8") as fh:
        for ev in events_a:
            fh.write(json.dumps(ev) + "\n")
    with (history_dir / "2026-01-02.jsonl").open("w", encoding="utf-8") as fh:
        for ev in events_b:
            fh.write(json.dumps(ev) + "\n")
    mints_data = {
        "version": 1,
        "total_minted": 0,
        "trajectories": trajectories,
        "mints": [],
    }
    with (tmp_path / "ledger" / "trajectory_mints.json").open("w", encoding="utf-8") as fh:
        json.dump(mints_data, fh)
    return tmp_path


def mint_event(trajectory: str, slot, amount: int = 20, timestamp: str = "2026-01-01T00:00:00Z") -> dict:
    """Return a trajectory_mint event dict.  slot may be any JSON-serialisable type."""
    return {
        "type": "trajectory_mint",
        "trajectory": trajectory,
        "slot": slot,
        "amount": amount,
        "agents": ["agent-x@claude"],
        "per_agent": [amount],
        "issue": 100,
        "timestamp": timestamp,
    }


def traj_info(next_slot: int) -> dict:
    return {"name": "Test Trajectory", "next_slot": next_slot, "total_minted": 0}


# ---------------------------------------------------------------------------
# Test 1 — [GAP] Case-sensitive trajectory bypasses double-mint detection
# ---------------------------------------------------------------------------


def test_case_mismatch_trajectory_bypasses_double_mint_detection(tmp_path: Path) -> None:
    """[CONFIRMED GAP] find_double_mints normalises trajectories with str(traj),
    which preserves case.  Two events that refer to the same logical trajectory
    (e.g. 'T1' and 't1') are treated as different keys and are never counted as
    a duplicate pair.

    Real violation: two mint events both target trajectory T1, slot 22 — one
    is written with the canonical 'T1' key, the other with lowercase 't1'.
    The checker should report a double-mint, but because str('T1') ≠ str('t1'),
    the counts dict has two singleton entries.  No duplicate is detected → PASS.

    Bypass mechanism: str() in `key = (str(traj), int(slot))` performs no
    case normalisation.  An adversary writing a second mint event with a
    differently-cased trajectory name can evade the uniqueness check entirely.
    """
    events = [
        mint_event("T1", 22, timestamp="2026-01-01T00:00:00Z"),
        mint_event("t1", 22, timestamp="2026-01-01T01:00:00Z"),  # same slot, lowercase traj
    ]
    trajectories = {
        "T1": traj_info(next_slot=23),
        "t1": traj_info(next_slot=23),
    }
    root = make_ledger(tmp_path, events, trajectories)
    payload = run_check(root)

    # GAP: 't1' and 'T1' are distinct keys; count never reaches 2 for either
    assert payload["status"] == "PASS", (
        "Two mint events for slot 22 — one as 'T1', one as 't1' — are not "
        "treated as duplicates.  str() preserves case; the double-mint is "
        "invisible to find_double_mints."
    )
    assert payload["double_mints"] == [], (
        "double_mints is empty despite two events targeting the same slot on "
        "the same trajectory under different case spellings."
    )


# ---------------------------------------------------------------------------
# Test 2 — [GAP] Slot gap not detected: only max_slot used for next_slot check
# ---------------------------------------------------------------------------


def test_slot_gap_not_detected_only_max_slot_used(tmp_path: Path) -> None:
    """[CONFIRMED GAP] find_next_slot_drift tracks only the maximum minted slot
    per trajectory.  It computes expected_next_slot = max_slot + 1 and compares
    that against the declared value.  It does NOT verify that every integer from
    1 to max_slot has been minted.

    Real violation: T1 has minted slots [1, 3] — slot 2 was skipped.  A correct
    ledger should have slot 2 before slot 3 could be minted.  With max_slot = 3
    and declared next_slot = 4 the drift check passes cleanly.  The missing
    slot 2 is never reported → PASS.

    Bypass mechanism: max_slot tracking is O(1) state but only catches forward
    drift and regressions.  Gaps (holes in the contiguous sequence) are
    structurally undetectable by this algorithm.
    """
    events = [
        mint_event("T1", 1),
        mint_event("T1", 3),  # slot 2 was never minted
    ]
    trajectories = {"T1": traj_info(next_slot=4)}  # max=3 → expected=4, correct
    root = make_ledger(tmp_path, events, trajectories)
    payload = run_check(root)

    # GAP: max=3 → expected next_slot=4, declared=4 → no drift; gap at 2 undetected
    assert payload["status"] == "PASS", (
        "Slots [1, 3] have a gap at 2.  The checker only tracks max_slot (3) "
        "and validates next_slot == max+1 (4).  The gap at slot 2 is invisible."
    )
    assert payload["next_slot_drift"] == [], (
        "next_slot_drift is empty even though slot 2 was never minted before "
        "slot 3 appeared in history."
    )


# ---------------------------------------------------------------------------
# Test 3 — [GAP] Null slot event silently skipped, hides potential duplicate
# ---------------------------------------------------------------------------


def test_null_slot_event_skipped_hides_duplicate_mint(tmp_path: Path) -> None:
    """[CONFIRMED GAP] find_double_mints skips any event where slot is None via
    `if traj is None or slot is None: continue`.  A second mint for an already-
    minted slot, whose slot field was corrupted to null, is dropped without any
    warning and never increments the duplicate counter.

    Real violation: trajectory T2, slot 5 was minted once legitimately.  A
    second mint attempt was written to history, but its slot field is null
    (perhaps due to a serialisation error or deliberate tampering).  The
    checker should flag a suspicious second trajectory_mint event for T2,
    but the null-slot guard drops it silently → PASS.

    Bypass mechanism: the None-check is necessary to avoid a TypeError in
    int(slot), but it creates a silent drop with no audit trail.  An attacker
    can craft a second mint event with slot=null to evade duplicate detection.
    """
    events = [
        mint_event("T2", 5),           # legitimate first mint
        mint_event("T2", None),        # second mint with corrupted/null slot
    ]
    trajectories = {"T2": traj_info(next_slot=6)}
    root = make_ledger(tmp_path, events, trajectories)
    payload = run_check(root)

    # GAP: null slot event is silently discarded; only one event counted for T2
    assert payload["status"] == "PASS", (
        "A second trajectory_mint for T2 with slot=null is silently dropped.  "
        "Only the first event (slot=5) is counted.  No duplicate detected → PASS "
        "even though two trajectory_mint events exist for the same trajectory."
    )
    assert payload["double_mints"] == []


# ---------------------------------------------------------------------------
# Test 4 — [GAP] Large slot gap [1,2,5] — multiple holes invisible
# ---------------------------------------------------------------------------


def test_large_slot_gap_multiple_holes_not_detected(tmp_path: Path) -> None:
    """[CONFIRMED GAP] The gap-detection blind spot extends to multiple missing
    slots.  Slots [1, 2, 5] leave holes at 3 and 4.  With max_slot = 5 the
    expected next_slot = 6 matches the declared value → PASS.

    This test confirms that the GAP in test 2 is not an edge case but a
    structural property of the max_slot algorithm: any number of missing
    interior slots are undetectable as long as next_slot == max+1.
    """
    events = [
        mint_event("T3", 1),
        mint_event("T3", 2),
        mint_event("T3", 5),  # slots 3 and 4 were never minted
    ]
    trajectories = {"T3": traj_info(next_slot=6)}  # max=5 → expected=6, correct
    root = make_ledger(tmp_path, events, trajectories)
    payload = run_check(root)

    # GAP: max=5, declared=6, matches → PASS despite gaps at 3 and 4
    assert payload["status"] == "PASS", (
        "Slots [1, 2, 5] have gaps at 3 and 4.  max_slot=5, expected=6, declared=6 "
        "→ no drift reported.  Two missing slots are structurally undetectable."
    )
    assert payload["next_slot_drift"] == []


# ---------------------------------------------------------------------------
# Test 5 — Timestamp collision: different timestamps, same (traj, slot) → FAIL
# ---------------------------------------------------------------------------


def test_timestamp_collision_same_slot_detected_as_double_mint(tmp_path: Path) -> None:
    """Timestamps are ignored by find_double_mints.  Two events with the same
    (trajectory, slot) pair but different timestamps are correctly counted as
    a duplicate.  The bypass attempt — disguising the second event with a
    different timestamp — fails because the key is (str(traj), int(slot)) only.

    This documents that the timestamp-bypass vector does NOT work: the checker
    correctly counts unique (traj, slot) pairs regardless of when they occurred.
    """
    events = [
        mint_event("T1", 22, timestamp="2026-01-01T00:00:00Z"),
        mint_event("T1", 22, timestamp="2026-01-02T12:00:00Z"),  # same slot, different time
    ]
    trajectories = {"T1": traj_info(next_slot=23)}
    root = make_ledger(tmp_path, events, trajectories)
    payload = run_check(root)

    assert payload["status"] == "FAIL"
    assert len(payload["double_mints"]) == 1
    dm = payload["double_mints"][0]
    assert dm["trajectory"] == "T1"
    assert dm["slot"] == 22
    assert dm["count"] == 2


# ---------------------------------------------------------------------------
# Test 6 — Whitespace leading slot: ' 22' normalised to 22 → FAIL
# ---------------------------------------------------------------------------


def test_whitespace_leading_slot_normalised_duplicate_detected(tmp_path: Path) -> None:
    """Python's int() strips leading whitespace: int(' 22') == 22.  A slot value
    of ' 22' (string with leading space) is normalised to the same integer as
    a bare slot=22.  Two events — one with slot=' 22', one with slot=22 — are
    detected as a duplicate for the same trajectory.

    The whitespace-bypass vector does NOT work: int() coercion defeats it.
    """
    events = [
        mint_event("T1", " 22"),   # string with leading whitespace
        mint_event("T1", 22),      # canonical int
    ]
    trajectories = {"T1": traj_info(next_slot=23)}
    root = make_ledger(tmp_path, events, trajectories)
    payload = run_check(root)

    assert payload["status"] == "FAIL"
    assert len(payload["double_mints"]) == 1
    dm = payload["double_mints"][0]
    assert dm["slot"] == 22, "int(' 22') normalises to 22; both events share the same key"


# ---------------------------------------------------------------------------
# Test 7 — Whitespace trailing slot: '22 ' normalised to 22 → FAIL
# ---------------------------------------------------------------------------


def test_whitespace_trailing_slot_normalised_duplicate_detected(tmp_path: Path) -> None:
    """Python's int() strips trailing whitespace: int('22 ') == 22.  A slot value
    of '22 ' (string with trailing space) is normalised to the same integer as
    a bare slot=22.  The trailing-whitespace encoding variant does NOT bypass
    duplicate detection.
    """
    events = [
        mint_event("T1", "22 "),   # string with trailing whitespace
        mint_event("T1", 22),      # canonical int
    ]
    trajectories = {"T1": traj_info(next_slot=23)}
    root = make_ledger(tmp_path, events, trajectories)
    payload = run_check(root)

    assert payload["status"] == "FAIL"
    assert len(payload["double_mints"]) == 1
    dm = payload["double_mints"][0]
    assert dm["slot"] == 22, "int('22 ') normalises to 22; both events share the same key"


# ---------------------------------------------------------------------------
# Test 8 — String-typed slot: '5' coerced to int 5 → FAIL
# ---------------------------------------------------------------------------


def test_string_slot_coerced_to_int_duplicate_detected(tmp_path: Path) -> None:
    """int('5') == 5.  A slot encoded as the JSON string '5' is coerced to the
    same integer as a bare int 5.  Two events — one with slot='5', one with
    slot=5 — are detected as duplicates.

    Unlike check_trajectory_history_sync.py (which uses isinstance guards and
    silently drops non-int slots), this checker uses int(slot) which coerces
    string-typed integers.  The string-encoding variant does NOT bypass detection.
    """
    events = [
        mint_event("T4", "5"),   # JSON-string slot
        mint_event("T4", 5),     # canonical int slot
    ]
    trajectories = {"T4": traj_info(next_slot=6)}
    root = make_ledger(tmp_path, events, trajectories)
    payload = run_check(root)

    assert payload["status"] == "FAIL"
    assert len(payload["double_mints"]) == 1
    dm = payload["double_mints"][0]
    assert dm["trajectory"] == "T4"
    assert dm["slot"] == 5


# ---------------------------------------------------------------------------
# Test 9 — Float-typed slot: 5.0 coerced to int 5 → FAIL
# ---------------------------------------------------------------------------


def test_float_slot_coerced_to_int_duplicate_detected(tmp_path: Path) -> None:
    """int(5.0) == 5.  A slot encoded as a JSON float (5.0) is coerced to the
    same integer as a bare int 5.  Two events — one with slot=5.0, one with
    slot=5 — are detected as duplicates.

    Note: check_trajectory_history_sync.py has a confirmed GAP here because it
    uses isinstance(slot, int) which rejects floats.  This checker uses int(slot)
    which accepts and coerces floats, closing that particular bypass vector.
    """
    events = [
        mint_event("T5", 5.0),   # float-typed slot
        mint_event("T5", 5),     # canonical int slot
    ]
    trajectories = {"T5": traj_info(next_slot=6)}
    root = make_ledger(tmp_path, events, trajectories)
    payload = run_check(root)

    assert payload["status"] == "FAIL"
    assert len(payload["double_mints"]) == 1
    dm = payload["double_mints"][0]
    assert dm["slot"] == 5, "int(5.0) == 5; float and int slot values share the same key"


# ---------------------------------------------------------------------------
# Test 10 — Bool slot True == 1: int(True)=1, duplicate with slot=1 detected
# ---------------------------------------------------------------------------


def test_bool_slot_true_coerced_to_int_one_duplicate_detected(tmp_path: Path) -> None:
    """In Python, bool is a subclass of int: int(True) == 1, int(False) == 0.
    A slot encoded as the boolean True is coerced to 1 and matches a canonical
    int-1 slot.  Two events — one with slot=True, one with slot=1 — are
    detected as duplicates for trajectory T6.

    This is an unusual JSON encoding variant but valid per the JSON spec
    (true is a boolean literal).  The checker correctly normalises it.
    """
    events = [
        mint_event("T6", True),  # boolean True → int 1
        mint_event("T6", 1),     # canonical int 1
    ]
    trajectories = {"T6": traj_info(next_slot=2)}
    root = make_ledger(tmp_path, events, trajectories)
    payload = run_check(root)

    assert payload["status"] == "FAIL"
    assert len(payload["double_mints"]) == 1
    dm = payload["double_mints"][0]
    assert dm["slot"] == 1, "int(True) == 1; bool and int-1 share the same key"
    assert dm["count"] == 2


# ---------------------------------------------------------------------------
# Test 11 — next_slot = max_slot (off-by-one): expected max+1, declared max
# ---------------------------------------------------------------------------


def test_next_slot_equals_max_slot_off_by_one_fails(tmp_path: Path) -> None:
    """find_next_slot_drift requires declared_next_slot == max_minted_slot + 1.
    Declaring next_slot equal to the current max (instead of max+1) means the
    next mint would overwrite an already-minted slot — a double-mint pre-cursor.

    With history slots [1, 2, 3] the correct next_slot is 4.  Declaring
    next_slot=3 (== max) is an off-by-one error that must be flagged as FAIL.
    """
    events = [mint_event("T1", 1), mint_event("T1", 2), mint_event("T1", 3)]
    trajectories = {"T1": traj_info(next_slot=3)}  # should be 4
    root = make_ledger(tmp_path, events, trajectories)
    payload = run_check(root)

    assert payload["status"] == "FAIL"
    assert len(payload["next_slot_drift"]) == 1
    drift = payload["next_slot_drift"][0]
    assert drift["trajectory"] == "T1"
    assert drift["history_max_slot"] == 3
    assert drift["expected_next_slot"] == 4
    assert drift["declared_next_slot"] == 3


# ---------------------------------------------------------------------------
# Test 12 — next_slot = max_slot - 1 (regression): points at already-minted slot
# ---------------------------------------------------------------------------


def test_next_slot_regression_below_max_slot_fails(tmp_path: Path) -> None:
    """Declaring next_slot below max_minted_slot means it points at a slot that
    has already been minted.  The next mint operation would attempt to reuse that
    slot, directly enabling a double-mint.

    With history slots [1, 2, 3, 4] the correct next_slot is 5.  Declaring
    next_slot=3 (== max-1) is a regression that must be flagged as FAIL.
    """
    events = [
        mint_event("T2", 1),
        mint_event("T2", 2),
        mint_event("T2", 3),
        mint_event("T2", 4),
    ]
    trajectories = {"T2": traj_info(next_slot=3)}  # should be 5
    root = make_ledger(tmp_path, events, trajectories)
    payload = run_check(root)

    assert payload["status"] == "FAIL"
    assert len(payload["next_slot_drift"]) == 1
    drift = payload["next_slot_drift"][0]
    assert drift["trajectory"] == "T2"
    assert drift["history_max_slot"] == 4
    assert drift["expected_next_slot"] == 5
    assert drift["declared_next_slot"] == 3


# ---------------------------------------------------------------------------
# Test 13 — next_slot skips forward by two: expected max+1, declared max+2
# ---------------------------------------------------------------------------


def test_next_slot_skips_forward_by_two_fails(tmp_path: Path) -> None:
    """Declaring next_slot = max + 2 skips over a valid slot entirely.  The
    skipped slot can never be issued through normal minting, creating a permanent
    gap in the trajectory sequence.

    With history slots [1, 2] the correct next_slot is 3.  Declaring
    next_slot=4 (== max+2) must be flagged as FAIL with expected=3, declared=4.
    """
    events = [mint_event("T3", 1), mint_event("T3", 2)]
    trajectories = {"T3": traj_info(next_slot=4)}  # should be 3
    root = make_ledger(tmp_path, events, trajectories)
    payload = run_check(root)

    assert payload["status"] == "FAIL"
    assert len(payload["next_slot_drift"]) == 1
    drift = payload["next_slot_drift"][0]
    assert drift["trajectory"] == "T3"
    assert drift["history_max_slot"] == 2
    assert drift["expected_next_slot"] == 3
    assert drift["declared_next_slot"] == 4


# ---------------------------------------------------------------------------
# Test 14 — Duplicate across multiple JSONL files: same (traj, slot) → FAIL
# ---------------------------------------------------------------------------


def test_duplicate_across_multiple_jsonl_files_detected(tmp_path: Path) -> None:
    """load_history_mint_events reads ALL *.jsonl files under ledger/history/.
    A (trajectory, slot) pair that appears in two separate JSONL files is
    accumulated in the same counts dict and correctly identified as a duplicate.

    This confirms that splitting events across files is not a bypass vector:
    the scanner is file-agnostic and the aggregated counts span all files.
    """
    events_file_a = [mint_event("T4", 7, timestamp="2026-01-01T00:00:00Z")]
    events_file_b = [mint_event("T4", 7, timestamp="2026-01-02T00:00:00Z")]  # same slot, different file
    trajectories = {"T4": traj_info(next_slot=8)}

    root = make_ledger_two_files(tmp_path, events_file_a, events_file_b, trajectories)
    payload = run_check(root)

    assert payload["status"] == "FAIL"
    assert len(payload["double_mints"]) == 1
    dm = payload["double_mints"][0]
    assert dm["trajectory"] == "T4"
    assert dm["slot"] == 7
    assert dm["count"] == 2, "Both files contribute to the count; cross-file duplicates detected"
