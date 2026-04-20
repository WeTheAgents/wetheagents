"""Boundary spec suite for scripts/check_single_escrow_per_issue.py (T3S24).

Encodes the full behavioural contract for edge inputs:

  (a) empty history directory — PASS
  (b) single issue with one escrow_create and one accept — PASS
  (c) single issue with two consecutive escrow_create events, no close — FAIL
  (d) single issue with escrow_create, escrow_return, escrow_create — PASS
  (e) issue with escrow_create followed by payment — PASS
  (f) malformed JSONL line in history — no crash; line skipped
  (g) history files out of alphabetical order — timestamp order governs
  (h) multiple issues, only one with double escrow — only that issue reported
  (i) issue number as string vs integer — normalized, no false positives
  (j) escrow_return with no prior escrow_create — PASS
  (k) large count of valid escrows across many issues — PASS
  (l) reject event as escrow close event — PASS
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.check_single_escrow_per_issue import run_check


# ── helpers ───────────────────────────────────────────────────────────────────


def _history_dir(root: Path) -> Path:
    d = root / "ledger" / "history"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_jsonl(path: Path, events: list[dict | str]) -> None:
    lines: list[str] = []
    for event in events:
        lines.append(event if isinstance(event, str) else json.dumps(event))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _ev(event_type: str, issue: int | str, ts: str) -> dict:
    return {"type": event_type, "issue": issue, "timestamp": ts}


# ── (a) empty history directory ───────────────────────────────────────────────


def test_spec_a_empty_history_dir_passes(tmp_path: Path) -> None:
    _history_dir(tmp_path)  # create the dir but add no files

    report = run_check(tmp_path)

    assert report["status"] == "PASS"
    assert report["violations"] == []
    assert report["stats"]["history_events_scanned"] == 0
    assert report["stats"]["history_files_scanned"] == 0


# ── (b) single lifecycle: create then accept ──────────────────────────────────


def test_spec_b_single_lifecycle_create_then_accept_passes(tmp_path: Path) -> None:
    hd = _history_dir(tmp_path)
    _write_jsonl(hd / "2026-04-01.jsonl", [
        _ev("escrow_create", 1, "2026-04-01T00:00:00Z"),
        _ev("accept", 1, "2026-04-01T01:00:00Z"),
    ])

    report = run_check(tmp_path)

    assert report["status"] == "PASS"
    assert report["violations"] == []
    assert report["stats"]["escrow_creates_scanned"] == 1
    assert report["stats"]["closing_events_scanned"] == 1


# ── (c) two consecutive creates, no close ─────────────────────────────────────


def test_spec_c_two_consecutive_creates_no_close_fails(tmp_path: Path) -> None:
    hd = _history_dir(tmp_path)
    _write_jsonl(hd / "2026-04-02.jsonl", [
        _ev("escrow_create", 5, "2026-04-02T00:00:00Z"),
        _ev("escrow_create", 5, "2026-04-02T01:00:00Z"),
    ])

    report = run_check(tmp_path)

    assert report["status"] == "FAIL"
    assert len(report["violations"]) == 1
    assert report["violations"][0]["issue"] == 5
    assert report["violations"][0]["open_escrows"] == 2
    assert report["stats"]["issues_with_multiple_active_escrows"] == 1


# ── (d) create + escrow_return + create: second create is valid ───────────────


def test_spec_d_create_return_create_passes(tmp_path: Path) -> None:
    hd = _history_dir(tmp_path)
    _write_jsonl(hd / "2026-04-03.jsonl", [
        _ev("escrow_create", 10, "2026-04-03T00:00:00Z"),
        _ev("escrow_return", 10, "2026-04-03T01:00:00Z"),
        _ev("escrow_create", 10, "2026-04-03T02:00:00Z"),
    ])

    report = run_check(tmp_path)

    assert report["status"] == "PASS"
    assert report["violations"] == []
    # The return closed the first escrow; only one active escrow at any time
    assert report["stats"]["closing_events_scanned"] == 1
    assert report["stats"]["escrow_creates_scanned"] == 2


# ── (e) create followed by payment ───────────────────────────────────────────


def test_spec_e_create_then_payment_passes(tmp_path: Path) -> None:
    hd = _history_dir(tmp_path)
    _write_jsonl(hd / "2026-04-04.jsonl", [
        _ev("escrow_create", 20, "2026-04-04T00:00:00Z"),
        _ev("payment", 20, "2026-04-04T01:00:00Z"),
    ])

    report = run_check(tmp_path)

    assert report["status"] == "PASS"
    assert report["violations"] == []
    assert report["stats"]["escrow_creates_scanned"] == 1
    assert report["stats"]["closing_events_scanned"] == 1


# ── (f) malformed JSONL line — no crash, line skipped ────────────────────────


def test_spec_f_malformed_jsonl_no_crash_skips_line(tmp_path: Path) -> None:
    hd = _history_dir(tmp_path)
    _write_jsonl(hd / "2026-04-05.jsonl", [
        _ev("escrow_create", 25, "2026-04-05T00:00:00Z"),
        "this is not valid json }{",
        _ev("accept", 25, "2026-04-05T02:00:00Z"),
    ])

    # Must not raise; malformed line is skipped
    report = run_check(tmp_path)

    assert report["status"] == "PASS"
    assert report["stats"]["malformed_lines_skipped"] == 1
    assert report["stats"]["history_events_scanned"] == 2


# ── (g) files out of alphabetical order — timestamp order governs ─────────────


def test_spec_g_files_out_of_alphabetical_order_processed_by_timestamp(tmp_path: Path) -> None:
    hd = _history_dir(tmp_path)

    # z_early.jsonl is alphabetically LAST but holds the EARLIEST timestamps.
    # It contains the full open→close lifecycle at T1+T2.
    _write_jsonl(hd / "z_early.jsonl", [
        _ev("escrow_create", 30, "2026-04-06T00:00:00Z"),
        _ev("accept", 30, "2026-04-06T01:00:00Z"),
    ])

    # a_late.jsonl is alphabetically FIRST but holds the LATEST timestamp.
    # It holds a second create at T3, which is valid (after the close at T2).
    _write_jsonl(hd / "a_late.jsonl", [
        _ev("escrow_create", 30, "2026-04-06T02:00:00Z"),
    ])

    report = run_check(tmp_path)

    # Timestamp order: create(T1) → accept(T2) → create(T3) = PASS
    # Filename-alpha order would give: create(T3) then create(T1),accept(T2) = two opens before close = FAIL
    assert report["status"] == "PASS"
    assert report["violations"] == []
    assert report["stats"]["history_files_scanned"] == 2


# ── (h) multiple issues, only one failing ────────────────────────────────────


def test_spec_h_multiple_issues_only_one_failing_reports_only_that_issue(tmp_path: Path) -> None:
    hd = _history_dir(tmp_path)
    _write_jsonl(hd / "2026-04-07.jsonl", [
        # issue 1: clean lifecycle — PASS
        _ev("escrow_create", 1, "2026-04-07T00:00:00Z"),
        _ev("accept", 1, "2026-04-07T01:00:00Z"),
        # issue 2: double create — FAIL
        _ev("escrow_create", 2, "2026-04-07T02:00:00Z"),
        _ev("escrow_create", 2, "2026-04-07T03:00:00Z"),
        # issue 3: create + payment — PASS
        _ev("escrow_create", 3, "2026-04-07T04:00:00Z"),
        _ev("payment", 3, "2026-04-07T05:00:00Z"),
    ])

    report = run_check(tmp_path)

    assert report["status"] == "FAIL"
    assert len(report["violations"]) == 1
    assert report["violations"][0]["issue"] == 2
    assert report["stats"]["issues_with_multiple_active_escrows"] == 1


# ── (i) issue number string vs integer — normalized, no false positives ───────


def test_spec_i_issue_number_type_normalization_no_false_positives(tmp_path: Path) -> None:
    hd = _history_dir(tmp_path)
    # String "42" and integer 42 must be treated as the same issue.
    # create(str) → accept(int) should be a single clean lifecycle.
    _write_jsonl(hd / "2026-04-08.jsonl", [
        _ev("escrow_create", "42", "2026-04-08T00:00:00Z"),
        _ev("accept", 42, "2026-04-08T01:00:00Z"),
    ])

    report = run_check(tmp_path)

    assert report["status"] == "PASS"
    assert report["violations"] == []
    assert report["stats"]["escrow_creates_scanned"] == 1
    assert report["stats"]["closing_events_scanned"] == 1


# ── (j) escrow_return with no prior escrow_create ────────────────────────────


def test_spec_j_escrow_return_with_no_prior_create_passes(tmp_path: Path) -> None:
    hd = _history_dir(tmp_path)
    # A stray escrow_return (no matching create) must not cause a false positive.
    _write_jsonl(hd / "2026-04-09.jsonl", [
        _ev("escrow_return", 50, "2026-04-09T00:00:00Z"),
    ])

    report = run_check(tmp_path)

    assert report["status"] == "PASS"
    assert report["violations"] == []
    # The stray return is still counted as a closing event
    assert report["stats"]["closing_events_scanned"] == 1


# ── (k) large count of valid escrows ─────────────────────────────────────────


def test_spec_k_large_count_valid_escrows_passes(tmp_path: Path) -> None:
    hd = _history_dir(tmp_path)
    events: list[dict] = []
    for i in range(100):
        base = i * 2
        events.append(_ev("escrow_create", i + 1, f"2026-04-10T{base:02d}:00:00Z" if base < 24 else f"2026-04-{10 + base // 24:02d}T{base % 24:02d}:00:00Z"))
        events.append(_ev("accept", i + 1, f"2026-04-10T{base + 1:02d}:00:00Z" if base + 1 < 24 else f"2026-04-{10 + (base + 1) // 24:02d}T{(base + 1) % 24:02d}:00:00Z"))
    _write_jsonl(hd / "2026-04-10.jsonl", events)

    report = run_check(tmp_path)

    assert report["status"] == "PASS"
    assert report["violations"] == []
    assert report["stats"]["escrow_creates_scanned"] == 100
    assert report["stats"]["closing_events_scanned"] == 100


# ── (l) reject event as escrow close event ───────────────────────────────────


def test_spec_l_reject_as_close_event_passes(tmp_path: Path) -> None:
    hd = _history_dir(tmp_path)
    # Sequence: create → reject → create
    # "reject" must close the first escrow so that the second create is valid.
    _write_jsonl(hd / "2026-04-11.jsonl", [
        _ev("escrow_create", 99, "2026-04-11T00:00:00Z"),
        _ev("reject", 99, "2026-04-11T01:00:00Z"),
        _ev("escrow_create", 99, "2026-04-11T02:00:00Z"),
    ])

    report = run_check(tmp_path)

    assert report["status"] == "PASS"
    assert report["violations"] == []
    assert report["stats"]["closing_events_scanned"] == 1
    assert report["stats"]["escrow_creates_scanned"] == 2
