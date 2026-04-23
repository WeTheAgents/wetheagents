#!/usr/bin/env python3
"""Adversarial tests for scripts/check_escrow_lifecycle_integrity.py.

Each test documents expected behavior and classifies the scenario as:
  DEFENDED  — the script handles it correctly
  KNOWN GAP — the script produces incorrect or unsafe results; document for future T1 slots
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from scripts import check_escrow_lifecycle_integrity as checker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _case_root(temp_repo: Path) -> Path:
    root = temp_repo / f"case_{uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _write_history(root: Path, filename: str, events: list[dict]) -> None:
    history_dir = root / "ledger" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(e) for e in events]
    (history_dir / filename).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_escrows(root: Path, active: dict) -> None:
    ledger_dir = root / "ledger"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    (ledger_dir / "escrows.json").write_text(
        json.dumps({"version": 1, "active": active}) + "\n", encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Adversarial 1: Phantom escrow — KNOWN GAP
# ---------------------------------------------------------------------------


def test_phantom_escrow_in_escrows_json_not_detected(temp_repo: Path) -> None:
    """KNOWN GAP: A phantom entry in escrows.json is invisible to the checker.

    Attack: Insert a WEA lock for issue 42 directly into escrows.json (amount=100)
    with no corresponding escrow_create in history. A checker that cross-references
    the two data sources would catch the phantom — WEA locked with no audit
    trail. This checker reads only ledger/history/*.jsonl; escrows.json is
    never opened.
    Result: PASS despite a WEA lock that has no history-backed justification.
    """
    root = _case_root(temp_repo)
    # Phantom lock in escrows.json — no history event backs it
    _write_escrows(root, {"42": {"amount": 100, "author": "Claude-1@claude", "type": "pod"}})
    # History is empty — no escrow_create for issue 42

    result = checker.run_check(root)

    # KNOWN GAP: checker ignores escrows.json entirely
    assert result["status"] == "PASS"
    assert result["summary"]["escrow_create_events_scanned"] == 0
    assert result["summary"]["failures"] == 0


# ---------------------------------------------------------------------------
# Adversarial 2: Orphan create — DEFENDED
# ---------------------------------------------------------------------------


def test_orphan_create_no_close_event_detected(temp_repo: Path) -> None:
    """DEFENDED: An escrow_create with no close event is flagged as no_close_event.

    Attack: Log an escrow_create for issue 42 in history but never log accept,
    escrow_return, or payment. A naive check might read only escrows.json for
    open entries and miss the orphaned history event if someone deleted the
    escrows.json entry manually without going through the proper close flow.
    The checker replays history end-to-end and catches the unclosed create
    regardless of escrows.json state.
    Result: FAIL with reason=no_close_event.
    """
    root = _case_root(temp_repo)
    _write_history(root, "2026-04-01.jsonl", [
        {"type": "escrow_create", "issue": 42, "amount": 100},
    ])
    # Deliberately no close event for issue 42

    result = checker.run_check(root)

    assert result["status"] == "FAIL"
    assert result["summary"]["failures"] == 1
    failures = [e for e in result["issues"] if e["status"] == "FAIL"]
    assert len(failures) == 1
    assert failures[0]["issue"] == 42
    assert failures[0]["reason"] == "no_close_event"


# ---------------------------------------------------------------------------
# Adversarial 3: Amount tampering — DEFENDED
# ---------------------------------------------------------------------------


def test_amount_tampering_close_amount_differs_flagged(temp_repo: Path) -> None:
    """DEFENDED: Close event with amount != create amount is flagged as amount_mismatch.

    Attack: An escrow_return records amount=50 for issue 42, but the original
    escrow_create logged amount=100. A naive existence check (does a close event
    exist for the issue?) would return PASS. The checker cross-validates the
    amounts in the matched create/close pair, catching the tampered return.
    Result: FAIL with reason=amount_mismatch.
    """
    root = _case_root(temp_repo)
    _write_history(root, "2026-04-01.jsonl", [
        {"type": "escrow_create", "issue": 42, "amount": 100},
        {"type": "escrow_return", "issue": 42, "amount": 50},  # tampered — should be 100
    ])

    result = checker.run_check(root)

    assert result["status"] == "FAIL"
    failures = [e for e in result["issues"] if e["status"] == "FAIL"]
    assert len(failures) == 1
    assert failures[0]["issue"] == 42
    assert failures[0]["reason"] == "amount_mismatch"
    assert failures[0]["create_amount"] == 100
    assert failures[0]["close_amount"] == 50


# ---------------------------------------------------------------------------
# Adversarial 4: Double create — KNOWN GAP
# ---------------------------------------------------------------------------


def test_double_create_paired_closes_passes_unchecked(temp_repo: Path) -> None:
    """KNOWN GAP: Two escrow_create events for the same issue pass when two
    matching close events follow.

    Attack: Log escrow_create twice for issue 42 (both amount=100), then log
    two escrow_return events (both amount=100). The checker stores open creates
    in a FIFO list per issue: each close pops the oldest unmatched create.
    With equal counts and matching amounts, all creates are paired — no
    remainder, no flag. The invariant "only one escrow per issue" is never
    enforced; the duplicate create is silently consumed.
    Result: PASS despite two escrow_create events for the same issue.
    """
    root = _case_root(temp_repo)
    _write_history(root, "2026-04-01.jsonl", [
        {"type": "escrow_create", "issue": 42, "amount": 100},
        {"type": "escrow_create", "issue": 42, "amount": 100},  # duplicate
        {"type": "escrow_return", "issue": 42, "amount": 100},
        {"type": "escrow_return", "issue": 42, "amount": 100},
    ])

    result = checker.run_check(root)

    # KNOWN GAP: FIFO matching exhausts both creates — no violation reported
    assert result["status"] == "PASS"
    assert result["summary"]["escrow_create_events_scanned"] == 2
    assert result["summary"]["failures"] == 0


# ---------------------------------------------------------------------------
# Adversarial 5: Stale type mismatch — KNOWN GAP
# ---------------------------------------------------------------------------


def test_stale_type_mismatch_not_detected(temp_repo: Path) -> None:
    """KNOWN GAP: Mechanic/type mismatch between escrows.json and history is not detected.

    Attack: escrows.json records issue 42 as type="winner_take_all", but the
    history escrow_create event has mechanic="pod". A cross-referencing checker
    would catch the inconsistency — the escrow was created under one mechanic
    but later re-labelled. This checker never opens escrows.json, and the
    `mechanic` field in history events is not validated; only issue, amount,
    and lifecycle ordering are inspected.
    Result: PASS despite conflicting type metadata across the two data sources.
    """
    root = _case_root(temp_repo)
    _write_escrows(root, {
        "42": {"amount": 100, "author": "agent0@system", "type": "winner_take_all"},
    })
    _write_history(root, "2026-04-01.jsonl", [
        # mechanic disagrees with escrows.json type — checker ignores both
        {"type": "escrow_create", "issue": 42, "amount": 100, "mechanic": "pod"},
        {"type": "escrow_return", "issue": 42, "amount": 100},
    ])

    result = checker.run_check(root)

    # KNOWN GAP: mechanic/type field never validated
    assert result["status"] == "PASS"
    assert result["summary"]["failures"] == 0


# ---------------------------------------------------------------------------
# Adversarial 6: Author mismatch — KNOWN GAP
# ---------------------------------------------------------------------------


def test_author_mismatch_not_detected(temp_repo: Path) -> None:
    """KNOWN GAP: Author mismatch between escrows.json and history escrow_create
    is not detected.

    Attack: escrows.json records issue 42 with author="agent0@system" (the only
    legitimate escrow creator), but the history escrow_create event lists
    author="Claude-1@claude" (an unauthorized worker). Spoofed authorship —
    a worker logging an escrow as if created by agent0 — goes completely
    undetected. The checker never reads escrows.json and does not inspect the
    `author` field in history events; only issue, amount, and event ordering
    are validated.
    Result: PASS despite mismatched authorship indicating a potential forgery.
    """
    root = _case_root(temp_repo)
    _write_escrows(root, {
        "42": {"amount": 100, "author": "agent0@system", "type": "pod"},
    })
    _write_history(root, "2026-04-01.jsonl", [
        # author forged — worker claims to be agent0
        {"type": "escrow_create", "issue": 42, "amount": 100, "author": "Claude-1@claude"},
        {"type": "escrow_return", "issue": 42, "amount": 100},
    ])

    result = checker.run_check(root)

    # KNOWN GAP: author field ignored in both history and escrows.json
    assert result["status"] == "PASS"
    assert result["summary"]["failures"] == 0
