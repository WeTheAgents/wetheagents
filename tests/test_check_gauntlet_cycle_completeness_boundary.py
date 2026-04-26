"""Boundary / edge-case tests for scripts/check_gauntlet_cycle_completeness.py.

Covers the 7 scenarios from Task #849:
  1. Single-trajectory cycle — only T1 at slot N → WARNING not VIOLATION
  2. All-but-one cycle — T1-T4 at slot N, T5 missing → VIOLATION
  3. Slot gap in one trajectory — T1 skips slot 32 → VIOLATION
  4. Highest-cycle in-progress boundary — max cycle is incomplete (WARNING);
     earlier gap is VIOLATION regardless
  5. T6 present, T1-T5 absent — must not flag
  6. Empty trajectory_mints.json — must PASS
  7. Single complete cycle — T1-T5 all at slot 1 → PASS
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from check_gauntlet_cycle_completeness import run_check  # noqa: E402


def _write_mints(root: Path, mints: list[dict]) -> None:
    ledger = root / "ledger"
    ledger.mkdir(parents=True, exist_ok=True)
    (ledger / "trajectory_mints.json").write_text(
        json.dumps(
            {
                "version": 1,
                "total_minted": 0,
                "trajectories": {
                    t: {"name": t, "next_slot": 1, "total_minted": 0}
                    for t in ("T1", "T2", "T3", "T4", "T5", "T6")
                },
                "mints": mints,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _full_cycle(slot: int, trajectories: list[str] | None = None) -> list[dict]:
    trajs = trajectories or ["T1", "T2", "T3", "T4", "T5"]
    return [{"trajectory": t, "slot": slot, "amount": 19 + slot} for t in trajs]


# ---------------------------------------------------------------------------
# Scenario 1: Single-trajectory cycle
# ---------------------------------------------------------------------------


def test_single_trajectory_cycle_is_warning_not_violation(temp_repo: Path) -> None:
    """Cycles 1-2 complete; cycle 3 has only T1 so far (T2-T5 max_slot=2).

    T2-T5 haven't reached slot 3 yet — no trajectory has proved it skipped
    cycle 3 — so cycle 3 is in-progress → WARNING not VIOLATION.
    """
    mints = (
        _full_cycle(1)
        + _full_cycle(2)
        + [{"trajectory": "T1", "slot": 3, "amount": 22}]  # T2-T5 still at slot 2
    )
    _write_mints(temp_repo, mints)

    result = run_check(temp_repo)

    assert result["status"] == "PASS", f"expected PASS, got: {json.dumps(result)}"
    assert result["violations"] == [], "no trajectory proved it skipped cycle 3"
    assert len(result["warnings"]) == 1
    w = result["warnings"][0]
    assert w["cycle"] == 3
    assert "T2" in w["missing"]
    assert "T3" in w["missing"]
    assert "T4" in w["missing"]
    assert "T5" in w["missing"]
    assert result["summary"]["in_progress_cycle"] == 3


# ---------------------------------------------------------------------------
# Scenario 2: All-but-one cycle (exactly 1 of 5 missing)
# ---------------------------------------------------------------------------


def test_all_but_one_trajectory_is_violation(temp_repo: Path) -> None:
    """T1-T5 mint slots 1-4 completely; in slot 5 T5 is absent while T1-T4 mint it;
    T5 then mints slot 6 — proving it jumped over slot 5.

    Exactly 1 trajectory (T5) skipped slot 5 → VIOLATION at cycle 5.
    """
    mints = (
        _full_cycle(1)
        + _full_cycle(2)
        + _full_cycle(3)
        + _full_cycle(4)
        + _full_cycle(5, ["T1", "T2", "T3", "T4"])  # T5 absent at slot 5
        + [{"trajectory": "T5", "slot": 6, "amount": 25}]  # T5 proves it passed slot 5
    )
    _write_mints(temp_repo, mints)

    result = run_check(temp_repo)

    assert result["status"] == "FAIL", f"expected FAIL, got: {json.dumps(result)}"
    violated_cycles = {v["cycle"] for v in result["violations"]}
    assert 5 in violated_cycles, f"cycle 5 gap not detected: {result['violations']}"
    v5 = next(v for v in result["violations"] if v["cycle"] == 5)
    assert "T5" in v5["missing"]
    assert "T5" in v5["skipped_by"]
    assert result["summary"]["total_violations"] >= 1


# ---------------------------------------------------------------------------
# Scenario 3: Slot gap in one trajectory
# ---------------------------------------------------------------------------


def test_slot_gap_in_one_trajectory_is_violation(temp_repo: Path) -> None:
    """T1 mints slots 30, 31, 33 (skips 32); T2-T5 mint 30-33 without gaps.

    T1's slot 33 proves it passed cycle 32 without minting it → VIOLATION at cycle 32.
    """
    t1_slots = [30, 31, 33]  # deliberately omits 32
    other_slots = [30, 31, 32, 33]

    mints: list[dict] = []
    for s in t1_slots:
        mints.append({"trajectory": "T1", "slot": s, "amount": 19 + s})
    for traj in ["T2", "T3", "T4", "T5"]:
        for s in other_slots:
            mints.append({"trajectory": traj, "slot": s, "amount": 19 + s})

    _write_mints(temp_repo, mints)

    result = run_check(temp_repo)

    assert result["status"] == "FAIL", f"expected FAIL, got: {json.dumps(result)}"
    violated_cycles = {v["cycle"] for v in result["violations"]}
    assert 32 in violated_cycles, f"cycle 32 gap not detected: {result['violations']}"
    v32 = next(v for v in result["violations"] if v["cycle"] == 32)
    assert "T1" in v32["skipped_by"]
    assert "T1" in v32["missing"]


# ---------------------------------------------------------------------------
# Scenario 4: Highest-cycle in-progress boundary
# ---------------------------------------------------------------------------


def test_max_cycle_incomplete_is_warning_earlier_gap_is_violation(
    temp_repo: Path,
) -> None:
    """Two-part boundary: earlier gap triggers VIOLATION; max cycle is WARNING.

    Cycles 1-2: complete.
    Cycle 3: T2 absent (T2 has slot 4, proving it skipped cycle 3) → VIOLATION.
    Cycle 4 (max): T3 absent (T3 max_slot=3, hasn't reached slot 4 yet) → WARNING.
    """
    mints = (
        _full_cycle(1)  # complete
        + _full_cycle(2)  # complete
        # Cycle 3: T1,T3,T4,T5 present; T2 absent
        + _full_cycle(3, ["T1", "T3", "T4", "T5"])
        # T2 proves it passed cycle 3 by minting cycle 4
        + [{"trajectory": "T2", "slot": 4, "amount": 23}]
        # Cycle 4 (max): T1,T2,T4,T5 present; T3 absent (T3 max_slot=3, not >4)
        + _full_cycle(4, ["T1", "T2", "T4", "T5"])
    )
    _write_mints(temp_repo, mints)

    result = run_check(temp_repo)

    # Earlier gap (cycle 3, T2 skipped) must be a VIOLATION
    assert result["status"] == "FAIL", f"expected FAIL: {json.dumps(result)}"
    violated_cycles = {v["cycle"] for v in result["violations"]}
    assert 3 in violated_cycles, "cycle 3 gap (T2 skipped) must be a violation"
    v3 = next(v for v in result["violations"] if v["cycle"] == 3)
    assert "T2" in v3["skipped_by"]

    # Max cycle (4, T3 not yet arrived) must be a WARNING not a VIOLATION
    warn_cycles = {w["cycle"] for w in result["warnings"]}
    assert 4 in warn_cycles, "cycle 4 (in-progress, T3 not yet here) must be a warning"
    assert 4 not in violated_cycles, "cycle 4 must not appear as a violation"

    w4 = next(w for w in result["warnings"] if w["cycle"] == 4)
    assert "T3" in w4["missing"]
    assert result["summary"]["in_progress_cycle"] == 4


# ---------------------------------------------------------------------------
# Scenario 5: T6 present, T1-T5 all absent
# ---------------------------------------------------------------------------


def test_t6_only_mint_does_not_flag(temp_repo: Path) -> None:
    """T6 mints slots 1, 2, 3; T1-T5 have no mints at all.

    T6 is excluded from completeness requirements — cycle_map stays empty → PASS.
    """
    mints = [
        {"trajectory": "T6", "slot": 1, "amount": 20},
        {"trajectory": "T6", "slot": 2, "amount": 21},
        {"trajectory": "T6", "slot": 3, "amount": 22},
    ]
    _write_mints(temp_repo, mints)

    result = run_check(temp_repo)

    assert result["status"] == "PASS", f"expected PASS, got: {json.dumps(result)}"
    assert result["violations"] == []
    assert result["warnings"] == []
    assert result["summary"]["total_cycles_checked"] == 0, (
        "T6 slots must not contribute to cycle_map"
    )


# ---------------------------------------------------------------------------
# Scenario 6: Empty trajectory_mints.json
# ---------------------------------------------------------------------------


def test_empty_mints_passes_with_zero_cycles(temp_repo: Path) -> None:
    """No mints in trajectory_mints.json → PASS, nothing to verify."""
    _write_mints(temp_repo, [])

    result = run_check(temp_repo)

    assert result["status"] == "PASS"
    assert result["violations"] == []
    assert result["warnings"] == []
    assert result["summary"]["total_cycles_checked"] == 0
    assert result["summary"]["complete_cycles"] == 0
    assert result["summary"]["total_violations"] == 0


# ---------------------------------------------------------------------------
# Scenario 7: Single complete cycle
# ---------------------------------------------------------------------------


def test_single_complete_cycle_passes(temp_repo: Path) -> None:
    """T1-T5 all mint slot 1, nothing else.

    One complete cycle → PASS, complete_cycles=1, no warnings.
    """
    mints = _full_cycle(1)
    _write_mints(temp_repo, mints)

    result = run_check(temp_repo)

    assert result["status"] == "PASS", f"expected PASS, got: {json.dumps(result)}"
    assert result["violations"] == []
    assert result["warnings"] == []
    assert result["summary"]["complete_cycles"] == 1
    assert result["summary"]["total_violations"] == 0
    assert result["summary"]["in_progress_cycle"] is None
