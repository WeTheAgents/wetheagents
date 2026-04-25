"""Boundary-spec tests for scripts/check_escrow_ledger_history_consistency.py.

The checker detects two anomalies in active escrows:
  - Phantom: active in escrows.json but no escrow_create event found in history
  - Zombie:  active in escrows.json and a close event (payment/accept/reject/
             escrow_return) was found in history — the escrow should have been
             released

run_check(root) reads two sources:
  - ledger/escrows.json  → active.keys() are the issues to audit
  - ledger/history/*.jsonl → scanned for escrow_create + close events

All test fixtures write real files to tmp_path.

## Gaps

GAP-1  Double classification — an active escrow whose issue appears in a close
       event but has NO corresponding escrow_create event is classified as BOTH
       phantom AND zombie.  The report emits it in both lists with no indication
       of overlap.  Consumers deduplicating on status=FAIL may not notice the
       double-count.
       Severity: LOW — FAIL status is still correct; only the report detail is
       slightly misleading.
       See test_gap1_close_without_create_double_classified.
"""
from __future__ import annotations

import json
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from check_escrow_ledger_history_consistency import run_check


# ── helpers ───────────────────────────────────────────────────────────────────

def _write_escrows(tmp_path: Path, active: dict) -> None:
    ledger = tmp_path / "ledger"
    ledger.mkdir(parents=True, exist_ok=True)
    (ledger / "escrows.json").write_text(
        json.dumps({"active": active}), encoding="utf-8"
    )


def _write_jsonl(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(e) for e in events) + "\n",
        encoding="utf-8",
    )


def _history(tmp_path: Path) -> Path:
    p = tmp_path / "ledger" / "history"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _create(issue: int | str) -> dict:
    return {"type": "escrow_create", "issue": issue}


def _close(issue: int | str, kind: str = "escrow_return") -> dict:
    return {"type": kind, "issue": issue}


# ── 1. Valid escrow — create in history, no close ─────────────────────────────
# The escrow for issue 100 is active.  A history create event exists and no
# close event (payment / accept / reject / escrow_return) appears.  The checker
# finds issue 100 in creates but not in closes → neither phantom nor zombie.
#
# Decision table:
# | active issues | creates | closes | phantom | zombie | expected |
# |---------------|---------|--------|---------|--------|----------|
# | {100}         | {100}   | {}     | {}      | {}     | PASS     |


def test_case1_valid_escrow_create_no_close(tmp_path: Path) -> None:
    """Active escrow with escrow_create and no close event → PASS."""
    _write_escrows(tmp_path, {"100": {"amount": 10}})
    _write_jsonl(_history(tmp_path) / "2026-04-24.jsonl", [_create(100)])

    result = run_check(tmp_path)

    assert result["status"] == "PASS"
    assert result["phantom_issues"] == []
    assert result["zombie_issues"] == []
    assert result["total_active_escrows"] == 1


# ── 2. Phantom escrow — active, no create event anywhere ──────────────────────
# Issue 200 is active in escrows.json.  No history file contains an
# escrow_create for issue 200.  The checker computes phantom = active - creates
# → {200}.
#
# Decision table:
# | active issues | creates | closes | phantom | zombie | expected |
# |---------------|---------|--------|---------|--------|----------|
# | {200}         | {}      | {}     | {200}   | {}     | FAIL     |


def test_case2_phantom_escrow_no_create(tmp_path: Path) -> None:
    """Active escrow with no escrow_create event anywhere → FAIL (phantom)."""
    _write_escrows(tmp_path, {"200": {"amount": 5}})
    _history(tmp_path)  # create empty history dir

    result = run_check(tmp_path)

    assert result["status"] == "FAIL"
    assert result["phantom_issues"] == ["200"]
    assert result["zombie_issues"] == []
    assert result["phantom_count"] == 1
    assert result["zombie_count"] == 0


# ── 3. Zombie escrow — create found AND close event found ─────────────────────
# Issue 300 is active in escrows.json.  History contains both an escrow_create
# (the escrow was legitimately opened) and an escrow_return (it was released).
# Because the escrow is still active, this is a zombie: the ledger thinks the
# escrow is live but history says it was returned.
#
# Decision table:
# | active issues | creates | closes | phantom | zombie | expected |
# |---------------|---------|--------|---------|--------|----------|
# | {300}         | {300}   | {300}  | {}      | {300}  | FAIL     |


