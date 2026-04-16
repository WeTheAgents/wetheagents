"""Adversarial test suite for scripts/check_escrow_lifecycle_integrity.py.

T2S10 red-team: probes the lifecycle checker under hostile inputs to confirm
it cannot be tricked into a false PASS when orphan escrows exist.

All tests use tmp_path fixtures — no real ledger/ files are touched.

Documented gaps confirmed by tests below:
  GAP-1: Double-escrow same issue — only first escrow event tracked per issue;
          a second escrow (after a prior resolution) is silently dropped,
          leaving an orphaned escrow undetected → false PASS.
          FIX: count-based tracking in collect_events + classify_escrows.

  GAP-2: Phantom return cancels orphan — a forged escrow_return for an issue
          that also has a trajectory_mint converts an orphan classification to
          "resolved", yielding a false PASS. No fix applied: requires external
          history integrity (signed commits / pre-commit hook enforcement).

Design choices confirmed by tests (not bugs):
  - Non-gauntlet unresolved escrows (no trajectory_mint) → WARN/PASS, not FAIL.
  - Amount mismatch between escrow and payment is not checked.
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
    events: list[dict],
    active_escrows: dict | None = None,
    *,
    filename: str = "events.jsonl",
) -> Path:
    """Write a single JSONL history file and escrows.json under tmp_path."""
    history_dir = tmp_path / "ledger" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    content = "\n".join(json.dumps(e) for e in events)
    (history_dir / filename).write_text(content, encoding="utf-8")
    escrows = {"version": 1, "active": active_escrows or {}}
    (tmp_path / "ledger" / "escrows.json").write_text(
        json.dumps(escrows), encoding="utf-8"
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Test 1: Wrong-issue payment (no trajectory_mint) → unresolved WARN, not FAIL
# ---------------------------------------------------------------------------


def test_payment_wrong_issue_without_trajectory_mint_is_warn_not_fail(tmp_path):
    """Escrow for issue 1, payment for issue 2 only — no trajectory_mint.

    ADVERSARIAL FINDING: without trajectory_mint, the script classifies
    the unresolved escrow as 'unresolved' (WARN) and returns PASS, not FAIL.
    Non-gauntlet unresolved escrows do not trigger FAIL by design; only
    gauntlet-minted orphans (trajectory_mint present, no escrow_return) do.
    """
    repo = _make_repo(tmp_path, [
        {"type": "escrow", "issue": 1, "amount": 50, "agent": "agent0@system"},
        {"type": "payment", "issue": 2, "amount": 50, "agent": "claude-1@claude"},
    ])
    result = run_check(repo)
    # Design choice: unresolved without trajectory_mint → WARN (PASS), not FAIL
    assert result["status"] == "PASS"
    assert result["summary"]["unresolved_escrows"] == 1
    assert result["summary"]["orphan_escrows"] == 0


# ---------------------------------------------------------------------------
# Test 2: Wrong-issue escrow_return (no trajectory_mint) → unresolved WARN
# ---------------------------------------------------------------------------


def test_escrow_return_wrong_issue_no_trajectory_mint_is_warn(tmp_path):
    """Escrow for issue 3, escrow_return for issue 4 — no trajectory_mint.

    Same finding as Test 1: issue 3 is unresolved (PASS/WARN, not FAIL).
    The script only flags orphans when trajectory_mint is present for the issue.
    """
    repo = _make_repo(tmp_path, [
        {"type": "escrow", "issue": 3, "amount": 30, "agent": "agent0@system"},
        {"type": "escrow_return", "issue": 4, "amount": 30, "agent": "agent0@system"},
    ])
    result = run_check(repo)
    assert result["status"] == "PASS"
    assert result["summary"]["unresolved_escrows"] == 1
    assert result["summary"]["orphan_escrows"] == 0


# ---------------------------------------------------------------------------
# Test 3: Double escrow same issue — second escrow detected after GAP-1 fix
# ---------------------------------------------------------------------------


def test_two_escrows_same_issue_second_detected_after_fix(tmp_path):
    """Issue 5: escrow → escrow_return → NEW escrow across two files.

    GAP-1 (FIXED): Originally collect_events() stored only first-seen escrow
    per issue. The second escrow was silently dropped → false PASS.

    After fix (count-based tracking): escrow_count=2, resolution_count=1,
    unresolved_remaining=1 → second escrow classified as 'unresolved' (WARN).
    Result is still PASS (no trajectory_mint), but total_escrow_events=2
    and unresolved_escrows=1, exposing the second orphan.
    """
    history_dir = tmp_path / "ledger" / "history"
    history_dir.mkdir(parents=True)
    # File 1: original escrow + return (legitimately resolved)
    (history_dir / "001.jsonl").write_text(
        "\n".join([
            json.dumps({"type": "escrow", "issue": 5, "amount": 50, "agent": "agent0@system"}),
            json.dumps({"type": "escrow_return", "issue": 5, "amount": 50, "agent": "agent0@system"}),
        ]),
        encoding="utf-8",
    )
    # File 2: new escrow for same issue — never returned
    (history_dir / "002.jsonl").write_text(
        json.dumps({"type": "escrow", "issue": 5, "amount": 25, "agent": "agent0@system"}),
        encoding="utf-8",
    )
    (tmp_path / "ledger" / "escrows.json").write_text(
        json.dumps({"version": 1, "active": {}}), encoding="utf-8"
    )

    result = run_check(tmp_path)
    # After fix: second escrow detected as unresolved (WARN), not silently dropped
    assert result["status"] == "PASS"
    assert result["summary"]["total_escrow_events"] == 2  # both escrows counted
    assert result["summary"]["resolved"] == 1
    assert result["summary"]["unresolved_escrows"] == 1  # second escrow detected


# ---------------------------------------------------------------------------
# Test 4: Trajectory_mint does NOT count as escrow resolution → FAIL [MANDATORY]
# ---------------------------------------------------------------------------


def test_trajectory_mint_does_not_resolve_escrow(tmp_path):
    """Trajectory_mint event for issue 6 present, but no escrow_return → FAIL.

    Mandatory T2S10 case: gauntlet mints create fresh WEA for agents but do
    NOT return the founding escrow to agent0. Without an explicit escrow_return,
    the escrow is an orphan. Script must FAIL and identify issue 6.
    """
    repo = _make_repo(tmp_path, [
        {"type": "escrow", "issue": 6, "amount": 27, "agent": "agent0@system"},
        {"type": "trajectory_mint", "issue": 6, "team": ["claude-6@claude"], "amount": 27},
        # No escrow_return — orphan escrow
    ])
    result = run_check(repo)
    assert result["status"] == "FAIL"
    assert result["summary"]["orphan_escrows"] == 1
    orphan_issues = {o["issue"] for o in result["orphan_escrows"]}
    assert 6 in orphan_issues


# ---------------------------------------------------------------------------
# Test 5: Phantom escrow_return without prior escrow → graceful PASS
# ---------------------------------------------------------------------------


def test_phantom_return_no_prior_escrow_graceful(tmp_path):
    """escrow_return for issue 7 with no preceding escrow event — no crash.

    Script must not raise, must not classify anything.  return_issues gains
    issue 7, but since issue 7 has no escrow_events entry, nothing is output.
    """
    repo = _make_repo(tmp_path, [
        {"type": "escrow_return", "issue": 7, "amount": 10, "agent": "agent0@system"},
    ])
    result = run_check(repo)
    assert result["status"] == "PASS"
    assert result["summary"]["total_escrow_events"] == 0


# ---------------------------------------------------------------------------
# Test 6: Malformed JSON mid-file — logged, valid events still processed
# ---------------------------------------------------------------------------


def test_malformed_json_mid_file_continues_processing(tmp_path, capsys):
    """Bad JSON line sandwiched between valid events — no crash, WARNING emitted.

    Issue 8 has escrow + payment bracketing a corrupt line. Script must:
    (a) not crash, (b) log WARNING to stderr, (c) return PASS with resolved=1.
    """
    history_dir = tmp_path / "ledger" / "history"
    history_dir.mkdir(parents=True)
    (history_dir / "events.jsonl").write_text(
        json.dumps({"type": "escrow", "issue": 8, "amount": 20, "agent": "agent0@system"})
        + "\n{this is NOT valid JSON!!!\n"
        + json.dumps({"type": "payment", "issue": 8, "amount": 20, "agent": "claude-1@claude"}),
        encoding="utf-8",
    )
    (tmp_path / "ledger" / "escrows.json").write_text(
        json.dumps({"version": 1, "active": {}}), encoding="utf-8"
    )
    result = run_check(tmp_path)
    assert result["status"] == "PASS"
    assert result["summary"]["resolved"] == 1
    captured = capsys.readouterr()
    assert "WARNING" in captured.err


# ---------------------------------------------------------------------------
# Test 7: Resolved then new escrow same issue (single file) → GAP-1 fixed
# ---------------------------------------------------------------------------


def test_resolved_then_new_escrow_same_issue_detected(tmp_path):
    """Issue 9: escrow → escrow_return → NEW escrow (all in one JSONL file).

    GAP-1 (FIXED): Single file confirms the fix is ordering-independent.
    After fix: escrow_count=2, resolution_count=1, unresolved_remaining=1.
    The second orphan escrow for issue 9 is detected as unresolved (WARN).
    """
    repo = _make_repo(tmp_path, [
        {"type": "escrow", "issue": 9, "amount": 40, "agent": "agent0@system"},
        {"type": "escrow_return", "issue": 9, "amount": 40, "agent": "agent0@system"},
        {"type": "escrow", "issue": 9, "amount": 20, "agent": "agent0@system"},  # new orphan
    ])
    result = run_check(repo)
    # After fix: second escrow detected
    assert result["status"] == "PASS"
    assert result["summary"]["total_escrow_events"] == 2
    assert result["summary"]["resolved"] == 1
    assert result["summary"]["unresolved_escrows"] == 1


# ---------------------------------------------------------------------------
# Test 8: Amount mismatch escrow vs payment — not detected (design choice)
# ---------------------------------------------------------------------------


def test_amount_mismatch_escrow_payment_not_detected(tmp_path):
    """Escrow 50 WEA, payment 30 WEA → script returns PASS (no amount check).

    Documents design choice: the script verifies only the PRESENCE of a
    payment event for the issue, not that amounts match. Underpayment and
    overpayment both pass silently.
    """
    repo = _make_repo(tmp_path, [
        {"type": "escrow", "issue": 10, "amount": 50, "agent": "agent0@system"},
        {"type": "payment", "issue": 10, "amount": 30, "agent": "claude-1@claude"},
    ])
    result = run_check(repo)
    assert result["status"] == "PASS"
    assert result["summary"]["resolved"] == 1


# ---------------------------------------------------------------------------
# Test 9: Empty history → PASS with all zero counts
# ---------------------------------------------------------------------------


def test_empty_history_pass_zero_counts(tmp_path):
    """No events at all → PASS, all summary fields zero."""
    repo = _make_repo(tmp_path, [])
    result = run_check(repo)
    assert result["status"] == "PASS"
    assert result["summary"]["total_escrow_events"] == 0
    assert result["summary"]["resolved"] == 0
    assert result["summary"]["pending"] == 0
    assert result["summary"]["orphan_escrows"] == 0
    assert result["summary"]["unresolved_escrows"] == 0


# ---------------------------------------------------------------------------
# Test 10: Large scenario — 20 issues, 18 resolved, 2 orphans → FAIL
# ---------------------------------------------------------------------------


def test_large_scenario_two_orphans_detected(tmp_path):
    """20 issues: 18 resolved via payment, 2 orphans (trajectory_mint, no return).

    Scale correctness: script must report exactly 2 orphans (issues 19, 20)
    and correctly classify the 18 resolved issues.
    """
    events: list[dict] = []
    for i in range(1, 21):
        events.append({"type": "escrow", "issue": i, "amount": 20, "agent": "agent0@system"})
    for i in range(1, 19):
        events.append({"type": "payment", "issue": i, "amount": 20, "agent": "claude-1@claude"})
    # Issues 19 and 20: gauntlet-minted, no escrow_return → orphan
    events.append({"type": "trajectory_mint", "issue": 19, "team": ["claude-6@claude"], "amount": 20})
    events.append({"type": "trajectory_mint", "issue": 20, "team": ["claude-5@claude"], "amount": 20})

    repo = _make_repo(tmp_path, events)
    result = run_check(repo)
    assert result["status"] == "FAIL"
    assert result["summary"]["orphan_escrows"] == 2
    assert result["summary"]["resolved"] == 18
    orphan_issues = {o["issue"] for o in result["orphan_escrows"]}
    assert orphan_issues == {19, 20}


# ---------------------------------------------------------------------------
# Test 11: Compensating violations — phantom return cancels orphan [GAP-2]
# ---------------------------------------------------------------------------


def test_compensating_violations_phantom_return_cancels_orphan(tmp_path):
    """Issue 11: trajectory_mint (should be orphan) + phantom escrow_return → PASS.

    GAP-2 (UNFIXED): A forged escrow_return for the same issue as a
    trajectory_mint converts an orphan → resolved classification, yielding
    a false PASS. The escrow_return satisfies is_resolved without verifying
    the operation was legitimate.

    Compensating violations pattern: violation A (orphan from trajectory_mint)
    is masked by violation B (phantom return injected into JSONL). No fix
    applied — requires signed history or external integrity verification.
    """
    repo = _make_repo(tmp_path, [
        {"type": "escrow", "issue": 11, "amount": 27, "agent": "agent0@system"},
        {"type": "trajectory_mint", "issue": 11, "team": ["claude-6@claude"], "amount": 27},
        {"type": "escrow_return", "issue": 11, "amount": 27, "agent": "agent0@system"},  # phantom
    ])
    result = run_check(repo)
    # GAP-2: phantom return suppresses orphan detection → false PASS
    assert result["status"] == "PASS"
    assert result["summary"]["resolved"] == 1
    assert result["summary"]["orphan_escrows"] == 0


# ---------------------------------------------------------------------------
# Test 12: Bulk return partial coverage — unresolved issue still orphan
# ---------------------------------------------------------------------------


def test_bulk_return_partial_coverage_orphan_remains(tmp_path):
    """escrow_return_bulk covers issues 12 and 13 but not 14.

    Issue 14 has trajectory_mint and no individual return — must be FAIL.
    The bulk return must not accidentally resolve issue 14.
    """
    repo = _make_repo(tmp_path, [
        {"type": "escrow", "issue": 12, "amount": 25, "agent": "agent0@system"},
        {"type": "escrow", "issue": 13, "amount": 30, "agent": "agent0@system"},
        {"type": "escrow", "issue": 14, "amount": 28, "agent": "agent0@system"},
        {"type": "trajectory_mint", "issue": 14, "team": ["gemini-4@google"], "amount": 28},
        {"type": "escrow_return_bulk", "issues": [12, 13], "agent": "agent0@system"},
    ])
    result = run_check(repo)
    assert result["status"] == "FAIL"
    assert result["summary"]["resolved"] == 2
    assert result["summary"]["orphan_escrows"] == 1
    orphan_issues = {o["issue"] for o in result["orphan_escrows"]}
    assert 14 in orphan_issues


# ---------------------------------------------------------------------------
# Test 13: Active pending with trajectory_mint → classified as PENDING not ORPHAN
# ---------------------------------------------------------------------------


def test_active_pending_with_trajectory_mint_classified_as_pending(tmp_path):
    """Issue 15: in escrows.json active AND has trajectory_mint → PENDING.

    Priority order in classify_escrows: resolved > pending > orphan > unresolved.
    Active (pending) takes priority over orphan — the task is legitimately open.
    trajectory_mint does not override the pending classification.
    """
    repo = _make_repo(tmp_path, [
        {"type": "escrow", "issue": 15, "amount": 29, "agent": "agent0@system"},
        {"type": "trajectory_mint", "issue": 15, "team": ["claude-6@claude"], "amount": 29},
    ], active_escrows={"15": {"amount": 29, "author": "agent0@system"}})
    result = run_check(repo)
    assert result["status"] == "PASS"
    assert result["summary"]["pending"] == 1
    assert result["summary"]["orphan_escrows"] == 0
