#!/usr/bin/env python3
"""Tests for scripts/check_payment_completeness.py.

Covers:
  1. All verified + paid → pass
  2. Verification without payment → fail
  3. every_good: multiple agents paid per issue → pass
  4. Partial payment (one of two agents unpaid) → fail
  5. Empty history → pass
  6. Verification for issue with no escrow (rejected work) → pass (ignored)
  7. escrow_create type as well as escrow type recognised
  8. escrow_batch type: issue referenced in batch is considered escrowed
  9. Payment with wrong agent does not satisfy verification
 10. Multiple gaps reported together
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_payment_completeness.py"
SCRIPTS_DIR = SCRIPT.parent
sys.path.insert(0, str(SCRIPTS_DIR))

from check_payment_completeness import check_payment_completeness  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_repo(tmp_path: Path, events_by_file: dict[str, list[dict]]) -> Path:
    """Write history events to ledger/history/*.jsonl and return repo root."""
    history_dir = tmp_path / "ledger" / "history"
    history_dir.mkdir(parents=True)
    for filename, events in events_by_file.items():
        content = "\n".join(json.dumps(e) for e in events) + "\n"
        (history_dir / filename).write_text(content, encoding="utf-8")
    return tmp_path


def _run(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )


# ---------------------------------------------------------------------------
# Test 1: all verified + paid → pass
# ---------------------------------------------------------------------------


def test_all_verified_and_paid_passes(tmp_path: Path) -> None:
    """Every verification has a matching payment → no gaps → exit 0."""
    root = _make_repo(tmp_path, {
        "2026-01-01.jsonl": [
            {"type": "escrow", "issue": 10, "amount": 20},
            {"type": "verification", "issue": 10, "agent": "Alice@claude"},
            {"type": "payment", "issue": 10, "agent": "Alice@claude", "amount": 20},
        ]
    })
    gaps = check_payment_completeness(root)
    assert gaps == []
    result = _run(root)
    assert result.returncode == 0
    assert "OK" in result.stdout


# ---------------------------------------------------------------------------
# Test 2: verification without payment → fail
# ---------------------------------------------------------------------------


def test_verification_without_payment_fails(tmp_path: Path) -> None:
    """Verification exists but no payment → gap → exit 1."""
    root = _make_repo(tmp_path, {
        "2026-01-01.jsonl": [
            {"type": "escrow", "issue": 10, "amount": 20},
            {"type": "verification", "issue": 10, "agent": "Alice@claude"},
            # no payment
        ]
    })
    gaps = check_payment_completeness(root)
    assert len(gaps) == 1
    assert gaps[0]["issue"] == 10
    assert gaps[0]["agent"] == "Alice@claude"
    result = _run(root)
    assert result.returncode == 1
    assert "FAIL" in result.stdout


# ---------------------------------------------------------------------------
# Test 3: every_good — multiple agents each verified and paid → pass
# ---------------------------------------------------------------------------


def test_every_good_multiple_agents_all_paid_passes(tmp_path: Path) -> None:
    """every_good issue with 3 agents all verified and paid → pass."""
    root = _make_repo(tmp_path, {
        "2026-01-01.jsonl": [
            {"type": "escrow", "issue": 21, "amount": 15, "mechanic": "every_good"},
            {"type": "verification", "issue": 21, "agent": "Alpha@claude"},
            {"type": "verification", "issue": 21, "agent": "Beta@claude"},
            {"type": "verification", "issue": 21, "agent": "Gamma@claude"},
            {"type": "payment", "issue": 21, "agent": "Alpha@claude", "amount": 5},
            {"type": "payment", "issue": 21, "agent": "Beta@claude", "amount": 5},
            {"type": "payment", "issue": 21, "agent": "Gamma@claude", "amount": 5},
        ]
    })
    gaps = check_payment_completeness(root)
    assert gaps == []
    result = _run(root)
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# Test 4: partial payment — one of two agents unpaid → fail
# ---------------------------------------------------------------------------


def test_partial_payment_fails(tmp_path: Path) -> None:
    """Two verifications but only one paid → one gap."""
    root = _make_repo(tmp_path, {
        "2026-01-01.jsonl": [
            {"type": "escrow", "issue": 30, "amount": 20},
            {"type": "verification", "issue": 30, "agent": "Alice@claude"},
            {"type": "verification", "issue": 30, "agent": "Bob@claude"},
            {"type": "payment", "issue": 30, "agent": "Alice@claude", "amount": 10},
            # Bob never paid
        ]
    })
    gaps = check_payment_completeness(root)
    assert len(gaps) == 1
    assert gaps[0]["agent"] == "Bob@claude"
    result = _run(root)
    assert result.returncode == 1


# ---------------------------------------------------------------------------
# Test 5: empty history → pass
# ---------------------------------------------------------------------------


def test_empty_history_passes(tmp_path: Path) -> None:
    """No files in history → no verifications → no gaps."""
    (tmp_path / "ledger" / "history").mkdir(parents=True)
    gaps = check_payment_completeness(tmp_path)
    assert gaps == []
    result = _run(tmp_path)
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# Test 6: verification for issue with no escrow (rejected work) → ignored
# ---------------------------------------------------------------------------


def test_verification_for_unescrowed_issue_ignored(tmp_path: Path) -> None:
    """If the issue was never escrowed, the verification is rejected work → skip."""
    root = _make_repo(tmp_path, {
        "2026-01-01.jsonl": [
            # no escrow for issue 99
            {"type": "verification", "issue": 99, "agent": "Alice@claude"},
            # no payment either — but should be ignored
        ]
    })
    gaps = check_payment_completeness(root)
    assert gaps == []
    result = _run(root)
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# Test 7: escrow_create type is also recognised as escrowing an issue
# ---------------------------------------------------------------------------


def test_escrow_create_type_recognised(tmp_path: Path) -> None:
    """escrow_create (older event name) still counts as escrowing an issue."""
    root = _make_repo(tmp_path, {
        "2026-01-01.jsonl": [
            {"type": "escrow_create", "issue": 50, "amount": 10},
            {"type": "verification", "issue": 50, "agent": "Carol@cursor"},
            # no payment → should be a gap (issue IS escrowed)
        ]
    })
    gaps = check_payment_completeness(root)
    assert len(gaps) == 1
    assert gaps[0]["issue"] == 50


# ---------------------------------------------------------------------------
# Test 8: escrow_batch type — issue in batch is escrowed
# ---------------------------------------------------------------------------


def test_escrow_batch_recognised(tmp_path: Path) -> None:
    """escrow_batch with an issues list counts each issue as escrowed."""
    root = _make_repo(tmp_path, {
        "2026-01-01.jsonl": [
            {"type": "escrow_batch", "issues": [4, 5, 6], "total": 30},
            {"type": "verification", "issue": 5, "agent": "Dave@codex"},
            # no payment → gap (issue 5 IS in the batch)
        ]
    })
    gaps = check_payment_completeness(root)
    assert len(gaps) == 1
    assert gaps[0]["issue"] == 5


# ---------------------------------------------------------------------------
# Test 9: payment for wrong agent does not satisfy verification
# ---------------------------------------------------------------------------


def test_payment_wrong_agent_does_not_satisfy(tmp_path: Path) -> None:
    """Payment exists for a different agent on same issue → still a gap."""
    root = _make_repo(tmp_path, {
        "2026-01-01.jsonl": [
            {"type": "escrow", "issue": 77, "amount": 15},
            {"type": "verification", "issue": 77, "agent": "Alice@claude"},
            {"type": "payment", "issue": 77, "agent": "Bob@claude", "amount": 15},
            # Alice verified but Bob was paid
        ]
    })
    gaps = check_payment_completeness(root)
    assert len(gaps) == 1
    assert gaps[0]["agent"] == "Alice@claude"


# ---------------------------------------------------------------------------
# Test 10: multiple gaps reported together
# ---------------------------------------------------------------------------


def test_multiple_gaps_all_reported(tmp_path: Path) -> None:
    """Multiple verification gaps → all reported, exit 1."""
    root = _make_repo(tmp_path, {
        "2026-01-01.jsonl": [
            {"type": "escrow", "issue": 11, "amount": 10},
            {"type": "escrow", "issue": 22, "amount": 10},
            {"type": "verification", "issue": 11, "agent": "A@claude"},
            {"type": "verification", "issue": 22, "agent": "B@claude"},
            # neither paid
        ]
    })
    gaps = check_payment_completeness(root)
    assert len(gaps) == 2
    issues = {g["issue"] for g in gaps}
    assert issues == {11, 22}
    result = _run(root)
    assert result.returncode == 1
    assert "2 verification" in result.stdout


# ---------------------------------------------------------------------------
# Test 11: events spanning multiple files
# ---------------------------------------------------------------------------


def test_events_spanning_multiple_files(tmp_path: Path) -> None:
    """Escrow in one file, verification and payment in another → pass."""
    root = _make_repo(tmp_path, {
        "2026-01-01.jsonl": [
            {"type": "escrow", "issue": 55, "amount": 25},
        ],
        "2026-01-02.jsonl": [
            {"type": "verification", "issue": 55, "agent": "Eve@cursor"},
            {"type": "payment", "issue": 55, "agent": "Eve@cursor", "amount": 25},
        ],
    })
    gaps = check_payment_completeness(root)
    assert gaps == []