def test_case3_zombie_escrow_create_and_close_same_file(tmp_path: Path) -> None:
    """Active escrow with both escrow_create and escrow_return in history → FAIL (zombie)."""
    _write_escrows(tmp_path, {"300": {"amount": 20}})
    _write_jsonl(
        _history(tmp_path) / "2026-04-24.jsonl",
        [_create(300), _close(300, "escrow_return")],
    )

    result = run_check(tmp_path)

    assert result["status"] == "FAIL"
    assert result["zombie_issues"] == ["300"]
    assert result["phantom_issues"] == []
    assert result["zombie_count"] == 1


def test_case3b_zombie_detected_via_payment_event(tmp_path: Path) -> None:
    """Close event of kind 'payment' also classifies issue as zombie → FAIL."""
    _write_escrows(tmp_path, {"301": {"amount": 15}})
    _write_jsonl(
        _history(tmp_path) / "2026-04-24.jsonl",
        [_create(301), _close(301, "payment")],
    )

    result = run_check(tmp_path)

    assert result["status"] == "FAIL"
    assert result["zombie_issues"] == ["301"]


# ── 4. Zombie in different file — create and close in separate .jsonl ─────────
# Issue 400 is active.  The escrow_create lives in 2026-04-20.jsonl and the
# escrow_return in 2026-04-21.jsonl.  _index_history_events iterates sorted
# filenames, so both files are read; the sets union across files.
#
# Decision table:
# | active issues | 2026-04-20.jsonl  | 2026-04-21.jsonl  | creates | closes | phantom | zombie | expected |
# |---------------|-------------------|-------------------|---------|--------|---------|--------|----------|
# | {400}         | escrow_create(400)| escrow_return(400)| {400}   | {400}  | {}      | {400}  | FAIL     |


def test_case4_zombie_create_and_close_different_files(tmp_path: Path) -> None:
    """escrow_create in one file, escrow_return in a later file → FAIL (zombie, cross-file)."""
    _write_escrows(tmp_path, {"400": {"amount": 30}})
    hist = _history(tmp_path)
    _write_jsonl(hist / "2026-04-20.jsonl", [_create(400)])
    _write_jsonl(hist / "2026-04-21.jsonl", [_close(400, "escrow_return")])

    result = run_check(tmp_path)

    assert result["status"] == "FAIL"
    assert result["zombie_issues"] == ["400"]
    assert result["phantom_issues"] == []


# ── 5. String vs integer issue key normalization ──────────────────────────────
# escrows.json uses the string key "800".  The history escrow_create event uses
# the integer 800.  _normalize_issue converts both to "800", so the sets
# compare equal → no phantom, no zombie.
#
# Decision table:
# | active key | history issue type | normalized active | normalized creates | phantom | expected |
# |------------|--------------------|-------------------|--------------------|---------|----------|
# | "800" (str)| 800 (int)          | "800"             | "800"              | {}      | PASS     |


def test_case5_string_vs_integer_key_normalization(tmp_path: Path) -> None:
    """escrows.json key '800' (str) matches history event issue=800 (int) → PASS."""
    _write_escrows(tmp_path, {"800": {"amount": 52}})
    _write_jsonl(
        _history(tmp_path) / "2026-04-25.jsonl",
        [{"type": "escrow_create", "issue": 800}],  # integer, not string
    )

    result = run_check(tmp_path)

    assert result["status"] == "PASS"
    assert result["phantom_issues"] == []
    assert result["zombie_issues"] == []


# ── 6. No history directory — missing or empty ────────────────────────────────
# When ledger/history/ does not exist, _index_history_events returns empty sets.
# If there are also no active escrows, both phantom and zombie sets are empty.
# If there ARE active escrows, they would all be phantoms (no create events).
# The sub-case of zero active escrows + no history dir is the "empty system" PASS.
#
# Decision table:
# | active issues | history dir state | creates | closes | phantom | zombie | expected |
# |---------------|-------------------|---------|--------|---------|--------|----------|
# | {}            | does not exist    | {}      | {}     | {}      | {}     | PASS     |
# | {}            | exists, empty     | {}      | {}     | {}      | {}     | PASS     |


