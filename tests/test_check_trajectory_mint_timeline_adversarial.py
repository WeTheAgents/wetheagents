"""Adversarial tests for scripts/check_trajectory_mint_timeline.py.

Covers four edge-case scenarios not exercised by the baseline test suite:

  (a) Two trajectories advancing in the same JSONL with interleaved events.
      Per-trajectory ordering must be evaluated independently — a violation in T1
      must not bleed into T2 tracking, and vice versa.

  (b) Trajectory_mint events where the slot field in the body disagrees with
      the sequential slot position — specifically the "gap-filling" attack where
      a lower slot is injected after a higher slot has already been seen for
      that trajectory.  The checker must anchor on the highest slot seen, not
      on the first visible gap.

  (c) JSONL history with zero trajectory_mint events — checker must return PASS
      cleanly without crashing, even when the files contain other event types.

  (d) next_slot in trajectory_mints.json lower than the highest slot seen in
      history — potential rollback attack that would allow re-issuing already-
      minted slots.  Checker must flag the divergence.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from check_trajectory_mint_timeline import run_check


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_ledger(
    tmp_path: Path,
    file_events: dict[str, list[dict]],
    trajectories: dict,
) -> Path:
    """Write a fake ledger under tmp_path and return the repo root."""
    history_dir = tmp_path / "ledger" / "history"
    history_dir.mkdir(parents=True)
    for fname, events in file_events.items():
        with (history_dir / fname).open("w") as fh:
            for ev in events:
                fh.write(json.dumps(ev) + "\n")
    mints_data = {
        "version": 1,
        "total_minted": 0,
        "trajectories": trajectories,
        "mints": [],
    }
    with (tmp_path / "ledger" / "trajectory_mints.json").open("w") as fh:
        json.dump(mints_data, fh)
    return tmp_path


def mint(trajectory: str, slot: int) -> dict:
    """Build a minimal trajectory_mint event."""
    return {
        "type": "trajectory_mint",
        "trajectory": trajectory,
        "slot": slot,
        "amount": 20,
        "agents": ["agent-x@claude"],
        "per_agent": [20],
        "issue": 100 + slot,
        "timestamp": "2026-01-01T00:00:00Z",
    }


def traj(next_slot: int) -> dict:
    return {"name": "Test Trajectory", "next_slot": next_slot, "total_minted": 0}


# ---------------------------------------------------------------------------
# (a) Interleaved multi-trajectory events in a single JSONL file
# ---------------------------------------------------------------------------


def test_interleaved_trajectories_one_violated_one_clean(tmp_path: Path) -> None:
    """T1 and T2 events interleaved in one file; T1 has ordering violation, T2 is clean.

    This test confirms that per-trajectory state is tracked independently.
    A naive checker that maintains a global last-slot might fail to detect T1's
    violation when T2 events appear in between T1 events.

    T1 sequence: slot=1 → slot=5 → slot=3 (VIOLATION: 3 < 5)
    T2 sequence: slot=1 → slot=2 → slot=3 (clean)
    """
    file_events = {
        "2026-01-01.jsonl": [
            mint("T1", 1),
            mint("T2", 1),
            mint("T1", 5),
            mint("T2", 2),
            mint("T1", 3),  # violation: 3 < 5
            mint("T2", 3),
        ]
    }
    trajectories = {"T1": traj(6), "T2": traj(4)}
    root = make_ledger(tmp_path, file_events, trajectories)
    result = run_check(root)

    assert result["status"] == "FAIL"
    violated_trajectories = {v["trajectory"] for v in result["ordering_violations"]}
    assert "T1" in violated_trajectories, "T1's ordering violation must be detected"
    assert "T2" not in violated_trajectories, "T2 is clean and must not be flagged"


def test_interleaved_trajectories_second_violated(tmp_path: Path) -> None:
    """Reverse: T1 is clean, T2 has violation despite interleaved ordering.

    T1 sequence: slot=1 → slot=2 → slot=3 (clean)
    T2 sequence: slot=10 → slot=4 → slot=11 (violation at slot=4; slot=11 is clean)

    Confirms per-trajectory independence works regardless of which trajectory
    has the violation.
    """
    file_events = {
        "2026-01-01.jsonl": [
            mint("T1", 1),
            mint("T2", 10),
            mint("T1", 2),
            mint("T2", 4),   # violation: 4 < 10
            mint("T1", 3),
            mint("T2", 11),  # 11 > 10 (the high-water mark), so still no second violation
        ]
    }
    trajectories = {"T1": traj(4), "T2": traj(12)}
    root = make_ledger(tmp_path, file_events, trajectories)
    result = run_check(root)

    assert result["status"] == "FAIL"
    violated_trajectories = {v["trajectory"] for v in result["ordering_violations"]}
    assert "T2" in violated_trajectories, "T2's ordering violation must be detected"
    assert "T1" not in violated_trajectories, "T1 is clean and must not be flagged"


def test_interleaved_trajectories_both_clean(tmp_path: Path) -> None:
    """All events interleaved, both trajectories strictly increasing — PASS.

    Confirms the baseline: heavy interleaving alone does not produce false positives.

    T1: slot=1 → slot=3 → slot=5
    T2: slot=2 → slot=4 → slot=6
    """
    file_events = {
        "2026-01-01.jsonl": [
            mint("T1", 1),
            mint("T2", 2),
            mint("T1", 3),
            mint("T2", 4),
            mint("T1", 5),
            mint("T2", 6),
        ]
    }
    trajectories = {"T1": traj(6), "T2": traj(7)}
    root = make_ledger(tmp_path, file_events, trajectories)
    result = run_check(root)

    assert result["status"] == "PASS"
    assert result["ordering_violations"] == []


# ---------------------------------------------------------------------------
# (b) Slot body disagrees with sequential slot position (gap-filling attack)
# ---------------------------------------------------------------------------


def test_gap_filling_attack_rejected(tmp_path: Path) -> None:
    """A lower slot injected after a higher slot has been seen — gap-filling attack.

    Attack pattern:
      1. Establish a high-water mark: T1 slot=1 → slot=5
      2. Inject slot=3, which fills the "gap" between 1 and 5.

    A vulnerable checker might accept slot=3 because it is within [1, 5] range
    and appears to repair a gap.  The correct checker must anchor on the highest
    slot seen (5) and reject anything ≤ 5 as an ordering violation.
    """
    file_events = {
        "2026-01-01.jsonl": [
            mint("T1", 1),
            mint("T1", 5),
            mint("T1", 3),  # looks like a gap-fill but violates strict ordering
        ]
    }
    trajectories = {"T1": traj(6)}
    root = make_ledger(tmp_path, file_events, trajectories)
    result = run_check(root)

    assert result["status"] == "FAIL"
    assert len(result["ordering_violations"]) == 1
    v = result["ordering_violations"][0]
    assert v["trajectory"] == "T1"
    assert v["slot"] == 3
    assert v["prev_slot"] == 5


def test_gap_filling_multiple_injections(tmp_path: Path) -> None:
    """Multiple lower slots injected after a high-water mark — each must be flagged.

    Attack pattern: T1 slot=1 → slot=10 → slot=5 → slot=7
    Both slot=5 and slot=7 are less than the high-water mark (10) and must be
    flagged.  After slot=5 is a violation, the high-water mark stays at 10, so
    slot=7 is also caught.
    """
    file_events = {
        "2026-01-01.jsonl": [
            mint("T1", 1),
            mint("T1", 10),
            mint("T1", 5),   # violation: 5 < 10
            mint("T1", 7),   # violation: 7 < 10 (high-water mark stays at 10)
        ]
    }
    trajectories = {"T1": traj(11)}
    root = make_ledger(tmp_path, file_events, trajectories)
    result = run_check(root)

    assert result["status"] == "FAIL"
    violations = result["ordering_violations"]
    assert len(violations) == 2
    violation_slots = {v["slot"] for v in violations}
    assert violation_slots == {5, 7}
    # Both violations reference the same high-water mark
    for v in violations:
        assert v["prev_slot"] == 10


# ---------------------------------------------------------------------------
# (c) JSONL history with zero trajectory_mint events
# ---------------------------------------------------------------------------


def test_zero_mint_events_only_other_types(tmp_path: Path) -> None:
    """History contains only non-mint event types — checker must PASS without crashing.

    Verifies that the checker doesn't crash or produce false positives when
    no trajectory_mint events exist in the stream.
    """
    file_events = {
        "2026-01-01.jsonl": [
            {"type": "pay", "agent": "claude-1@claude", "amount": 50, "issue": 5},
            {"type": "escrow_create", "issue": 10, "amount": 30},
            {"type": "escrow_return", "issue": 10, "amount": 30},
            {"type": "claim", "issue": 15, "agent": "claude-1@claude"},
        ]
    }
    trajectories = {"T1": traj(1), "T2": traj(1)}
    root = make_ledger(tmp_path, file_events, trajectories)
    result = run_check(root)

    assert result["status"] == "PASS"
    assert result["ordering_violations"] == []
    assert result["next_slot_drift"] == []


def test_zero_mint_events_multiple_files(tmp_path: Path) -> None:
    """Multiple JSONL files, all containing only non-mint events — PASS.

    Edge case: the history spans several dates but none contain mints.
    """
    file_events = {
        "2026-01-01.jsonl": [
            {"type": "pay", "agent": "a@b", "amount": 10},
        ],
        "2026-01-02.jsonl": [
            {"type": "escrow_create", "issue": 1, "amount": 20},
            {"type": "balance_update", "agent": "a@b", "delta": 10},
        ],
        "2026-01-03.jsonl": [
            {"type": "claim", "issue": 2, "agent": "a@b"},
        ],
    }
    # No trajectories at all in JSON → any empty history is consistent
    trajectories: dict = {}
    root = make_ledger(tmp_path, file_events, trajectories)
    result = run_check(root)

    assert result["status"] == "PASS"
    assert result["ordering_violations"] == []
    assert result["next_slot_drift"] == []


def test_zero_mint_events_empty_trajectories_dict(tmp_path: Path) -> None:
    """trajectory_mints.json has trajectories with next_slot=1 and history has
    no mint events — all trajectories are in "awaiting first mint" state.

    This is the normal state at project genesis: checker must PASS cleanly.
    """
    file_events = {
        "2026-01-01.jsonl": [
            {"type": "pay", "agent": "agent0@system", "amount": 100},
        ]
    }
    trajectories = {
        "T1": traj(1),
        "T2": traj(1),
        "T3": traj(1),
    }
    root = make_ledger(tmp_path, file_events, trajectories)
    result = run_check(root)

    assert result["status"] == "PASS"
    assert result["ordering_violations"] == []
    assert result["next_slot_drift"] == []


# ---------------------------------------------------------------------------
# (d) next_slot lower than max history slot — rollback attack
# ---------------------------------------------------------------------------


def test_rollback_attack_next_slot_below_max(tmp_path: Path) -> None:
    """next_slot rolled back below the highest slot in history.

    Attack: history has T1 slots 1-5, but trajectory_mints.json declares
    next_slot=3.  This would allow re-minting slots 3, 4, or 5 — a classic
    rollback attack.  Checker must flag this as next_slot drift.
    """
    file_events = {
        "2026-01-01.jsonl": [mint("T1", 1), mint("T1", 2)],
        "2026-01-02.jsonl": [mint("T1", 3), mint("T1", 4)],
        "2026-01-03.jsonl": [mint("T1", 5)],
    }
    trajectories = {"T1": traj(3)}  # should be 6; rolled back to 3
    root = make_ledger(tmp_path, file_events, trajectories)
    result = run_check(root)

    assert result["status"] == "FAIL"
    assert result["ordering_violations"] == [], "ordering is clean; only drift detected"
    drift = result["next_slot_drift"]
    assert len(drift) == 1
    d = drift[0]
    assert d["trajectory"] == "T1"
    assert d["history_max_slot"] == 5
    assert d["expected_next_slot"] == 6
    assert d["declared_next_slot"] == 3


def test_rollback_attack_next_slot_to_genesis(tmp_path: Path) -> None:
    """Aggressive rollback: next_slot reset to 1 after many mints.

    Attack: next_slot=1 implies no mints have happened, but history records
    10 slots for T1.  This would allow the entire slot sequence to be re-issued.
    """
    file_events = {
        "2026-01-01.jsonl": [mint("T1", i) for i in range(1, 11)],
    }
    trajectories = {"T1": traj(1)}  # should be 11; fully rolled back
    root = make_ledger(tmp_path, file_events, trajectories)
    result = run_check(root)

    assert result["status"] == "FAIL"
    drift = result["next_slot_drift"]
    assert len(drift) == 1
    d = drift[0]
    assert d["history_max_slot"] == 10
    assert d["expected_next_slot"] == 11
    assert d["declared_next_slot"] == 1


def test_rollback_attack_multi_trajectory(tmp_path: Path) -> None:
    """next_slot rolled back for T2 only while T1 is correct.

    Confirms the checker detects drift per-trajectory and doesn't require all
    trajectories to be wrong before reporting.
    """
    file_events = {
        "2026-01-01.jsonl": [
            mint("T1", 1), mint("T1", 2), mint("T1", 3),
            mint("T2", 1), mint("T2", 2), mint("T2", 3),
        ]
    }
    trajectories = {
        "T1": traj(4),  # correct
        "T2": traj(2),  # rolled back: should be 4
    }
    root = make_ledger(tmp_path, file_events, trajectories)
    result = run_check(root)

    assert result["status"] == "FAIL"
    assert result["ordering_violations"] == []
    drifted = {d["trajectory"] for d in result["next_slot_drift"]}
    assert "T2" in drifted, "T2 rollback must be detected"
    assert "T1" not in drifted, "T1 is correct and must not be flagged"
