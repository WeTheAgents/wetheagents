"""Tests for scripts/check_trajectory_mint_consistency.py."""

import json
import sys
from pathlib import Path

import pytest

# Make the script importable
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from check_trajectory_mint_consistency import (
    check_bidirectional_match,
    check_next_slot,
    check_per_agent_sums,
    check_per_trajectory_total_minted,
    check_total_minted,
    run_checks,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_ledger(tmp_path: Path, events: list[dict], mints_data: dict) -> Path:
    """Write a minimal fake ledger under tmp_path and return tmp_path."""
    history_dir = tmp_path / "ledger" / "history"
    history_dir.mkdir(parents=True)
    with (history_dir / "2026-01-01.jsonl").open("w") as fh:
        for ev in events:
            fh.write(json.dumps(ev) + "\n")
    with (tmp_path / "ledger" / "trajectory_mints.json").open("w") as fh:
        json.dump(mints_data, fh)
    return tmp_path


def _event(trajectory: str, slot: int, amount: int, agents: list[str] | None = None, per_agent: list[int] | None = None) -> dict:
    if agents is None:
        agents = ["agent-x@claude"]
    if per_agent is None:
        per_agent = [amount]
    return {
        "type": "trajectory_mint",
        "trajectory": trajectory,
        "slot": slot,
        "amount": amount,
        "agents": agents,
        "per_agent": per_agent,
        "issue": 100 + slot,
        "timestamp": "2026-01-01T00:00:00Z",
    }


def _mint(trajectory: str, slot: int, amount: int, agents: list[str] | None = None, per_agent: list[int] | None = None) -> dict:
    if agents is None:
        agents = ["agent-x@claude"]
    if per_agent is None:
        per_agent = [amount]
    return {
        "trajectory": trajectory,
        "slot": slot,
        "amount": amount,
        "agents": agents,
        "per_agent": per_agent,
        "issue_or_pr": f"#{100 + slot}",
        "idem_key": f"trajectory_mint|{trajectory}|{slot}",
    }


def _clean_ledger_data() -> tuple[list[dict], dict]:
    """A minimal consistent ledger: T1 slot 1, T2 slot 1."""
    events = [
        _event("T1", 1, 20),
        _event("T2", 1, 20),
    ]
    mints_data = {
        "version": 1,
        "total_minted": 40,
        "trajectories": {
            "T1": {"name": "State Integrity", "next_slot": 2, "total_minted": 20},
            "T2": {"name": "Verification", "next_slot": 2, "total_minted": 20},
        },
        "mints": [_mint("T1", 1, 20), _mint("T2", 1, 20)],
    }
    return events, mints_data


# ---------------------------------------------------------------------------
# Test 1: clean synthetic ledger passes
# ---------------------------------------------------------------------------


def test_clean_synthetic_ledger_passes(tmp_path: Path) -> None:
    events, mints_data = _clean_ledger_data()
    root = make_ledger(tmp_path, events, mints_data)
    ok, errors = run_checks(root)
    assert ok, f"Expected PASS but got errors: {errors}"
    assert errors == []


# ---------------------------------------------------------------------------
# Test 2: orphan history event detected
# ---------------------------------------------------------------------------


def test_orphan_history_event(tmp_path: Path) -> None:
    events, mints_data = _clean_ledger_data()
    # Add extra history event with no matching mints entry
    events.append(_event("T3", 1, 20))
    root = make_ledger(tmp_path, events, mints_data)
    ok, errors = run_checks(root)
    assert not ok
    assert any("orphan history event" in e and "T3" in e and "slot 1" in e for e in errors), errors


# ---------------------------------------------------------------------------
# Test 3: orphan mints entry detected
# ---------------------------------------------------------------------------


def test_orphan_mints_entry(tmp_path: Path) -> None:
    events, mints_data = _clean_ledger_data()
    # Add extra mints entry with no matching history event
    mints_data["mints"].append(_mint("T3", 1, 20))
    root = make_ledger(tmp_path, events, mints_data)
    ok, errors = run_checks(root)
    assert not ok
    assert any("orphan mints entry" in e and "T3" in e and "slot 1" in e for e in errors), errors


# ---------------------------------------------------------------------------
# Test 4: total_minted wrong
# ---------------------------------------------------------------------------


def test_total_minted_wrong(tmp_path: Path) -> None:
    events, mints_data = _clean_ledger_data()
    mints_data["total_minted"] = 999  # should be 40
    root = make_ledger(tmp_path, events, mints_data)
    ok, errors = run_checks(root)
    assert not ok
    assert any("total_minted mismatch" in e for e in errors), errors


# ---------------------------------------------------------------------------
# Test 5: slot gap in trajectory
# ---------------------------------------------------------------------------


def test_slot_gap(tmp_path: Path) -> None:
    # T1 has slot 1 and slot 3, skipping slot 2
    events = [_event("T1", 1, 20), _event("T1", 3, 22)]
    mints_data = {
        "version": 1,
        "total_minted": 42,
        "trajectories": {
            "T1": {"name": "State Integrity", "next_slot": 4, "total_minted": 42},
        },
        "mints": [_mint("T1", 1, 20), _mint("T1", 3, 22)],
    }
    root = make_ledger(tmp_path, events, mints_data)
    ok, errors = run_checks(root)
    assert not ok
    assert any("slot gap" in e and "T1" in e for e in errors), errors


# ---------------------------------------------------------------------------
# Test 6: per_agent sum mismatch
# ---------------------------------------------------------------------------


def test_per_agent_sum_wrong(tmp_path: Path) -> None:
    events, mints_data = _clean_ledger_data()
    # Corrupt per_agent so it doesn't sum to amount
    mints_data["mints"][0]["per_agent"] = [15]  # should be [20] for amount=20
    root = make_ledger(tmp_path, events, mints_data)
    ok, errors = run_checks(root)
    assert not ok
    assert any("per_agent sum mismatch" in e and "T1" in e and "slot 1" in e for e in errors), errors


# ---------------------------------------------------------------------------
# Test 7: next_slot declared wrong
# ---------------------------------------------------------------------------


def test_next_slot_wrong(tmp_path: Path) -> None:
    events, mints_data = _clean_ledger_data()
    # T1 has 1 mint (slot 1) so next_slot should be 2, declare 5 instead
    mints_data["trajectories"]["T1"]["next_slot"] = 5
    root = make_ledger(tmp_path, events, mints_data)
    ok, errors = run_checks(root)
    assert not ok
    assert any("next_slot wrong" in e and "T1" in e for e in errors), errors


# ---------------------------------------------------------------------------
# Test 8: amount mismatch between history event and mints entry
# ---------------------------------------------------------------------------


def test_amount_mismatch_history_vs_mints(tmp_path: Path) -> None:
    events, mints_data = _clean_ledger_data()
    # History says T1 slot 1 = 20, but mints says 25
    mints_data["mints"][0]["amount"] = 25
    mints_data["mints"][0]["per_agent"] = [25]
    root = make_ledger(tmp_path, events, mints_data)
    ok, errors = run_checks(root)
    assert not ok
    assert any("amount mismatch" in e and "T1" in e and "slot 1" in e for e in errors), errors


# ---------------------------------------------------------------------------
# Test 9: multi-agent per_agent sums correctly
# ---------------------------------------------------------------------------


def test_multi_agent_per_agent_correct(tmp_path: Path) -> None:
    events = [_event("T3", 1, 20, agents=["a@claude", "b@claude"], per_agent=[10, 10])]
    mints_data = {
        "version": 1,
        "total_minted": 20,
        "trajectories": {
            "T3": {"name": "Safety", "next_slot": 2, "total_minted": 20},
        },
        "mints": [_mint("T3", 1, 20, agents=["a@claude", "b@claude"], per_agent=[10, 10])],
    }
    root = make_ledger(tmp_path, events, mints_data)
    ok, errors = run_checks(root)
    assert ok, f"Expected PASS but got errors: {errors}"


# ---------------------------------------------------------------------------
# Test 11: per-trajectory total_minted wrong
# ---------------------------------------------------------------------------


def test_per_trajectory_total_minted_wrong(tmp_path: Path) -> None:
    events, mints_data = _clean_ledger_data()
    # T1 has one mint of 20, but we declare total_minted=99
    mints_data["trajectories"]["T1"]["total_minted"] = 99
    root = make_ledger(tmp_path, events, mints_data)
    ok, errors = run_checks(root)
    assert not ok
    assert any("per-trajectory total_minted wrong" in e and "T1" in e for e in errors), errors


# ---------------------------------------------------------------------------
# Test 10: real ledger integration test
# ---------------------------------------------------------------------------


def test_real_ledger_passes() -> None:
    """The current real ledger must pass all checks."""
    root = Path(__file__).parent.parent
    ok, errors = run_checks(root)
    assert ok, f"Real ledger has inconsistencies:\n" + "\n".join(errors)
