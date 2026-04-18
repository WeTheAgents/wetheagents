"""Tests for scripts/check_trajectory_slot_uniqueness.py."""

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
    """Write a minimal fake ledger under tmp_path and return the root."""
    history_dir = tmp_path / "ledger" / "history"
    history_dir.mkdir(parents=True)
    with (history_dir / "2026-01-01.jsonl").open("w") as fh:
        for ev in events:
            fh.write(json.dumps(ev) + "\n")
    mints_data = {
        "version": 1,
        "total_minted": sum(ev.get("amount", 0) for ev in events),
        "trajectories": trajectories,
        "mints": [],
    }
    with (tmp_path / "ledger" / "trajectory_mints.json").open("w") as fh:
        json.dump(mints_data, fh)
    return tmp_path


def mint_event(trajectory: str, slot: int, amount: int = 20) -> dict:
    return {
        "type": "trajectory_mint",
        "trajectory": trajectory,
        "slot": slot,
        "amount": amount,
        "agents": ["agent-x@claude"],
        "per_agent": [amount],
        "issue": 100 + slot,
        "timestamp": "2026-01-01T00:00:00Z",
    }


def traj_info(next_slot: int, total_minted: int = 0) -> dict:
    return {"name": "Test Trajectory", "next_slot": next_slot, "total_minted": total_minted}


# ---------------------------------------------------------------------------
# Test 1: all-clean PASS — no duplicates, next_slot correct
# ---------------------------------------------------------------------------


def test_all_clean_pass(tmp_path: Path) -> None:
    events = [mint_event("T1", 1), mint_event("T1", 2), mint_event("T2", 1)]
    trajectories = {
        "T1": traj_info(next_slot=3, total_minted=40),
        "T2": traj_info(next_slot=2, total_minted=20),
    }
    root = make_ledger(tmp_path, events, trajectories)
    payload = run_check(root)
    assert payload["status"] == "PASS"
    assert payload["double_mints"] == []
    assert payload["next_slot_drift"] == []


# ---------------------------------------------------------------------------
# Test 2: one trajectory with a slot appearing twice — FAIL
# ---------------------------------------------------------------------------


def test_single_double_mint_fail(tmp_path: Path) -> None:
    events = [
        mint_event("T1", 1),
        mint_event("T1", 2),
        mint_event("T1", 2),  # duplicate!
    ]
    trajectories = {"T1": traj_info(next_slot=3, total_minted=60)}
    root = make_ledger(tmp_path, events, trajectories)
    payload = run_check(root)
    assert payload["status"] == "FAIL"
    assert len(payload["double_mints"]) == 1
    dm = payload["double_mints"][0]
    assert dm["trajectory"] == "T1"
    assert dm["slot"] == 2
    assert dm["count"] == 2


# ---------------------------------------------------------------------------
# Test 3: two trajectories each with a duplicate — FAIL with both reported
# ---------------------------------------------------------------------------


def test_two_trajectories_with_duplicates(tmp_path: Path) -> None:
    events = [
        mint_event("T1", 1),
        mint_event("T1", 1),  # duplicate
        mint_event("T2", 3),
        mint_event("T2", 3),  # duplicate
    ]
    trajectories = {
        "T1": traj_info(next_slot=2, total_minted=40),
        "T2": traj_info(next_slot=4, total_minted=40),
    }
    root = make_ledger(tmp_path, events, trajectories)
    payload = run_check(root)
    assert payload["status"] == "FAIL"
    assert len(payload["double_mints"]) == 2
    trajs = {d["trajectory"] for d in payload["double_mints"]}
    assert trajs == {"T1", "T2"}


# ---------------------------------------------------------------------------
# Test 4: next_slot too high (skipped slot) — FAIL
# history has max slot 3 but next_slot declared as 6
# ---------------------------------------------------------------------------


def test_next_slot_too_high(tmp_path: Path) -> None:
    events = [mint_event("T1", 1), mint_event("T1", 2), mint_event("T1", 3)]
    trajectories = {"T1": traj_info(next_slot=6, total_minted=60)}  # should be 4
    root = make_ledger(tmp_path, events, trajectories)
    payload = run_check(root)
    assert payload["status"] == "FAIL"
    assert len(payload["next_slot_drift"]) == 1
    drift = payload["next_slot_drift"][0]
    assert drift["trajectory"] == "T1"
    assert drift["history_max_slot"] == 3
    assert drift["expected_next_slot"] == 4
    assert drift["declared_next_slot"] == 6


