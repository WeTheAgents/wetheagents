"""Tests for scripts/check_trajectory_mint_timeline.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from check_trajectory_mint_timeline import (
    find_next_slot_drift,
    find_ordering_violations,
    run_check,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_ledger(
    tmp_path: Path,
    file_events: dict[str, list[dict]],
    trajectories: dict,
) -> Path:
    """Write a fake ledger under tmp_path.

    file_events: mapping of filename (e.g. "2026-01-01.jsonl") to list of events.
    trajectories: the trajectories dict for trajectory_mints.json.
    Returns the repo root (tmp_path).
    """
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


def mint(
    trajectory: str,
    slot: int,
    amount: int = 20,
    timestamp: str = "2026-01-01T00:00:00Z",
) -> dict:
    """Build a trajectory_mint event dict."""
    return {
        "type": "trajectory_mint",
        "trajectory": trajectory,
        "slot": slot,
        "amount": amount,
        "agents": ["agent-x@claude"],
        "per_agent": [amount],
        "issue": 100 + slot,
        "timestamp": timestamp,
    }


def traj(next_slot: int) -> dict:
    """Build a minimal trajectory entry for trajectory_mints.json."""
    return {"name": "Test Trajectory", "next_slot": next_slot, "total_minted": 0}


# ---------------------------------------------------------------------------
# find_ordering_violations — unit tests
# ---------------------------------------------------------------------------


def _with_meta(events: list[dict], fname: str = "2026-01-01.jsonl") -> list[dict]:
    """Inject _file and _line metadata as the script would."""
    result = []
    for i, ev in enumerate(events):
        copy = dict(ev)
        copy["_file"] = fname
        copy["_line"] = i + 1
        result.append(copy)
    return result


def test_ordering_clean_single_trajectory() -> None:
    events = _with_meta([mint("T1", 1), mint("T1", 2), mint("T1", 3)])
    assert find_ordering_violations(events) == []


def test_ordering_clean_multiple_trajectories() -> None:
    events = _with_meta(
        [mint("T1", 1), mint("T2", 1), mint("T1", 2), mint("T2", 2), mint("T1", 3)]
    )
    assert find_ordering_violations(events) == []


def test_ordering_violation_same_file() -> None:
    """Slot 3 then slot 2 for same trajectory in the same file."""
    events = _with_meta([mint("T1", 1), mint("T1", 3), mint("T1", 2)])
    violations = find_ordering_violations(events)
    assert len(violations) == 1
    v = violations[0]
    assert v["trajectory"] == "T1"
    assert v["slot"] == 2
    assert v["prev_slot"] == 3


def test_ordering_duplicate_slot_same_file() -> None:
    """Duplicate slot (5, 5) is a violation — not strictly increasing."""
    events = _with_meta([mint("T1", 5), mint("T1", 5)])
    violations = find_ordering_violations(events)
    assert len(violations) == 1
    assert violations[0]["slot"] == 5
    assert violations[0]["prev_slot"] == 5


def test_ordering_violation_across_files() -> None:
    """Slot 5 in an earlier file, slot 3 in a later file — out of order."""
    file1_events = _with_meta([mint("T1", 5)], fname="2026-01-01.jsonl")
    file2_events = _with_meta([mint("T1", 3)], fname="2026-01-02.jsonl")
    for ev in file2_events:
        ev["_line"] = 1
    violations = find_ordering_violations(file1_events + file2_events)
    assert len(violations) == 1
    assert violations[0]["slot"] == 3
    assert violations[0]["prev_slot"] == 5


def test_ordering_only_one_trajectory_violated() -> None:
    """T1 is clean, T2 has an out-of-order mint."""
    events = _with_meta(
        [mint("T1", 1), mint("T1", 2), mint("T2", 3), mint("T2", 1)]
    )
    violations = find_ordering_violations(events)
    assert len(violations) == 1
    assert violations[0]["trajectory"] == "T2"


def test_ordering_empty_stream() -> None:
    assert find_ordering_violations([]) == []


def test_ordering_single_event_per_trajectory() -> None:
    events = _with_meta([mint("T1", 7), mint("T2", 3), mint("T3", 1)])
    assert find_ordering_violations(events) == []


def test_ordering_non_mint_events_ignored() -> None:
    """Events with type != trajectory_mint have no _file/_line — make sure
    the loader (not find_ordering_violations) filters them, but the function
    itself handles missing trajectory/slot gracefully."""
    events = [
        {"type": "pay", "trajectory": "T1", "slot": 99, "_file": "f.jsonl", "_line": 1},
        {"type": "trajectory_mint", "trajectory": "T1", "slot": 1, "_file": "f.jsonl", "_line": 2},
    ]
    # pay event has no trajectory_mint type — the loader already filtered it,
    # but if it slips through, trajectory/slot are still present and would be
    # treated as a mint event. We test that find_ordering_violations handles
    # events with missing trajectory or slot gracefully.
    incomplete = [
        {"type": "trajectory_mint", "_file": "f.jsonl", "_line": 1},  # missing trajectory
        {"type": "trajectory_mint", "trajectory": "T1", "_file": "f.jsonl", "_line": 2},  # missing slot
    ]
    assert find_ordering_violations(incomplete) == []


def test_ordering_multiple_violations() -> None:
    """Multiple out-of-order events in same trajectory are each reported."""
    events = _with_meta([mint("T1", 5), mint("T1", 3), mint("T1", 2)])
    violations = find_ordering_violations(events)
    # slot 3 violates (after 5), slot 2 violates... but after slot 3 violation
    # we do NOT advance last_seen, so prev stays at 5 for the next check.
    assert len(violations) == 2
    assert violations[0]["slot"] == 3
    assert violations[1]["slot"] == 2


def test_ordering_position_fields_populated() -> None:
    """Violation records must include position and prev_position strings."""
    ev1 = dict(mint("T1", 5))
    ev1["_file"] = "2026-01-01.jsonl"
    ev1["_line"] = 3
    ev2 = dict(mint("T1", 2))
    ev2["_file"] = "2026-01-02.jsonl"
    ev2["_line"] = 7
    violations = find_ordering_violations([ev1, ev2])
    assert len(violations) == 1
    assert violations[0]["position"] == "2026-01-02.jsonl:line 7"
    assert violations[0]["prev_position"] == "2026-01-01.jsonl:line 3"


# ---------------------------------------------------------------------------
# find_next_slot_drift — unit tests
# ---------------------------------------------------------------------------


def test_next_slot_drift_clean() -> None:
    events = _with_meta([mint("T1", 1), mint("T1", 2), mint("T2", 1)])
    trajectories = {"T1": traj(3), "T2": traj(2)}
    assert find_next_slot_drift(events, trajectories) == []


def test_next_slot_drift_declared_too_high() -> None:
    events = _with_meta([mint("T1", 3)])
    trajectories = {"T1": traj(5)}  # declared 5, expected 4
    drift = find_next_slot_drift(events, trajectories)
    assert len(drift) == 1
    assert drift[0]["trajectory"] == "T1"
    assert drift[0]["expected_next_slot"] == 4
    assert drift[0]["declared_next_slot"] == 5


def test_next_slot_drift_declared_too_low() -> None:
    events = _with_meta([mint("T1", 3)])
    trajectories = {"T1": traj(2)}  # declared 2, expected 4
    drift = find_next_slot_drift(events, trajectories)
    assert len(drift) == 1
    assert drift[0]["expected_next_slot"] == 4
    assert drift[0]["declared_next_slot"] == 2


def test_next_slot_drift_trajectory_in_history_missing_from_json() -> None:
    events = _with_meta([mint("T1", 1)])
    trajectories: dict = {}  # T1 not in JSON
    drift = find_next_slot_drift(events, trajectories)
    assert len(drift) == 1
    assert drift[0]["trajectory"] == "T1"
    assert drift[0]["declared_next_slot"] is None


def test_next_slot_drift_trajectory_in_json_no_history() -> None:
    trajectories = {"T1": traj(2)}  # declared 2, but no history → expected 1
    drift = find_next_slot_drift([], trajectories)
    assert len(drift) == 1
    assert drift[0]["expected_next_slot"] == 1
    assert drift[0]["declared_next_slot"] == 2


def test_next_slot_drift_no_history_correct_next_slot() -> None:
    """Trajectory in JSON with next_slot=1 and no history → PASS."""
    trajectories = {"T1": traj(1)}
    assert find_next_slot_drift([], trajectories) == []


def test_next_slot_drift_uses_max_not_last() -> None:
    """If history has slots [1, 3, 2] (out-of-order but unique), max is 3."""
    events = _with_meta([mint("T1", 1), mint("T1", 3), mint("T1", 2)])
    trajectories = {"T1": traj(4)}  # max=3, expected=4
    assert find_next_slot_drift(events, trajectories) == []


# ---------------------------------------------------------------------------
# run_check — integration tests against fake ledger
# ---------------------------------------------------------------------------


def test_run_check_pass_real_ledger_shape(tmp_path: Path) -> None:
    """Clean ledger with two trajectories, multiple files, correct order."""
    file_events = {
        "2026-01-01.jsonl": [mint("T1", 1), mint("T2", 1)],
        "2026-01-02.jsonl": [mint("T1", 2), mint("T2", 2)],
        "2026-01-03.jsonl": [mint("T1", 3)],
    }
    trajectories = {"T1": traj(4), "T2": traj(3)}
    root = make_ledger(tmp_path, file_events, trajectories)
    result = run_check(root)
    assert result["status"] == "PASS"
    assert result["ordering_violations"] == []
    assert result["next_slot_drift"] == []


def test_run_check_fail_retroactive_insert(tmp_path: Path) -> None:
    """Slot 3 recorded in an earlier file after slot 5 was in a later file."""
    file_events = {
        "2026-01-01.jsonl": [mint("T1", 1), mint("T1", 5)],
        "2026-01-02.jsonl": [mint("T1", 3)],  # retroactive insert
    }
    trajectories = {"T1": traj(6)}
    root = make_ledger(tmp_path, file_events, trajectories)
    result = run_check(root)
    assert result["status"] == "FAIL"
    assert len(result["ordering_violations"]) == 1
    assert result["ordering_violations"][0]["slot"] == 3


def test_run_check_fail_duplicate_slot_across_files(tmp_path: Path) -> None:
    """Same slot appears in two different files."""
    file_events = {
        "2026-01-01.jsonl": [mint("T2", 4)],
        "2026-01-02.jsonl": [mint("T2", 4)],
    }
    trajectories = {"T2": traj(5)}
    root = make_ledger(tmp_path, file_events, trajectories)
    result = run_check(root)
    assert result["status"] == "FAIL"
    assert result["ordering_violations"][0]["trajectory"] == "T2"


def test_run_check_fail_next_slot_drift_only(tmp_path: Path) -> None:
    """Ordering is fine but next_slot in JSON is wrong."""
    file_events = {"2026-01-01.jsonl": [mint("T1", 1), mint("T1", 2)]}
    trajectories = {"T1": traj(10)}  # wrong: should be 3
    root = make_ledger(tmp_path, file_events, trajectories)
    result = run_check(root)
    assert result["status"] == "FAIL"
    assert result["ordering_violations"] == []
    assert result["next_slot_drift"][0]["expected_next_slot"] == 3


def test_run_check_non_mint_events_ignored(tmp_path: Path) -> None:
    """Non-trajectory_mint events in JSONL must not affect the check."""
    file_events = {
        "2026-01-01.jsonl": [
            {"type": "pay", "agent": "X", "amount": 10},
            mint("T1", 1),
            {"type": "escrow_create", "issue": 5},
            mint("T1", 2),
        ]
    }
    trajectories = {"T1": traj(3)}
    root = make_ledger(tmp_path, file_events, trajectories)
    result = run_check(root)
    assert result["status"] == "PASS"


def test_run_check_malformed_json_lines_skipped(tmp_path: Path) -> None:
    """Malformed JSON lines must be skipped without crashing."""
    history_dir = tmp_path / "ledger" / "history"
    history_dir.mkdir(parents=True)
    with (history_dir / "2026-01-01.jsonl").open("w") as fh:
        fh.write('{"type": "trajectory_mint", "trajectory": "T1", "slot": 1, "amount": 20, "agents": [], "per_agent": [], "issue": 101, "timestamp": "2026-01-01T00:00:00Z"}\n')
        fh.write("not valid json\n")
        fh.write('{"type": "trajectory_mint", "trajectory": "T1", "slot": 2, "amount": 20, "agents": [], "per_agent": [], "issue": 102, "timestamp": "2026-01-01T00:00:00Z"}\n')
    trajectories = {"T1": traj(3)}
    mints_data = {"version": 1, "total_minted": 0, "trajectories": trajectories, "mints": []}
    with (tmp_path / "ledger" / "trajectory_mints.json").open("w") as fh:
        json.dump(mints_data, fh)
    result = run_check(tmp_path)
    assert result["status"] == "PASS"


def test_run_check_empty_history(tmp_path: Path) -> None:
    """Empty history files, next_slot=1 for all trajectories → PASS."""
    file_events: dict[str, list] = {"2026-01-01.jsonl": []}
    trajectories = {"T1": traj(1), "T2": traj(1)}
    root = make_ledger(tmp_path, file_events, trajectories)
    result = run_check(root)
    assert result["status"] == "PASS"


def test_run_check_files_processed_in_filename_order(tmp_path: Path) -> None:
    """Files with lexicographically earlier names are processed first."""
    # File "b" has slot 3, file "a" has slot 1. Since "a" < "b", order is a→b → clean.
    file_events = {
        "2026-01-01.jsonl": [mint("T1", 1), mint("T1", 2)],
        "2026-01-02.jsonl": [mint("T1", 3)],
    }
    trajectories = {"T1": traj(4)}
    root = make_ledger(tmp_path, file_events, trajectories)
    result = run_check(root)
    assert result["status"] == "PASS"


def test_run_check_fail_both_violations_and_drift(tmp_path: Path) -> None:
    """Both ordering violation and next_slot drift → FAIL with both lists populated."""
    file_events = {
        "2026-01-01.jsonl": [mint("T1", 3), mint("T1", 1)],  # out-of-order
    }
    trajectories = {"T1": traj(10)}  # also wrong next_slot
    root = make_ledger(tmp_path, file_events, trajectories)
    result = run_check(root)
    assert result["status"] == "FAIL"
    assert len(result["ordering_violations"]) >= 1
    assert len(result["next_slot_drift"]) >= 1


def test_run_check_pass_live_repo() -> None:
    """Run against the actual repository — must PASS on a clean ledger."""
    repo_root = Path(__file__).resolve().parent.parent
    result = run_check(repo_root)
    assert result["status"] == "PASS", (
        f"Live repo check failed:\n{json.dumps(result, indent=2)}"
    )
