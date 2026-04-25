"""Tests for scripts/check_trajectory_next_slot_consistency.py."""

import json
import shutil
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from check_trajectory_next_slot_consistency import NO_MINT_NEXT_SLOT, run_check


def make_ledger(tmp_path: Path, events: list[dict], trajectories: dict) -> Path:
    """Write a tiny ledger fixture and return repository root path."""
    history_dir = tmp_path / "ledger" / "history"
    history_dir.mkdir(parents=True)
    with (history_dir / "2026-01-01.jsonl").open("w") as fh:
        for ev in events:
            fh.write(json.dumps(ev) + "\n")

    with (tmp_path / "ledger" / "trajectory_mints.json").open("w") as fh:
        payload = {
            "version": 1,
            "total_minted": 0,
            "trajectories": trajectories,
            "mints": [],
        }
        json.dump(payload, fh)

    return tmp_path


def make_tmp_root() -> Path:
    """Build an isolated temporary root under the local writable temp folder."""
    base = Path(r"C:/Users/peach/AppData/Local/Temp/pytest_local_tmp_cx19")
    base.mkdir(exist_ok=True)
    root = base / f"next-slot-check-{uuid.uuid4().hex}"
    root.mkdir()
    return root


def mint_event(trajectory: str, slot: int, amount: int = 20) -> dict:
    """Build a minimal trajectory_mint event."""
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


def trajectory_info(next_slot: int) -> dict:
    return {"name": "T", "next_slot": next_slot, "total_minted": 0}


def full_trajectory_map(next_slot: int = NO_MINT_NEXT_SLOT) -> dict:
    """Build a full T1-T6 trajectory map with the same next_slot value."""
    return {f"T{i}": trajectory_info(next_slot=next_slot) for i in range(1, 7)}


def test_consistent_state_passes() -> None:
    tmp_root = make_tmp_root()
    events = [mint_event("T1", 1), mint_event("T1", 2), mint_event("T2", 1)]
    trajectories = full_trajectory_map()
    trajectories.update({"T1": trajectory_info(3), "T2": trajectory_info(2)})
    try:
        root = make_ledger(tmp_root, events, trajectories)
        payload = run_check(root)
        assert payload["status"] == "PASS"
        assert payload["duplicate_slots"] == []
        assert payload["next_slot_violations"] == []
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


def test_next_slot_too_low_fails() -> None:
    tmp_root = make_tmp_root()
    events = [mint_event("T1", 1), mint_event("T1", 2)]
    trajectories = full_trajectory_map(next_slot=NO_MINT_NEXT_SLOT)
    trajectories["T1"] = trajectory_info(2)  # should be 3
    try:
        root = make_ledger(tmp_root, events, trajectories)
        payload = run_check(root)
        assert payload["status"] == "FAIL"
        assert len(payload["next_slot_violations"]) == 1
        drift = payload["next_slot_violations"][0]
        assert drift["trajectory"] == "T1"
        assert drift["history_max_slot"] == 2
        assert drift["expected_next_slot"] == 3
        assert drift["declared_next_slot"] == 2
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


def test_next_slot_too_high_fails() -> None:
    tmp_root = make_tmp_root()
    events = [mint_event("T1", 1), mint_event("T1", 2), mint_event("T1", 3)]
    trajectories = full_trajectory_map(next_slot=NO_MINT_NEXT_SLOT)
    trajectories["T1"] = trajectory_info(6)  # should be 4
    try:
        root = make_ledger(tmp_root, events, trajectories)
        payload = run_check(root)
        assert payload["status"] == "FAIL"
        assert len(payload["next_slot_violations"]) == 1
        drift = payload["next_slot_violations"][0]
        assert drift["trajectory"] == "T1"
        assert drift["history_max_slot"] == 3
        assert drift["expected_next_slot"] == 4
        assert drift["declared_next_slot"] == 6
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


def test_no_history_is_pass_for_next_slot_twenty() -> None:
    tmp_root = make_tmp_root()
    events: list[dict] = []
    trajectories = full_trajectory_map(next_slot=NO_MINT_NEXT_SLOT)
    try:
        root = make_ledger(tmp_root, events, trajectories)
        payload = run_check(root)
        assert payload["status"] == "PASS"
        assert payload["duplicate_slots"] == []
        assert payload["next_slot_violations"] == []
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


def test_duplicate_slot_fails() -> None:
    tmp_root = make_tmp_root()
    events = [mint_event("T1", 1), mint_event("T1", 1)]
    trajectories = full_trajectory_map(next_slot=NO_MINT_NEXT_SLOT)
    trajectories["T1"] = trajectory_info(2)  # max slot is 1, so next should be 2
    try:
        root = make_ledger(tmp_root, events, trajectories)
        payload = run_check(root)
        assert payload["status"] == "FAIL"
        assert len(payload["duplicate_slots"]) == 1
        dup = payload["duplicate_slots"][0]
        assert dup["trajectory"] == "T1"
        assert dup["slot"] == 1
        assert dup["count"] == 2
        # next-slot check still consistent; only duplicate is reported here
        assert payload["next_slot_violations"] == []
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)
