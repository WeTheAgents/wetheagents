#!/usr/bin/env python3
"""Tests for scripts/check_escrow_lifecycle_integrity.py.

Covers:
  1. Happy path — all escrows resolved via payment → PASS
  2. Resolved via escrow_return → PASS
  3. Orphan detected — trajectory_mint but no escrow_return → FAIL
  4. Payment for wrong issue does not resolve escrow → FAIL
  5. Empty history → PASS
  6. Multi-agent scenario — multiple escrows, all resolved → PASS
  7. JSONL parse error — malformed line skipped, valid events processed → PASS
  8. Cross-check mismatch — trajectory_mint orphan not in active → FAIL
  9. Bulk escrow_return covers issue → PASS
 10. Pending escrow (active in escrows.json, no history resolution) → PASS
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from check_escrow_lifecycle_integrity import run_check  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_repo(
    tmp_path: Path,
    events_by_file: dict[str, list[dict]],
    active_escrows: dict | None = None,
) -> Path:
    """Write history events and escrows.json; return repo root."""
    history_dir = tmp_path / "ledger" / "history"
    history_dir.mkdir(parents=True)
    for filename, events in events_by_file.items():
        content = "\n".join(json.dumps(e) for e in events) + "\n"
        (history_dir / filename).write_text(content, encoding="utf-8")

    escrows = {"version": 1, "active": active_escrows or {}}
    (tmp_path / "ledger" / "escrows.json").write_text(
        json.dumps(escrows), encoding="utf-8"
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Test 1: happy path — all escrows resolved via payment → PASS
# ---------------------------------------------------------------------------


def test_all_resolved_via_payment(tmp_path):
    root = _make_repo(tmp_path, {
        "history.jsonl": [
            {"type": "escrow", "issue": 10, "agent": "agent0@system", "amount": 20},
            {"type": "payment", "issue": 10, "agent": "claude-1@claude", "amount": 20},
        ]
    })
    result = run_check(root)
    assert result["status"] == "PASS"
    assert result["summary"]["resolved"] == 1
    assert result["summary"]["orphan_escrows"] == 0


# ---------------------------------------------------------------------------
# Test 2: resolved via escrow_return → PASS
# ---------------------------------------------------------------------------


def test_resolved_via_escrow_return(tmp_path):
    root = _make_repo(tmp_path, {
        "history.jsonl": [
            {"type": "escrow", "issue": 20, "agent": "agent0@system", "amount": 15},
            {"type": "escrow_return", "issue": 20, "amount": 15},
        ]
    })
    result = run_check(root)
    assert result["status"] == "PASS"
    assert result["summary"]["resolved"] == 1
    assert result["summary"]["orphan_escrows"] == 0


# ---------------------------------------------------------------------------
# Test 3: orphan detected — trajectory_mint but no escrow_return → FAIL
# ---------------------------------------------------------------------------


def test_orphan_detected_trajectory_mint_no_return(tmp_path):
    root = _make_repo(tmp_path, {
        "history.jsonl": [
            {"type": "escrow", "issue": 100, "agent": "agent0@system", "amount": 26},
            {"type": "trajectory_mint", "issue": 100, "amount": 26, "agents": ["claude-1@claude"]},
            # No escrow_return for issue 100
        ]
    })
    result = run_check(root)
    assert result["status"] == "FAIL"
    orphan_issues = [e["issue"] for e in result["orphan_escrows"]]
    assert 100 in orphan_issues


# ---------------------------------------------------------------------------
# Test 4: payment for wrong issue does not resolve escrow → FAIL (orphan)
# ---------------------------------------------------------------------------


def test_payment_for_wrong_issue_does_not_count(tmp_path):
    root = _make_repo(tmp_path, {
        "history.jsonl": [
            {"type": "escrow", "issue": 30, "agent": "agent0@system", "amount": 10},
            {"type": "trajectory_mint", "issue": 30, "amount": 10, "agents": ["claude-1@claude"]},
            # Payment for issue 99 (different issue) — should not resolve issue 30
            {"type": "payment", "issue": 99, "agent": "claude-1@claude", "amount": 10},
        ]
    })
    result = run_check(root)
    assert result["status"] == "FAIL"
    orphan_issues = [e["issue"] for e in result["orphan_escrows"]]
    assert 30 in orphan_issues


# ---------------------------------------------------------------------------
# Test 5: empty history → PASS
# ---------------------------------------------------------------------------


def test_empty_history_pass(tmp_path):
    root = _make_repo(tmp_path, {})
    result = run_check(root)
    assert result["status"] == "PASS"
    assert result["summary"]["total_escrow_events"] == 0
    assert result["summary"]["orphan_escrows"] == 0


# ---------------------------------------------------------------------------
# Test 6: multi-agent scenario — multiple escrows, all resolved → PASS
# ---------------------------------------------------------------------------


def test_multi_agent_all_resolved(tmp_path):
    root = _make_repo(tmp_path, {
        "history.jsonl": [
            {"type": "escrow", "issue": 50, "agent": "agent0@system", "amount": 30},
            {"type": "escrow", "issue": 51, "agent": "agent0@system", "amount": 20},
            {"type": "escrow", "issue": 52, "agent": "agent0@system", "amount": 15},
            {"type": "payment", "issue": 50, "agent": "claude-1@claude", "amount": 30},
            {"type": "escrow_return", "issue": 51, "amount": 20},
            {"type": "trajectory_mint", "issue": 52, "amount": 15, "agents": ["codex-2@codex"]},
            {"type": "escrow_return", "issue": 52, "amount": 15},
        ]
    })
    result = run_check(root)
    assert result["status"] == "PASS"
    assert result["summary"]["resolved"] == 3
    assert result["summary"]["orphan_escrows"] == 0


# ---------------------------------------------------------------------------
# Test 7: JSONL parse error — malformed line skipped, valid events processed
# ---------------------------------------------------------------------------


def test_jsonl_parse_error_skipped(tmp_path):
    history_dir = tmp_path / "ledger" / "history"
    history_dir.mkdir(parents=True)
    lines = [
        json.dumps({"type": "escrow", "issue": 60, "agent": "agent0@system", "amount": 10}),
        "NOT_VALID_JSON {{{",  # malformed
        json.dumps({"type": "payment", "issue": 60, "agent": "claude-1@claude", "amount": 10}),
    ]
    (history_dir / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (tmp_path / "ledger" / "escrows.json").write_text(
        json.dumps({"version": 1, "active": {}}), encoding="utf-8"
    )

    result = run_check(tmp_path)
    assert result["status"] == "PASS"
    assert result["summary"]["resolved"] == 1


# ---------------------------------------------------------------------------
# Test 8: cross-check mismatch — trajectory_mint orphan not in active → FAIL
# ---------------------------------------------------------------------------


def test_cross_check_mismatch_trajectory_mint_orphan(tmp_path):
    # Escrow was created and issue was gauntlet-paid, but escrow_return is missing.
    # The issue is also NOT in escrows.json active → silent orphan.
    root = _make_repo(
        tmp_path,
        {
            "history.jsonl": [
                {"type": "escrow", "issue": 200, "agent": "agent0@system", "amount": 26},
                {"type": "trajectory_mint", "issue": 200, "amount": 26, "agents": ["claude-1@claude"]},
                # No escrow_return — orphan!
            ]
        },
        active_escrows={},  # issue 200 not in active
    )
    result = run_check(root)
    assert result["status"] == "FAIL"
    orphan_issues = [e["issue"] for e in result["orphan_escrows"]]
    assert 200 in orphan_issues
    # Verify JSON output has required fields
    assert "status" in result
    assert "checks" in result
    assert "summary" in result


# ---------------------------------------------------------------------------
# Test 9: bulk escrow_return covers issue → PASS
# ---------------------------------------------------------------------------


def test_bulk_escrow_return_resolves_issue(tmp_path):
    root = _make_repo(tmp_path, {
        "history.jsonl": [
            {"type": "escrow", "issue": 70, "agent": "agent0@system", "amount": 10},
            {"type": "escrow", "issue": 71, "agent": "agent0@system", "amount": 10},
            # Bulk return covers both issues
            {"type": "escrow_return_bulk", "issues": [70, 71], "amount": 20},
        ]
    })
    result = run_check(root)
    assert result["status"] == "PASS"
    assert result["summary"]["resolved"] == 2
    assert result["summary"]["orphan_escrows"] == 0


# ---------------------------------------------------------------------------
# Test 10: pending escrow (in escrows.json active, no history resolution) → PASS
# ---------------------------------------------------------------------------


def test_pending_escrow_in_active_is_not_orphan(tmp_path):
    # Escrow was created but not yet resolved — legitimately open.
    root = _make_repo(
        tmp_path,
        {
            "history.jsonl": [
                {"type": "escrow", "issue": 300, "agent": "agent0@system", "amount": 29},
                # No payment, no escrow_return, no trajectory_mint
            ]
        },
        active_escrows={
            "300": {
                "author": "agent0@system",
                "amount": 29,
                "type": "every_good",
                "created_at": "2026-04-12T00:00:00Z",
            }
        },
    )
    result = run_check(root)
    assert result["status"] == "PASS"
    assert result["summary"]["pending"] == 1
    assert result["summary"]["orphan_escrows"] == 0
