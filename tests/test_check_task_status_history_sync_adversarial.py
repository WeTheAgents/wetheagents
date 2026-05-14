"""Adversarial tests for scripts/check_task_status_history_sync.py.

Four adversarial scenarios not fully covered by the baseline test suite:

  (a) Accept event in history but status=open in task_index — should FAIL.
      Tests multi-file history, cross-file accept detection, and the gap
      where trajectory_mint does NOT trigger Rule (b) (by design).

  (b) Paid task with off-by-one issue number in accept event — should FAIL.
      Verifies exact-match semantics: accept for N+1 or N-1 does not satisfy
      payment requirement for task N.

  (c) JSONL with malformed lines mixed with valid events — should not crash.
      Valid events embedded in corrupted JSONL must still be found; fully
      malformed files yield empty event sets without raising exceptions.

  (d) Task with multiple accept events for the same issue — should still PASS.
      Duplicate accept events are deduplicated by the set data structure;
      paid tasks pass and open tasks still fail regardless of accept count.
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
    path.write_text(json.dumps({"version": 4, "tasks": tasks}), encoding="utf-8")


def _write_history(history_dir: Path, filename: str, lines: list[str]) -> None:
    """Write raw lines to a JSONL history file (lines are written as-is)."""
    history_dir.mkdir(parents=True, exist_ok=True)
    (history_dir / filename).write_text("\n".join(lines), encoding="utf-8")


def _event(event_type: str, issue: int, **extra) -> str:
    """Return a valid JSON event line."""
    return json.dumps({"type": event_type, "issue": issue, **extra})


# ---------------------------------------------------------------------------
# (a) Accept event in history but status=open in task_index
# ---------------------------------------------------------------------------


def test_accept_event_in_second_file_status_open_fails(tmp_path: Path) -> None:
    """Accept event lives in a later JSONL file while task_index shows status=open.

    Attack pattern: task_index manually rolled back to 'open' after an accept
    was recorded in a different history file.  The checker must scan ALL files,
    not just the most recent one.

    Expected: FAIL — Rule (b) violation detected across file boundary.
    """
    _write_task_index(
        tmp_path / "ledger" / "task_index.json",
        {"42": {"status": "open"}},
    )
    history_dir = tmp_path / "ledger" / "history"
    _write_history(history_dir, "2026-01-01.jsonl", [
        _event("escrow_create", 42),
        _event("claim", 42),
    ])
    _write_history(history_dir, "2026-01-02.jsonl", [
        _event("accept", 42),  # accept lives in a separate file
    ])

    result, passed = run(tmp_path)
    assert passed is False
    assert result["status"] == "FAIL"
    assert any(c["issue"] == 42 and c["result"] == "FAIL" for c in result["checks"])


def test_accept_event_different_issue_status_open_passes(tmp_path: Path) -> None:
    """Accept event exists in history for issue 41, but the open task is issue 42.

    The checker must match issue numbers exactly.  A accept for a neighbouring
    issue must not trigger a false positive on the open task.

    Expected: PASS — no Rule (b) violation for issue 42.
    """
    _write_task_index(
        tmp_path / "ledger" / "task_index.json",
        {"42": {"status": "open"}},
    )
    history_dir = tmp_path / "ledger" / "history"
    _write_history(history_dir, "2026-01-01.jsonl", [
        _event("accept", 41),  # different issue — must not contaminate issue 42
    ])

    result, passed = run(tmp_path)
    assert passed is True
    assert result["status"] == "PASS"
    assert all(c["result"] in ("PASS", "SKIP") for c in result["checks"])


def test_trajectory_mint_does_not_trigger_rule_b(tmp_path: Path) -> None:
    """A trajectory_mint event in history does NOT trigger Rule (b) for open tasks.

    Rule (b) only checks the accept_issues set, not mint_issues.  This is a
    documented gap: an open task with a mint event is not flagged.  This test
    records the current (permissive) behaviour so any future tightening is
    visible via test failure.

    Expected: PASS — Rule (b) is not triggered by trajectory_mint alone.
    """
    _write_task_index(
        tmp_path / "ledger" / "task_index.json",
        {"50": {"status": "open"}},
    )
    history_dir = tmp_path / "ledger" / "history"
    _write_history(history_dir, "2026-01-01.jsonl", [
        json.dumps({
            "type": "trajectory_mint",
            "issue": 50,
            "trajectory": "T2",
            "slot": 5,
            "amount": 44,
        }),
    ])

    result, passed = run(tmp_path)
    # Current behaviour: Rule (b) only looks at accept_issues, not mint_issues.
    # A trajectory_mint alone does not constitute a Rule (b) violation.
    assert passed is True
    assert result["checks"][0]["result"] == "PASS"


def test_multiple_open_tasks_one_has_accept_only_that_one_fails(tmp_path: Path) -> None:
    """Three open tasks; only one has an accept event in history.

    Verifies that the checker reports a precise FAIL only for the affected task
    and does not contaminate the two unaffected tasks.

    Expected: one FAIL (issue 10), two PASS (issues 20, 30).
    """
    _write_task_index(
        tmp_path / "ledger" / "task_index.json",
        {
            "10": {"status": "open"},
            "20": {"status": "open"},
            "30": {"status": "open"},
        },
    )
    history_dir = tmp_path / "ledger" / "history"
    _write_history(history_dir, "2026-01-01.jsonl", [
        _event("accept", 10),  # only issue 10 is affected
    ])

    result, passed = run(tmp_path)
    assert passed is False
    checks_by_issue = {c["issue"]: c for c in result["checks"]}
    assert checks_by_issue[10]["result"] == "FAIL"
    assert checks_by_issue[20]["result"] == "PASS"
    assert checks_by_issue[30]["result"] == "PASS"


# ---------------------------------------------------------------------------
# (b) Paid task with off-by-one issue number in accept event
# ---------------------------------------------------------------------------


def test_paid_task_accept_event_one_higher_fails(tmp_path: Path) -> None:
    """Task 100 is paid; only accept event in history is for issue 101.

    An off-by-one in the issue number means the accept event belongs to a
    different task.  Rule (a) must not be satisfied.

    Expected: FAIL — issue 100 has no matching payment event.
    """
    _write_task_index(
        tmp_path / "ledger" / "task_index.json",
        {"100": {"status": "paid"}},
    )
    history_dir = tmp_path / "ledger" / "history"
    _write_history(history_dir, "2026-01-01.jsonl", [
        _event("accept", 101),  # one higher — must not satisfy issue 100
    ])

    result, passed = run(tmp_path)
    assert passed is False
    assert result["checks"][0]["issue"] == 100
    assert result["checks"][0]["result"] == "FAIL"


def test_paid_task_accept_event_one_lower_fails(tmp_path: Path) -> None:
    """Task 100 is paid; only accept event in history is for issue 99.

    Off-by-one in the other direction.  Rule (a) must reject the near-miss.

    Expected: FAIL — issue 100 has no matching payment event.
    """
    _write_task_index(
        tmp_path / "ledger" / "task_index.json",
        {"100": {"status": "paid"}},
    )
    history_dir = tmp_path / "ledger" / "history"
    _write_history(history_dir, "2026-01-01.jsonl", [
        _event("accept", 99),  # one lower — must not satisfy issue 100
    ])

    result, passed = run(tmp_path)
    assert passed is False
    assert result["checks"][0]["result"] == "FAIL"


def test_paid_task_accept_exact_match_passes(tmp_path: Path) -> None:
    """Task 100 is paid; accept event is exactly for issue 100.

    Baseline passing case: exact match must satisfy Rule (a).

    Expected: PASS.
    """
    _write_task_index(
        tmp_path / "ledger" / "task_index.json",
        {"100": {"status": "paid"}},
    )
    history_dir = tmp_path / "ledger" / "history"
    _write_history(history_dir, "2026-01-01.jsonl", [
        _event("accept", 100),
    ])

    result, passed = run(tmp_path)
    assert passed is True
    assert result["checks"][0]["result"] == "PASS"


def test_open_task_neighbour_accept_not_a_violation(tmp_path: Path) -> None:
    """Task 100 is open; accept event is for issue 99 (a neighbour).

    Rule (b) checks whether the open task's own issue number is in accept_issues.
    A accept for issue 99 must not cause a false positive violation for task 100.

    Expected: PASS.
    """
    tasks = {"100": {"status": "open"}}
    checks = check_tasks(
        tasks,
        accept_issues={99},  # neighbour, not 100
        payment_issues=set(),
        mint_issues=set(),
        reject_issues=set(),
    )
    assert checks[0]["issue"] == 100
    assert checks[0]["result"] == "PASS"


# ---------------------------------------------------------------------------
# (c) JSONL with malformed lines mixed with valid events — should not crash
# ---------------------------------------------------------------------------


def test_malformed_lines_before_valid_accept_does_not_crash(tmp_path: Path) -> None:
    """Malformed JSONL lines precede a valid accept event; checker must not crash.

    The accept event must still be discovered and satisfy Rule (a) for the
    paid task.

    Expected: PASS — valid event is found despite surrounding garbage.
    """
    _write_task_index(
        tmp_path / "ledger" / "task_index.json",
        {"7": {"status": "paid"}},
    )
    history_dir = tmp_path / "ledger" / "history"
    _write_history(history_dir, "2026-01-01.jsonl", [
        "not valid json at all",
        "{broken",
        '{"type": "accept", "issue": 7}',  # valid accept after garbage
        "another bad line",
    ])

    result, passed = run(tmp_path)
    assert passed is True
    assert result["checks"][0]["result"] == "PASS"


def test_fully_malformed_jsonl_paid_task_fails(tmp_path: Path) -> None:
    """All lines in the JSONL file are malformed; no valid events are parsed.

    With no accept events found, a paid task has no payment evidence and must FAIL.

    Expected: FAIL — no events parseable from corrupt history.
    """
    _write_task_index(
        tmp_path / "ledger" / "task_index.json",
        {"8": {"status": "paid"}},
    )
    history_dir = tmp_path / "ledger" / "history"
    _write_history(history_dir, "2026-01-01.jsonl", [
        "not json",
        "{bad",
        "also bad [",
        "}}}}",
    ])

    result, passed = run(tmp_path)
    assert passed is False
    assert result["checks"][0]["result"] == "FAIL"


def test_json_non_object_lines_are_skipped(tmp_path: Path) -> None:
    """JSONL lines that are valid JSON but not objects (arrays, scalars) are skipped.

    The checker calls ``isinstance(entry, dict)`` after parsing; non-dict values
    must be silently skipped without raising an exception.

    Expected: FAIL for the paid task (no usable accept event).
    """
    _write_task_index(
        tmp_path / "ledger" / "task_index.json",
        {"9": {"status": "paid"}},
    )
    history_dir = tmp_path / "ledger" / "history"
    _write_history(history_dir, "2026-01-01.jsonl", [
        "[1, 2, 3]",          # valid JSON array — not a dict, must be skipped
        '"accept"',           # valid JSON string — not a dict
        "42",                 # valid JSON number — not a dict
        "null",               # valid JSON null — not a dict
    ])

    result, passed = run(tmp_path)
    assert passed is False
    assert result["checks"][0]["result"] == "FAIL"


def test_malformed_lines_across_multiple_files_valid_accept_found(tmp_path: Path) -> None:
    """Malformed lines are spread across multiple files; valid accept is in the last file.

    The checker iterates files in sorted order; the accept must be found
    regardless of which file it lands in.

    Expected: PASS — accept discovered in last file despite earlier corruption.
    """
    _write_task_index(
        tmp_path / "ledger" / "task_index.json",
        {"15": {"status": "paid"}},
    )
    history_dir = tmp_path / "ledger" / "history"
    _write_history(history_dir, "2026-01-01.jsonl", [
        "corrupted line one",
        "{bad json",
    ])
    _write_history(history_dir, "2026-01-02.jsonl", [
        "more garbage",
    ])
    _write_history(history_dir, "2026-01-03.jsonl", [
        "still garbage",
        '{"type": "accept", "issue": 15}',  # valid accept in last file
    ])

    result, passed = run(tmp_path)
    assert passed is True
    assert result["checks"][0]["result"] == "PASS"


# ---------------------------------------------------------------------------
# (d) Task with multiple accept events for same issue — should still PASS
# ---------------------------------------------------------------------------


def test_multiple_accept_events_same_issue_paid_passes(tmp_path: Path) -> None:
    """Task paid; history contains three accept events for the same issue.

    Duplicate accept events are collapsed into a single entry in the set.
    Rule (a) must PASS regardless of how many times the issue appears.

    Expected: PASS — idempotent set semantics absorb duplicates.
    """
    _write_task_index(
        tmp_path / "ledger" / "task_index.json",
        {"20": {"status": "paid"}},
    )
    history_dir = tmp_path / "ledger" / "history"
    _write_history(history_dir, "2026-01-01.jsonl", [
        _event("accept", 20),
        _event("accept", 20),
        _event("accept", 20),
    ])

    result, passed = run(tmp_path)
    assert passed is True
    assert result["checks"][0]["result"] == "PASS"


def test_multiple_accept_events_same_issue_open_fails(tmp_path: Path) -> None:
    """Task open; history contains two accept events for the same issue.

    Even with duplicate accepts, the fact that ANY accept event exists for an
    open task is a Rule (b) violation.  Deduplication must not suppress the fail.

    Expected: FAIL — one or many accepts for an open task is equally invalid.
    """
    _write_task_index(
        tmp_path / "ledger" / "task_index.json",
        {"21": {"status": "open"}},
    )
    history_dir = tmp_path / "ledger" / "history"
    _write_history(history_dir, "2026-01-01.jsonl", [
        _event("accept", 21),
        _event("accept", 21),  # duplicate
    ])

    result, passed = run(tmp_path)
    assert passed is False
    assert result["checks"][0]["result"] == "FAIL"
    assert "open" in result["checks"][0]["note"]


def test_accept_events_across_multiple_files_paid_passes(tmp_path: Path) -> None:
    """Task paid; accept events for the same issue appear in separate JSONL files.

    The checker accumulates events from all files; a paid task must PASS when
    its accept event exists in any file, even if duplicated across files.

    Expected: PASS — accepts from multiple files are all collected.
    """
    _write_task_index(
        tmp_path / "ledger" / "task_index.json",
        {"22": {"status": "paid"}},
    )
    history_dir = tmp_path / "ledger" / "history"
    _write_history(history_dir, "2026-01-01.jsonl", [_event("accept", 22)])
    _write_history(history_dir, "2026-01-02.jsonl", [_event("accept", 22)])  # duplicate in next file

    result, passed = run(tmp_path)
    assert passed is True
    assert result["checks"][0]["result"] == "PASS"


def test_build_issue_sets_multiple_accepts_same_issue_deduplicates() -> None:
    """_build_issue_sets collapses duplicate accept events to a single issue number.

    This is a unit-level verification that the set data structure correctly
    deduplicates repeated accept events, which is the foundation that allows
    the multi-accept PASS behaviour in the integration tests above.
    """
    events = [
        {"type": "accept", "issue": 55},
        {"type": "accept", "issue": 55},
        {"type": "accept", "issue": 55},
        {"type": "accept", "issue": 56},
    ]
    accept, payment, mint, reject = _build_issue_sets(events)
    assert accept == {55, 56}
    assert len(accept) == 2  # no duplicates in set
