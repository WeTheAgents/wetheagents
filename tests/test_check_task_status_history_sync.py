"""Tests for scripts/check_task_status_history_sync.py.

Covers all three consistency rules, skip/pass/fail paths, edge cases:
missing files, parse errors, non-integer issue keys, issue number type
normalization (int vs string in history), and empty collections.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.check_task_status_history_sync import (
    _build_issue_sets,
    _iter_history,
    check_tasks,
    run,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_task_index(path: Path, tasks: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": 4, "tasks": tasks}), encoding="utf-8"
    )


def _write_history(history_dir: Path, filename: str, events: list[dict]) -> None:
    history_dir.mkdir(parents=True, exist_ok=True)
    lines = "\n".join(json.dumps(e) for e in events)
    (history_dir / filename).write_text(lines, encoding="utf-8")


# ---------------------------------------------------------------------------
# _build_issue_sets
# ---------------------------------------------------------------------------


def test_build_issue_sets_categorises_events() -> None:
    events = [
        {"type": "accept", "issue": 10},
        {"type": "payment", "issue": 11},
        {"type": "trajectory_mint", "issue": 20},
        {"type": "reject", "issue": 30},
    ]
    accept, payment, mint, reject = _build_issue_sets(events)
    assert accept == {10}
    assert payment == {11}
    assert mint == {20}
    assert reject == {30}


def test_build_issue_sets_skips_missing_issue() -> None:
    events = [
        {"type": "accept"},  # no issue field
        {"type": "trajectory_mint", "issue": None},
    ]
    accept, payment, mint, reject = _build_issue_sets(events)
    assert accept == set()
    assert mint == set()


def test_build_issue_sets_normalises_issue_as_int() -> None:
    # issue stored as string "42" in history (edge case)
    events = [{"type": "accept", "issue": "42"}]
    accept, payment, mint, _ = _build_issue_sets(events)
    assert 42 in accept


def test_build_issue_sets_skips_non_numeric_issue() -> None:
    events = [{"type": "accept", "issue": "bad"}]
    accept, payment, mint, reject = _build_issue_sets(events)
    assert accept == set()


def test_build_issue_sets_multiple_events_same_issue() -> None:
    events = [
        {"type": "accept", "issue": 5},
        {"type": "accept", "issue": 5},
        {"type": "trajectory_mint", "issue": 5},
    ]
    accept, payment, mint, reject = _build_issue_sets(events)
    assert accept == {5}
    assert mint == {5}


# ---------------------------------------------------------------------------
# check_tasks — Rule (a): paid
# ---------------------------------------------------------------------------


def test_paid_with_accept_event_passes() -> None:
    tasks = {"100": {"status": "paid"}}
    checks = check_tasks(tasks, accept_issues={100}, payment_issues=set(), mint_issues=set(), reject_issues=set())
    assert len(checks) == 1
    assert checks[0]["result"] == "PASS"
    assert checks[0]["issue"] == 100


def test_paid_with_trajectory_mint_passes() -> None:
    tasks = {"200": {"status": "paid"}}
    checks = check_tasks(tasks, accept_issues=set(), payment_issues=set(), mint_issues={200}, reject_issues=set())
    assert checks[0]["result"] == "PASS"


def test_paid_with_no_event_fails() -> None:
    tasks = {"300": {"status": "paid"}}
    checks = check_tasks(tasks, accept_issues=set(), payment_issues=set(), mint_issues=set(), reject_issues=set())
    assert checks[0]["result"] == "FAIL"
    assert "300" in checks[0]["note"] or "300" in str(checks[0]["issue"])


def test_paid_with_only_reject_event_fails() -> None:
    # A reject event does NOT satisfy the paid rule
    tasks = {"400": {"status": "paid"}}
    checks = check_tasks(tasks, accept_issues=set(), payment_issues=set(), mint_issues=set(), reject_issues={400})
    assert checks[0]["result"] == "FAIL"


# ---------------------------------------------------------------------------
# check_tasks — Rule (b): open / claimed
# ---------------------------------------------------------------------------


def test_open_with_no_accept_passes() -> None:
    tasks = {"50": {"status": "open"}}
    checks = check_tasks(tasks, accept_issues=set(), payment_issues=set(), mint_issues=set(), reject_issues=set())
    assert checks[0]["result"] == "PASS"


def test_claimed_with_no_accept_passes() -> None:
    tasks = {"51": {"status": "claimed"}}
    checks = check_tasks(tasks, accept_issues=set(), payment_issues=set(), mint_issues=set(), reject_issues=set())
    assert checks[0]["result"] == "PASS"


def test_open_with_accept_event_fails() -> None:
    tasks = {"52": {"status": "open"}}
    checks = check_tasks(tasks, accept_issues={52}, payment_issues=set(), mint_issues=set(), reject_issues=set())
    assert checks[0]["result"] == "FAIL"
    assert "open" in checks[0]["note"]


def test_claimed_with_accept_event_fails() -> None:
    tasks = {"53": {"status": "claimed"}}
    checks = check_tasks(tasks, accept_issues={53}, payment_issues=set(), mint_issues=set(), reject_issues=set())
    assert checks[0]["result"] == "FAIL"
    assert "claimed" in checks[0]["note"]


# ---------------------------------------------------------------------------
# check_tasks — Rule (c): rejected
# ---------------------------------------------------------------------------


def test_rejected_with_reject_event_passes() -> None:
    tasks = {"60": {"status": "rejected"}}
    checks = check_tasks(tasks, accept_issues=set(), payment_issues=set(), mint_issues=set(), reject_issues={60})
    assert checks[0]["result"] == "PASS"


def test_rejected_without_reject_event_fails() -> None:
    tasks = {"61": {"status": "rejected"}}
    checks = check_tasks(tasks, accept_issues=set(), payment_issues=set(), mint_issues=set(), reject_issues=set())
    assert checks[0]["result"] == "FAIL"
    assert "rejected" in checks[0]["note"]


# ---------------------------------------------------------------------------
# check_tasks — other statuses
# ---------------------------------------------------------------------------


def test_cancelled_is_skipped() -> None:
    tasks = {"70": {"status": "cancelled"}}
    checks = check_tasks(tasks, accept_issues=set(), payment_issues=set(), mint_issues=set(), reject_issues=set())
    assert checks[0]["result"] == "SKIP"


def test_unknown_status_is_skipped() -> None:
    tasks = {"71": {"status": "some_future_status"}}
    checks = check_tasks(tasks, accept_issues=set(), payment_issues=set(), mint_issues=set(), reject_issues=set())
    assert checks[0]["result"] == "SKIP"


# ---------------------------------------------------------------------------
# check_tasks — edge cases
# ---------------------------------------------------------------------------


def test_non_integer_issue_key_fails() -> None:
    tasks = {"not_a_number": {"status": "paid"}}
    checks = check_tasks(tasks, accept_issues=set(), payment_issues=set(), mint_issues=set(), reject_issues=set())
    assert checks[0]["result"] == "FAIL"
    assert "non-integer" in checks[0]["note"]


def test_task_entry_not_a_dict_fails() -> None:
    tasks = {"80": "wrong_type"}
    checks = check_tasks(tasks, accept_issues=set(), payment_issues=set(), mint_issues=set(), reject_issues=set())
    assert checks[0]["result"] == "FAIL"
    assert "not a dict" in checks[0]["note"]


def test_empty_tasks_returns_empty_checks() -> None:
    checks = check_tasks({}, set(), set(), set(), set())
    assert checks == []


# ---------------------------------------------------------------------------
# _iter_history
# ---------------------------------------------------------------------------


def test_iter_history_reads_multiple_files(tmp_path: Path) -> None:
    history_dir = tmp_path / "history"
    _write_history(history_dir, "2026-01-01.jsonl", [{"type": "accept", "issue": 1}])
    _write_history(history_dir, "2026-01-02.jsonl", [{"type": "reject", "issue": 2}])
    events = _iter_history(history_dir)
    assert len(events) == 2


def test_iter_history_skips_malformed_lines(tmp_path: Path) -> None:
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    (history_dir / "2026-01-01.jsonl").write_text(
        '{"type": "accept", "issue": 1}\nnot-json\n{"type": "reject", "issue": 2}',
        encoding="utf-8",
    )
    events = _iter_history(history_dir)
    assert len(events) == 2


def test_iter_history_missing_dir_returns_empty(tmp_path: Path) -> None:
    events = _iter_history(tmp_path / "nonexistent")
    assert events == []


def test_iter_history_skips_blank_lines(tmp_path: Path) -> None:
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    (history_dir / "2026-01-01.jsonl").write_text(
        '\n\n{"type": "accept", "issue": 5}\n\n', encoding="utf-8"
    )
    events = _iter_history(history_dir)
    assert len(events) == 1


# ---------------------------------------------------------------------------
# run() — integration tests
# ---------------------------------------------------------------------------


def test_run_all_pass(tmp_path: Path) -> None:
    _write_task_index(
        tmp_path / "ledger" / "task_index.json",
        {
            "1": {"status": "paid"},
            "2": {"status": "open"},
            "3": {"status": "cancelled"},
        },
    )
    _write_history(
        tmp_path / "ledger" / "history",
        "2026-01-01.jsonl",
        [{"type": "accept", "issue": 1}],
    )

    result, passed = run(tmp_path)
    assert passed is True
    assert result["status"] == "PASS"
    fails = [c for c in result["checks"] if c["result"] == "FAIL"]
    assert fails == []


def test_run_paid_without_event_fails(tmp_path: Path) -> None:
    _write_task_index(
        tmp_path / "ledger" / "task_index.json",
        {"99": {"status": "paid"}},
    )
    _write_history(
        tmp_path / "ledger" / "history",
        "2026-01-01.jsonl",
        [],
    )

    result, passed = run(tmp_path)
    assert passed is False
    assert result["status"] == "FAIL"
    assert any(c["issue"] == 99 and c["result"] == "FAIL" for c in result["checks"])


def test_run_open_with_accept_event_fails(tmp_path: Path) -> None:
    _write_task_index(
        tmp_path / "ledger" / "task_index.json",
        {"42": {"status": "open"}},
    )
    _write_history(
        tmp_path / "ledger" / "history",
        "2026-01-01.jsonl",
        [{"type": "accept", "issue": 42}],
    )

    result, passed = run(tmp_path)
    assert passed is False
    assert any(c["issue"] == 42 and c["result"] == "FAIL" for c in result["checks"])


def test_run_missing_task_index_fails(tmp_path: Path) -> None:
    result, passed = run(tmp_path)
    assert passed is False
    assert "not found" in result["summary"]


def test_run_invalid_task_index_json_fails(tmp_path: Path) -> None:
    task_index_path = tmp_path / "ledger" / "task_index.json"
    task_index_path.parent.mkdir(parents=True, exist_ok=True)
    task_index_path.write_text("not valid json", encoding="utf-8")

    result, passed = run(tmp_path)
    assert passed is False
    assert "not valid JSON" in result["summary"]


def test_run_trajectory_mint_satisfies_paid_rule(tmp_path: Path) -> None:
    _write_task_index(
        tmp_path / "ledger" / "task_index.json",
        {"500": {"status": "paid"}},
    )
    _write_history(
        tmp_path / "ledger" / "history",
        "2026-01-01.jsonl",
        [{"type": "trajectory_mint", "issue": 500, "trajectory": "T1", "slot": 1}],
    )

    result, passed = run(tmp_path)
    assert passed is True
    assert result["checks"][0]["result"] == "PASS"


def test_run_rejected_without_reject_event_fails(tmp_path: Path) -> None:
    _write_task_index(
        tmp_path / "ledger" / "task_index.json",
        {"77": {"status": "rejected"}},
    )
    _write_history(
        tmp_path / "ledger" / "history",
        "2026-01-01.jsonl",
        [],
    )

    result, passed = run(tmp_path)
    assert passed is False
    assert any(c["issue"] == 77 and c["result"] == "FAIL" for c in result["checks"])


def test_run_empty_history_dir(tmp_path: Path) -> None:
    _write_task_index(
        tmp_path / "ledger" / "task_index.json",
        {"10": {"status": "open"}},
    )
    (tmp_path / "ledger" / "history").mkdir(parents=True)

    result, passed = run(tmp_path)
    assert passed is True  # open with no accept events is valid


def test_run_summary_counts_correct(tmp_path: Path) -> None:
    _write_task_index(
        tmp_path / "ledger" / "task_index.json",
        {
            "1": {"status": "paid"},   # PASS
            "2": {"status": "paid"},   # FAIL (no event)
            "3": {"status": "cancelled"},  # SKIP
        },
    )
    _write_history(
        tmp_path / "ledger" / "history",
        "2026-01-01.jsonl",
        [{"type": "accept", "issue": 1}],
    )

    result, passed = run(tmp_path)
    assert passed is False
    assert "1 PASS" in result["summary"]
    assert "1 FAIL" in result["summary"]
    assert "1 SKIP" in result["summary"]
