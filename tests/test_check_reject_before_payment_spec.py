"""Boundary spec suite for scripts/check_reject_before_payment.py (T4S26).

Encodes the full behavioural contract for edge inputs:

  (a) empty history directory — PASS
  (b) single issue: reject only, no payment — PASS
  (c) single issue: accept only, no reject — PASS
  (d) single issue: reject then accept, same agent — FAIL
  (e) single issue: reject then accept, different agents — PASS
  (f) single issue: accept then reject (correct order) — PASS
  (g) single issue: reject then payment event (not accept) — FAIL
  (h) two issues independent: one with reject-then-accept (FAIL), one clean (PASS)
  (i) malformed JSONL line in history — skip line, no crash
  (j) issue number as string vs integer in event — normalized correctly
  (k) same (issue, agent) pair: reject, return, re-accept — still FAIL
  (l) multiple reject events for same pair before payment — FAIL reported once
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.check_reject_before_payment import run_check


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


def _ev(event_type: str, issue: int | str, agent: str, ts: str) -> dict:
    return {"type": event_type, "issue": issue, "agent": agent, "timestamp": ts}


# ── (a) empty history directory ───────────────────────────────────────────────


def test_spec_a_empty_history_dir_passes(tmp_path: Path) -> None:
    _history_dir(tmp_path)  # create the dir but add no files

    report = run_check(tmp_path)

    assert report["status"] == "PASS"
    assert report["violations"] == []
    assert report["stats"]["history_events_scanned"] == 0
    assert report["stats"]["history_files_scanned"] == 0


# ── (b) reject only, no payment ───────────────────────────────────────────────


def test_spec_b_reject_only_no_payment_passes(tmp_path: Path) -> None:
    hd = _history_dir(tmp_path)
    _write_jsonl(hd / "2026-04-01.jsonl", [
        _ev("reject", 1, "alice@test", "2026-04-01T09:00:00Z"),
    ])

    report = run_check(tmp_path)

    assert report["status"] == "PASS"
    assert report["violations"] == []
    assert report["stats"]["reject_events_scanned"] == 1
    assert report["stats"]["payment_events_scanned"] == 0


# ── (c) accept only, no reject ────────────────────────────────────────────────


def test_spec_c_accept_only_no_reject_passes(tmp_path: Path) -> None:
    hd = _history_dir(tmp_path)
    _write_jsonl(hd / "2026-04-01.jsonl", [
        _ev("accept", 1, "alice@test", "2026-04-01T09:00:00Z"),
    ])

    report = run_check(tmp_path)

    assert report["status"] == "PASS"
    assert report["violations"] == []
    assert report["stats"]["reject_events_scanned"] == 0
    assert report["stats"]["payment_events_scanned"] == 1


# ── (d) reject then accept, same agent ────────────────────────────────────────


def test_spec_d_reject_then_accept_same_agent_fails(tmp_path: Path) -> None:
    hd = _history_dir(tmp_path)
    _write_jsonl(hd / "2026-04-01.jsonl", [
        _ev("reject", 10, "alice@test", "2026-04-01T09:00:00Z"),
        _ev("accept", 10, "alice@test", "2026-04-01T10:00:00Z"),
    ])

    report = run_check(tmp_path)

    assert report["status"] == "FAIL"
    assert len(report["violations"]) == 1
    v = report["violations"][0]
    assert v["issue"] == 10
    assert v["agent"] == "alice@test"
    assert v["event_type"] == "accept"
    assert report["stats"]["pairs_with_reject_before_payment"] == 1


# ── (e) reject then accept, different agents ──────────────────────────────────


def test_spec_e_reject_then_accept_different_agents_passes(tmp_path: Path) -> None:
    hd = _history_dir(tmp_path)
    _write_jsonl(hd / "2026-04-01.jsonl", [
        _ev("reject", 10, "alice@test", "2026-04-01T09:00:00Z"),
        _ev("accept", 10, "bob@test", "2026-04-01T10:00:00Z"),
    ])

    report = run_check(tmp_path)

    assert report["status"] == "PASS"
    assert report["violations"] == []
    # alice was rejected; bob's accept is independent
    assert report["stats"]["reject_events_scanned"] == 1
    assert report["stats"]["payment_events_scanned"] == 1


# ── (f) accept then reject (correct order) ────────────────────────────────────


def test_spec_f_accept_then_reject_passes(tmp_path: Path) -> None:
    hd = _history_dir(tmp_path)
    # accept comes BEFORE reject — reject was not yet recorded when payment occurred
    _write_jsonl(hd / "2026-04-01.jsonl", [
        _ev("accept", 10, "alice@test", "2026-04-01T09:00:00Z"),
        _ev("reject", 10, "alice@test", "2026-04-01T10:00:00Z"),
    ])

    report = run_check(tmp_path)

    assert report["status"] == "PASS"
    assert report["violations"] == []


# ── (g) reject then explicit payment event ────────────────────────────────────


def test_spec_g_reject_then_payment_event_fails(tmp_path: Path) -> None:
    hd = _history_dir(tmp_path)
    _write_jsonl(hd / "2026-04-01.jsonl", [
        _ev("reject", 20, "alice@test", "2026-04-01T09:00:00Z"),
        {"type": "payment", "issue": 20, "agent": "alice@test",
         "amount": 10, "timestamp": "2026-04-01T10:00:00Z"},
    ])

    report = run_check(tmp_path)

    assert report["status"] == "FAIL"
    assert len(report["violations"]) == 1
    assert report["violations"][0]["event_type"] == "payment"
    assert report["violations"][0]["issue"] == 20


# ── (h) two issues, only one failing ──────────────────────────────────────────


def test_spec_h_two_issues_only_failing_reported(tmp_path: Path) -> None:
    hd = _history_dir(tmp_path)
    _write_jsonl(hd / "2026-04-01.jsonl", [
        # issue 5: reject → accept same agent → FAIL
        _ev("reject", 5, "alice@test", "2026-04-01T09:00:00Z"),
        _ev("accept", 5, "alice@test", "2026-04-01T10:00:00Z"),
        # issue 6: clean accept → PASS
        _ev("accept", 6, "bob@test", "2026-04-01T11:00:00Z"),
    ])

    report = run_check(tmp_path)

    assert report["status"] == "FAIL"
    assert len(report["violations"]) == 1
    assert report["violations"][0]["issue"] == 5
    assert report["violations"][0]["agent"] == "alice@test"


# ── (i) malformed JSONL line — skip, no crash ─────────────────────────────────


def test_spec_i_malformed_jsonl_skipped_no_crash(tmp_path: Path) -> None:
    hd = _history_dir(tmp_path)
    _write_jsonl(hd / "2026-04-01.jsonl", [
        _ev("reject", 30, "alice@test", "2026-04-01T09:00:00Z"),
        "}{this is not valid json at all",
        _ev("accept", 30, "bob@test", "2026-04-01T10:00:00Z"),  # different agent → no violation
    ])

    # Must not raise; malformed line is skipped, remaining events processed
    report = run_check(tmp_path)

    assert report["status"] == "PASS"
    assert report["stats"]["malformed_lines_skipped"] == 1
    assert report["stats"]["history_events_scanned"] == 2


# ── (j) issue number as string vs integer ─────────────────────────────────────


def test_spec_j_issue_number_string_vs_integer_normalized(tmp_path: Path) -> None:
    hd = _history_dir(tmp_path)
    # String "42" and integer 42 must identify the same issue
    _write_jsonl(hd / "2026-04-01.jsonl", [
        {"type": "reject", "issue": "42", "agent": "alice@test", "timestamp": "2026-04-01T09:00:00Z"},
        {"type": "accept", "issue": 42, "agent": "alice@test", "timestamp": "2026-04-01T10:00:00Z"},
    ])

    report = run_check(tmp_path)

    assert report["status"] == "FAIL"
    assert len(report["violations"]) == 1
    assert report["violations"][0]["issue"] == 42  # displayed as integer


# ── (k) reject → escrow_return → re-accept — still FAIL ──────────────────────


def test_spec_k_reject_return_reaccept_still_fails(tmp_path: Path) -> None:
    hd = _history_dir(tmp_path)
    # escrow_return does NOT clear the rejected state
    _write_jsonl(hd / "2026-04-01.jsonl", [
        _ev("reject", 50, "alice@test", "2026-04-01T09:00:00Z"),
        {"type": "escrow_return", "issue": 50, "timestamp": "2026-04-01T09:30:00Z"},
        _ev("accept", 50, "alice@test", "2026-04-01T10:00:00Z"),
    ])

    report = run_check(tmp_path)

    assert report["status"] == "FAIL"
    assert len(report["violations"]) == 1
    assert report["violations"][0]["agent"] == "alice@test"
    # reject_ts should reference the original reject, not any intermediate event
    assert "09:00:00" in report["violations"][0]["reject_ts"]


# ── (l) multiple rejects before payment — FAIL reported once ──────────────────


def test_spec_l_multiple_rejects_before_payment_reported_once(tmp_path: Path) -> None:
    hd = _history_dir(tmp_path)
    # Two reject events for the same pair before the payment; only one violation
    _write_jsonl(hd / "2026-04-01.jsonl", [
        _ev("reject", 60, "alice@test", "2026-04-01T08:00:00Z"),
        _ev("reject", 60, "alice@test", "2026-04-01T09:00:00Z"),
        _ev("accept", 60, "alice@test", "2026-04-01T10:00:00Z"),
    ])

    report = run_check(tmp_path)

    assert report["status"] == "FAIL"
    assert len(report["violations"]) == 1
    assert report["violations"][0]["issue"] == 60
    # reject_ts must reference the FIRST reject
    assert "08:00:00" in report["violations"][0]["reject_ts"]
    assert report["stats"]["reject_events_scanned"] == 2
