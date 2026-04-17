from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.check_trajectory_history_sync import (
    _iter_json_objects,
    extract_json_keys,
    load_history_mints,
    load_json_mints,
    run_check,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _mint_event(trajectory: str, slot: int, issue: int = 100) -> str:
    return json.dumps(
        {
            "type": "trajectory_mint",
            "trajectory": trajectory,
            "slot": slot,
            "amount": 20 + slot - 1,
            "agents": ["agent0@system"],
            "per_agent": [20 + slot - 1],
            "issue": issue,
            "timestamp": "2026-03-17T00:00:00Z",
        }
    )


def _base_repo(tmp_path: Path) -> Path:
    """Minimal valid repo with one matching pair."""
    root = tmp_path
    (root / "ledger" / "history").mkdir(parents=True)
    _write_json(
        root / "ledger" / "trajectory_mints.json",
        {
            "mints": [
                {
                    "trajectory": "T1",
                    "slot": 1,
                    "amount": 20,
                    "agents": ["agent0@system"],
                    "per_agent": [20],
                    "issue_or_pr": "#100",
                    "idem_key": "trajectory_mint|T1|1",
                }
            ]
        },
    )
    _write_jsonl(
        root / "ledger" / "history" / "2026-03-17.jsonl",
        [_mint_event("T1", 1, 100)],
    )
    return root


# ---------------------------------------------------------------------------
# _iter_json_objects
# ---------------------------------------------------------------------------


def test_iter_single_object() -> None:
    text = '{"type": "trajectory_mint", "slot": 1}'
    result = _iter_json_objects(text)
    assert len(result) == 1
    assert result[0]["slot"] == 1


def test_iter_concatenated_objects() -> None:
    """Two JSON objects on one line with no separator — real edge case in history."""
    a = json.dumps({"type": "escrow_create", "issue": 10})
    b = json.dumps({"type": "trajectory_mint", "slot": 5})
    result = _iter_json_objects(a + b)
    assert len(result) == 2
    assert result[1]["slot"] == 5


def test_iter_empty_string() -> None:
    assert _iter_json_objects("") == []


def test_iter_whitespace_only() -> None:
    assert _iter_json_objects("   \n  ") == []


# ---------------------------------------------------------------------------
# extract_json_keys
# ---------------------------------------------------------------------------


def test_extract_json_keys_basic() -> None:
    mints = [{"trajectory": "T1", "slot": 1}, {"trajectory": "T2", "slot": 3}]
    assert extract_json_keys(mints) == {("T1", 1), ("T2", 3)}


def test_extract_json_keys_skips_missing_fields() -> None:
    mints = [{"trajectory": "T1"}, {"slot": 2}, {"trajectory": "T3", "slot": 5}]
    assert extract_json_keys(mints) == {("T3", 5)}


def test_extract_json_keys_empty_list() -> None:
    assert extract_json_keys([]) == set()


# ---------------------------------------------------------------------------
# load_history_mints
# ---------------------------------------------------------------------------


def test_load_history_mints_missing_dir(tmp_path: Path) -> None:
    """Non-existent history dir returns empty set — no crash."""
    result = load_history_mints(tmp_path / "does_not_exist")
    assert result == set()


def test_load_history_mints_empty_dir(tmp_path: Path) -> None:
    history = tmp_path / "history"
    history.mkdir()
    assert load_history_mints(history) == set()


def test_load_history_mints_skips_non_mint_events(tmp_path: Path) -> None:
    history = tmp_path / "history"
    history.mkdir()
    _write_jsonl(
        history / "2026-04-01.jsonl",
        [
            json.dumps({"type": "escrow_create", "issue": 1}),
            json.dumps({"type": "transfer", "trajectory": "T1", "slot": 99}),
        ],
    )
    assert load_history_mints(history) == set()


def test_load_history_mints_concatenated_line(tmp_path: Path) -> None:
    """trajectory_mint buried inside a concatenated line is found."""
    history = tmp_path / "history"
    history.mkdir()
    noise = json.dumps({"type": "escrow_return", "issue": 5})
    mint = _mint_event("T3", 7, 200)
    (history / "2026-04-09.jsonl").write_text(noise + mint + "\n", encoding="utf-8")
    result = load_history_mints(history)
    assert ("T3", 7) in result


# ---------------------------------------------------------------------------
# run_check — full integration
# ---------------------------------------------------------------------------


def test_run_check_pass_single_mint(tmp_path: Path) -> None:
    root = _base_repo(tmp_path)
    result = run_check(root)
    assert result["status"] == "PASS"
    assert result["missing_from_history"] == []
    assert result["missing_from_json"] == []


def test_run_check_fail_json_missing_from_history(tmp_path: Path) -> None:
    """Mint in trajectory_mints.json but no history event."""
    root = _base_repo(tmp_path)
    mints_path = root / "ledger" / "trajectory_mints.json"
    data = json.loads(mints_path.read_text())
    data["mints"].append(
        {"trajectory": "T2", "slot": 1, "amount": 20, "idem_key": "trajectory_mint|T2|1"}
    )
    _write_json(mints_path, data)

    result = run_check(root)
    assert result["status"] == "FAIL"
    assert {"trajectory": "T2", "slot": 1} in result["missing_from_history"]
    assert result["missing_from_json"] == []


def test_run_check_fail_history_missing_from_json(tmp_path: Path) -> None:
    """History event with no corresponding JSON entry."""
    root = _base_repo(tmp_path)
    history_file = root / "ledger" / "history" / "2026-03-18.jsonl"
    _write_jsonl(history_file, [_mint_event("T6", 3, 999)])

    result = run_check(root)
    assert result["status"] == "FAIL"
    assert {"trajectory": "T6", "slot": 3} in result["missing_from_json"]
    assert result["missing_from_history"] == []


def test_run_check_fail_both_directions(tmp_path: Path) -> None:
    """Missing in both directions simultaneously."""
    root = _base_repo(tmp_path)
    # Add JSON mint with no history
    mints_path = root / "ledger" / "trajectory_mints.json"
    data = json.loads(mints_path.read_text())
    data["mints"].append(
        {"trajectory": "T4", "slot": 2, "amount": 21, "idem_key": "trajectory_mint|T4|2"}
    )
    _write_json(mints_path, data)
    # Add history event with no JSON entry
    _write_jsonl(
        root / "ledger" / "history" / "2026-04-01.jsonl",
        [_mint_event("T5", 9, 500)],
    )

    result = run_check(root)
    assert result["status"] == "FAIL"
    assert any(m["trajectory"] == "T4" for m in result["missing_from_history"])
    assert any(m["trajectory"] == "T5" for m in result["missing_from_json"])


def test_run_check_empty_mints_and_empty_history(tmp_path: Path) -> None:
    """Both sources empty → PASS (nothing to mismatch)."""
    root = tmp_path
    (root / "ledger" / "history").mkdir(parents=True)
    _write_json(root / "ledger" / "trajectory_mints.json", {"mints": []})
    result = run_check(root)
    assert result["status"] == "PASS"


def test_run_check_multiple_trajectories_all_match(tmp_path: Path) -> None:
    """Multiple trajectories all present in both directions."""
    root = tmp_path
    (root / "ledger" / "history").mkdir(parents=True)
    pairs = [("T1", 1), ("T2", 2), ("T3", 3), ("T6", 5)]
    mints = [
        {"trajectory": t, "slot": s, "amount": 20, "idem_key": f"trajectory_mint|{t}|{s}"}
        for t, s in pairs
    ]
    _write_json(root / "ledger" / "trajectory_mints.json", {"mints": mints})
    lines = [_mint_event(t, s, 100 + s) for t, s in pairs]
    _write_jsonl(root / "ledger" / "history" / "2026-04-01.jsonl", lines)

    result = run_check(root)
    assert result["status"] == "PASS"


def test_run_check_missing_history_dir(tmp_path: Path) -> None:
    """History dir absent → all JSON mints are missing from history."""
    root = tmp_path
    (root / "ledger").mkdir()
    _write_json(
        root / "ledger" / "trajectory_mints.json",
        {"mints": [{"trajectory": "T1", "slot": 1, "amount": 20}]},
    )
    result = run_check(root)
    assert result["status"] == "FAIL"
    assert {"trajectory": "T1", "slot": 1} in result["missing_from_history"]


def test_run_check_duplicate_in_history_not_double_counted(tmp_path: Path) -> None:
    """Duplicate history events for the same (trajectory, slot) are deduplicated."""
    root = _base_repo(tmp_path)
    # Write the same event twice in a second file
    _write_jsonl(
        root / "ledger" / "history" / "2026-03-18.jsonl",
        [_mint_event("T1", 1, 100), _mint_event("T1", 1, 100)],
    )
    result = run_check(root)
    assert result["status"] == "PASS"
    assert result["missing_from_json"] == []


def test_run_check_output_sorted(tmp_path: Path) -> None:
    """missing_from_history and missing_from_json are sorted by (trajectory, slot)."""
    root = tmp_path
    (root / "ledger" / "history").mkdir(parents=True)
    _write_json(
        root / "ledger" / "trajectory_mints.json",
        {
            "mints": [
                {"trajectory": "T3", "slot": 5, "amount": 24},
                {"trajectory": "T1", "slot": 2, "amount": 21},
            ]
        },
    )
    # No history events at all
    result = run_check(root)
    assert result["status"] == "FAIL"
    keys = [(m["trajectory"], m["slot"]) for m in result["missing_from_history"]]
    assert keys == sorted(keys)