# ---------------------------------------------------------------------------
# Test 5: next_slot too low (over-incremented / stale) — FAIL
# history has max slot 4 but next_slot declared as 3
# ---------------------------------------------------------------------------


def test_next_slot_too_low(tmp_path: Path) -> None:
    events = [
        mint_event("T2", 1),
        mint_event("T2", 2),
        mint_event("T2", 3),
        mint_event("T2", 4),
    ]
    trajectories = {"T2": traj_info(next_slot=3, total_minted=80)}  # should be 5
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
# Test 6: trajectory with no history events, next_slot=1 — PASS
# ---------------------------------------------------------------------------


def test_no_history_next_slot_one_pass(tmp_path: Path) -> None:
    events: list[dict] = []
    trajectories = {
        "T1": traj_info(next_slot=1, total_minted=0),
        "T2": traj_info(next_slot=1, total_minted=0),
    }
    root = make_ledger(tmp_path, events, trajectories)
    payload = run_check(root)
    assert payload["status"] == "PASS"
    assert payload["double_mints"] == []
    assert payload["next_slot_drift"] == []


# ---------------------------------------------------------------------------
# Test 7: empty history, all trajectories have next_slot=1 — PASS
# ---------------------------------------------------------------------------


def test_empty_history_all_pass(tmp_path: Path) -> None:
    events: list[dict] = []
    trajectories = {
        "T1": traj_info(next_slot=1),
        "T2": traj_info(next_slot=1),
        "T3": traj_info(next_slot=1),
        "T4": traj_info(next_slot=1),
        "T5": traj_info(next_slot=1),
        "T6": traj_info(next_slot=1),
    }
    root = make_ledger(tmp_path, events, trajectories)
    payload = run_check(root)
    assert payload["status"] == "PASS"
    assert payload["double_mints"] == []
    assert payload["next_slot_drift"] == []


# ---------------------------------------------------------------------------
# Test 8: missing trajectory key in trajectory_mints.json — FAIL
# history has events for T9 but trajectory_mints.json doesn't include it
# ---------------------------------------------------------------------------


def test_missing_trajectory_mints_key(tmp_path: Path) -> None:
    events = [mint_event("T1", 1), mint_event("T9", 1), mint_event("T9", 2)]
    # T9 is absent from trajectories dict
    trajectories = {"T1": traj_info(next_slot=2, total_minted=20)}
    root = make_ledger(tmp_path, events, trajectories)
    payload = run_check(root)
    assert payload["status"] == "FAIL"
    drift_trajs = {d["trajectory"] for d in payload["next_slot_drift"]}
    assert "T9" in drift_trajs
    t9_drift = next(d for d in payload["next_slot_drift"] if d["trajectory"] == "T9")
    assert t9_drift["declared_next_slot"] is None
    assert t9_drift["expected_next_slot"] == 3


# ---------------------------------------------------------------------------
# Test 9: next_slot matches exactly — PASS
# Explicit check that correct next_slot emits nothing
# ---------------------------------------------------------------------------


def test_next_slot_matches_exactly_pass(tmp_path: Path) -> None:
    events = [mint_event("T3", 1), mint_event("T3", 2), mint_event("T3", 3)]
    trajectories = {"T3": traj_info(next_slot=4, total_minted=60)}
    root = make_ledger(tmp_path, events, trajectories)
    payload = run_check(root)
    assert payload["status"] == "PASS"
    assert payload["next_slot_drift"] == []


# ---------------------------------------------------------------------------
# Test 10: mixed pass/fail across trajectories — only failures reported
# ---------------------------------------------------------------------------