def test_case6_no_history_directory_no_active_escrows(tmp_path: Path) -> None:
    """No history/ dir and no active escrows → PASS (empty system)."""
    _write_escrows(tmp_path, {})
    # do not create ledger/history/ at all

    result = run_check(tmp_path)

    assert result["status"] == "PASS"
    assert result["phantom_issues"] == []
    assert result["zombie_issues"] == []
    assert result["total_active_escrows"] == 0


def test_case6b_empty_history_dir_no_active_escrows(tmp_path: Path) -> None:
    """ledger/history/ exists but is empty, no active escrows → PASS."""
    _write_escrows(tmp_path, {})
    _history(tmp_path)  # create the directory, leave it empty

    result = run_check(tmp_path)

    assert result["status"] == "PASS"
    assert result["phantom_issues"] == []
    assert result["total_active_escrows"] == 0


def test_case6c_missing_history_missing_escrows_json(tmp_path: Path) -> None:
    """Neither escrows.json nor history/ exists → defaults to empty active → PASS."""
    # nothing written — run_check defaults escrows to {"active": {}}
    result = run_check(tmp_path)

    assert result["status"] == "PASS"
    assert result["total_active_escrows"] == 0


def test_case6d_active_escrows_no_history_dir_are_phantoms(tmp_path: Path) -> None:
    """Active escrow with no history dir at all → FAIL (phantom, not silently PASS)."""
    _write_escrows(tmp_path, {"700": {"amount": 5}})
    # do not create ledger/history/

    result = run_check(tmp_path)

    # 700 has no create event → phantom
    assert result["status"] == "FAIL"
    assert result["phantom_issues"] == ["700"]


# ── 7. Multiple active escrows — one phantom, rest valid ──────────────────────
# Issues 501, 502, 503 are all active.  History has escrow_create for 501 and
# 502 but not for 503.  Only 503 should appear in phantom_issues.
#
# Decision table:
# | active issues   | creates      | closes | phantom | zombie | expected |
# |-----------------|--------------|--------|---------|--------|----------|
# | {501, 502, 503} | {501, 502}   | {}     | {503}   | {}     | FAIL     |


def test_case7_multiple_escrows_one_phantom(tmp_path: Path) -> None:
    """Three active escrows, one without create event → FAIL, only phantom reported."""
    _write_escrows(tmp_path, {
        "501": {"amount": 10},
        "502": {"amount": 10},
        "503": {"amount": 10},
    })
    _write_jsonl(
        _history(tmp_path) / "2026-04-24.jsonl",
        [_create(501), _create(502)],
    )

    result = run_check(tmp_path)

    assert result["status"] == "FAIL"
    assert result["phantom_issues"] == ["503"]
    assert result["zombie_issues"] == []
    assert result["phantom_count"] == 1
    assert result["zombie_count"] == 0
    assert result["total_active_escrows"] == 3


# ── GAP-1 demonstration — double classification ───────────────────────────────
# An active escrow has a close event in history but NO create event.  This
# scenario (e.g., a record-keeping gap) causes the issue to land in BOTH
# phantom_issues (active - creates = {600}) AND zombie_issues (active ∩ closes
# = {600}).  The FAIL status is correct, but the double-reporting is unexpected.
#
# Severity: LOW — FAIL is the right outcome; however, a caller iterating both
# lists may count the issue twice or produce confusing error messages.
#
# Decision table:
# | active issues | creates | closes | phantom | zombie | expected status |
# |---------------|---------|--------|---------|--------|-----------------|
# | {600}         | {}      | {600}  | {600}   | {600}  | FAIL (double)   |


def test_gap1_close_without_create_double_classified(tmp_path: Path) -> None:
    """Active escrow with close event but no create → appears in BOTH phantom and zombie lists."""
    _write_escrows(tmp_path, {"600": {"amount": 8}})
    _write_jsonl(
        _history(tmp_path) / "2026-04-24.jsonl",
        [_close(600, "escrow_return")],  # no escrow_create for 600
    )

    result = run_check(tmp_path)

    # FAIL status is correct
    assert result["status"] == "FAIL"
    # GAP-1: issue 600 appears in both lists simultaneously
    assert "600" in result["phantom_issues"]
    assert "600" in result["zombie_issues"]