def test_mixed_pass_fail_across_trajectories(tmp_path: Path) -> None:
    events = [
        mint_event("T1", 1),
        mint_event("T1", 2),  # T1 fine: max=2, expect next_slot=3
        mint_event("T2", 1),
        mint_event("T2", 1),  # T2 has double-mint at slot 1
        mint_event("T3", 1),  # T3 fine: max=1, expect next_slot=2
    ]
    trajectories = {
        "T1": traj_info(next_slot=3, total_minted=40),  # correct
        "T2": traj_info(next_slot=2, total_minted=40),  # correct (despite duplicate)
        "T3": traj_info(next_slot=5, total_minted=20),  # drift: expected 2, got 5
    }
    root = make_ledger(tmp_path, events, trajectories)
    payload = run_check(root)
    assert payload["status"] == "FAIL"
    # Only T2 in double_mints
    assert len(payload["double_mints"]) == 1
    assert payload["double_mints"][0]["trajectory"] == "T2"
    # Only T3 in next_slot_drift
    assert len(payload["next_slot_drift"]) == 1
    assert payload["next_slot_drift"][0]["trajectory"] == "T3"


# ---------------------------------------------------------------------------
# Test 11: double-mint AND next_slot drift simultaneously — both lists populated
# ---------------------------------------------------------------------------


def test_double_mint_and_drift_simultaneously(tmp_path: Path) -> None:
    events = [
        mint_event("T1", 2),
        mint_event("T1", 2),  # double-mint
    ]
    # max slot from history = 2, so expected next_slot = 3, but we declare 10
    trajectories = {"T1": traj_info(next_slot=10, total_minted=40)}
    root = make_ledger(tmp_path, events, trajectories)
    payload = run_check(root)
    assert payload["status"] == "FAIL"
    assert len(payload["double_mints"]) == 1
    assert payload["double_mints"][0]["slot"] == 2
    assert len(payload["next_slot_drift"]) == 1
    assert payload["next_slot_drift"][0]["declared_next_slot"] == 10


# ---------------------------------------------------------------------------
# Test 12: trajectory with no history events but next_slot != 1 — FAIL
# ---------------------------------------------------------------------------


def test_no_history_next_slot_wrong(tmp_path: Path) -> None:
    events: list[dict] = []
    trajectories = {"T5": traj_info(next_slot=5, total_minted=0)}  # should be 1
    root = make_ledger(tmp_path, events, trajectories)
    payload = run_check(root)
    assert payload["status"] == "FAIL"
    assert len(payload["next_slot_drift"]) == 1
    drift = payload["next_slot_drift"][0]
    assert drift["trajectory"] == "T5"
    assert drift["history_max_slot"] is None
    assert drift["expected_next_slot"] == 1
    assert drift["declared_next_slot"] == 5


# ---------------------------------------------------------------------------
# Test 13: multiple slots, all unique, max tracked correctly — PASS
# ---------------------------------------------------------------------------


def test_multiple_slots_all_unique_pass(tmp_path: Path) -> None:
    events = [
        mint_event("T6", 1, 20),
        mint_event("T6", 2, 21),
        mint_event("T6", 3, 22),
        mint_event("T6", 4, 23),
        mint_event("T6", 5, 24),
    ]
    trajectories = {"T6": traj_info(next_slot=6, total_minted=110)}
    root = make_ledger(tmp_path, events, trajectories)
    payload = run_check(root)
    assert payload["status"] == "PASS"
    assert payload["double_mints"] == []
    assert payload["next_slot_drift"] == []


# ---------------------------------------------------------------------------
# Test 14: triple-mint (same slot three times) — count reported correctly
# ---------------------------------------------------------------------------


def test_triple_mint_count_correct(tmp_path: Path) -> None:
    events = [
        mint_event("T4", 7),
        mint_event("T4", 7),
        mint_event("T4", 7),  # 3x same slot
    ]
    trajectories = {"T4": traj_info(next_slot=8, total_minted=60)}
    root = make_ledger(tmp_path, events, trajectories)
    payload = run_check(root)
    assert payload["status"] == "FAIL"
    assert len(payload["double_mints"]) == 1
    assert payload["double_mints"][0]["count"] == 3


# ---------------------------------------------------------------------------
# Test 15: real ledger integration — current ledger must PASS
# ---------------------------------------------------------------------------


def test_real_ledger_passes() -> None:
    root = Path(__file__).parent.parent
    payload = run_check(root)
    assert payload["status"] == "PASS", (
        "Real ledger has slot uniqueness violations:\n"
        + json.dumps(payload, indent=2)
    )
