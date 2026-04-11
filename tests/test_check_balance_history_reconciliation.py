"""Tests for scripts/check_balance_history_reconciliation.py

Covers: happy path, drift detection, missing files, parse errors,
        economy_reset, deduplicated escrow_return, trajectory_mint formats,
        accept events, and agent-only debit semantics.
"""

import json
from pathlib import Path

import pytest

from scripts.check_balance_history_reconciliation import (
    _AGENT0,
    compute_balances_from_history,
    reconcile,
    run,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_balances(path: Path, agents: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "agents": agents}), encoding="utf-8")


def _write_history(history_dir: Path, filename: str, events: list[dict]) -> None:
    history_dir.mkdir(parents=True, exist_ok=True)
    lines = "\n".join(json.dumps(e) for e in events)
    (history_dir / filename).write_text(lines, encoding="utf-8")


# ---------------------------------------------------------------------------
# Test 1: happy path — balances match history exactly
# ---------------------------------------------------------------------------

def test_happy_path_all_pass(tmp_path: Path) -> None:
    history_dir = tmp_path / "ledger" / "history"
    _write_balances(
        tmp_path / "ledger" / "balances.json",
        {
            "alice@claude": {"balance": 50},
            "bob@codex": {"balance": 30},
        },
    )
    _write_history(
        history_dir,
        "2026-01-01.jsonl",
        [
            {"type": "payment", "agent": "alice@claude", "amount": 50},
            {"type": "payment", "agent": "bob@codex", "amount": 30},
        ],
    )

    result, passed = run(tmp_path)

    assert passed is True
    assert result["status"] == "PASS"
    checks = {c["agent"]: c for c in result["checks"]}
    assert checks["alice@claude"]["status"] == "PASS"
    assert checks["bob@codex"]["status"] == "PASS"
    assert "2 PASS" in result["summary"]


# ---------------------------------------------------------------------------
# Test 2: drift detection — direct balance edit without history event
# ---------------------------------------------------------------------------

def test_drift_detected(tmp_path: Path) -> None:
    history_dir = tmp_path / "ledger" / "history"
    # history says alice earned 50, but balance.json stores 100 (direct edit)
    _write_balances(
        tmp_path / "ledger" / "balances.json",
        {"alice@claude": {"balance": 100}},
    )
    _write_history(
        history_dir,
        "2026-01-01.jsonl",
        [{"type": "payment", "agent": "alice@claude", "amount": 50}],
    )

    result, passed = run(tmp_path)

    assert passed is False
    assert result["status"] == "FAIL"
    checks = {c["agent"]: c for c in result["checks"]}
    assert checks["alice@claude"]["status"] == "FAIL"
    assert checks["alice@claude"]["delta"] == -50  # computed(50) - stored(100) = -50
    assert "FAIL" in result["summary"]


# ---------------------------------------------------------------------------
# Test 3: missing balances.json — returns FAIL
# ---------------------------------------------------------------------------

def test_missing_balances_json(tmp_path: Path) -> None:
    # No ledger directory at all
    result, passed = run(tmp_path)

    assert passed is False
    assert result["status"] == "FAIL"
    assert "not found" in result["summary"]


# ---------------------------------------------------------------------------
# Test 4: missing history directory — treated as no history, agents with
#          non-zero balance should FAIL
# ---------------------------------------------------------------------------

def test_missing_history_dir_with_nonzero_balance(tmp_path: Path) -> None:
    _write_balances(
        tmp_path / "ledger" / "balances.json",
        {"alice@claude": {"balance": 100}},
    )
    # No history directory

    result, passed = run(tmp_path)

    assert passed is False
    assert result["status"] == "FAIL"
    checks = {c["agent"]: c for c in result["checks"]}
    assert checks["alice@claude"]["status"] == "FAIL"
    assert checks["alice@claude"]["computed"] == 0


# ---------------------------------------------------------------------------
# Test 5: JSONL parse error — malformed lines are skipped, valid lines processed
# ---------------------------------------------------------------------------

def test_jsonl_parse_error_skips_bad_lines(tmp_path: Path) -> None:
    history_dir = tmp_path / "ledger" / "history"
    _write_balances(
        tmp_path / "ledger" / "balances.json",
        {"alice@claude": {"balance": 50}},
    )
    # Mix of invalid and valid JSON lines
    history_dir.mkdir(parents=True, exist_ok=True)
    (history_dir / "2026-01-01.jsonl").write_text(
        "not-json\n"
        '{"type": "payment", "agent": "alice@claude", "amount": 50}\n'
        "{bad json\n",
        encoding="utf-8",
    )

    result, passed = run(tmp_path)

    assert passed is True
    assert result["status"] == "PASS"
    checks = {c["agent"]: c for c in result["checks"]}
    assert checks["alice@claude"]["computed"] == 50


# ---------------------------------------------------------------------------
# Test 6: agent in balances.json but zero history events — balance must be 0
# ---------------------------------------------------------------------------

def test_agent_with_no_history_events(tmp_path: Path) -> None:
    history_dir = tmp_path / "ledger" / "history"
    _write_balances(
        tmp_path / "ledger" / "balances.json",
        {
            "alice@claude": {"balance": 50},
            "ghost@codex": {"balance": 0},  # no history events at all
        },
    )
    _write_history(
        history_dir,
        "2026-01-01.jsonl",
        [{"type": "payment", "agent": "alice@claude", "amount": 50}],
    )

    result, passed = run(tmp_path)

    assert passed is True
    checks = {c["agent"]: c for c in result["checks"]}
    assert checks["ghost@codex"]["status"] == "PASS"
    assert checks["ghost@codex"]["computed"] == 0
    assert checks["ghost@codex"]["stored"] == 0


# ---------------------------------------------------------------------------
# Test 7: escrow_return deduplication — duplicate entries for same issue
#         are counted only once
# ---------------------------------------------------------------------------

def test_escrow_return_deduplication(tmp_path: Path) -> None:
    history_dir = tmp_path / "ledger" / "history"
    _write_balances(
        tmp_path / "ledger" / "balances.json",
        {
            # payment 100, escrow -30, escrow_return +30 (net 100)
            "alice@claude": {"balance": 100},
        },
    )
    _write_history(
        history_dir,
        "2026-01-01.jsonl",
        [
            {"type": "payment", "agent": "alice@claude", "amount": 100},
            {"type": "escrow", "agent": "alice@claude", "issue": 1, "amount": 30},
            # Two identical escrow_return entries for the same issue — only first counts
            {"type": "escrow_return", "agent": "alice@claude", "issue": 1, "amount": 30},
            {"type": "escrow_return", "agent": "alice@claude", "issue": 1, "amount": 30},
        ],
    )

    result, passed = run(tmp_path)

    assert passed is True
    assert result["status"] == "PASS"
    checks = {c["agent"]: c for c in result["checks"]}
    assert checks["alice@claude"]["status"] == "PASS"
    assert checks["alice@claude"]["computed"] == 100


# ---------------------------------------------------------------------------
# Test 8: trajectory_mint — both list format and single-agent format
# ---------------------------------------------------------------------------

def test_trajectory_mint_both_formats(tmp_path: Path) -> None:
    history_dir = tmp_path / "ledger" / "history"
    _write_balances(
        tmp_path / "ledger" / "balances.json",
        {
            # list format: alice=20, bob=10
            # single format: carol=22
            "alice@claude": {"balance": 20},
            "bob@codex": {"balance": 10},
            "carol@gemini": {"balance": 22},
        },
    )
    _write_history(
        history_dir,
        "2026-01-01.jsonl",
        [
            {
                "type": "trajectory_mint",
                "agents": ["alice@claude", "bob@codex"],
                "per_agent": [20, 10],
            },
            {
                "type": "trajectory_mint",
                "agent": "carol@gemini",
                "amount": 22,
            },
        ],
    )

    result, passed = run(tmp_path)

    assert passed is True
    assert result["status"] == "PASS"
    checks = {c["agent"]: c for c in result["checks"]}
    assert checks["alice@claude"]["computed"] == 20
    assert checks["bob@codex"]["computed"] == 10
    assert checks["carol@gemini"]["computed"] == 22


# ---------------------------------------------------------------------------
# Test 9: accept events credit the agent
# ---------------------------------------------------------------------------

def test_accept_event_credits_agent(tmp_path: Path) -> None:
    history_dir = tmp_path / "ledger" / "history"
    _write_balances(
        tmp_path / "ledger" / "balances.json",
        {"alice@claude": {"balance": 65}},
    )
    _write_history(
        history_dir,
        "2026-01-01.jsonl",
        [
            {"type": "payment", "agent": "alice@claude", "amount": 50},
            {"type": "accept", "agent": "alice@claude", "amount": 15, "issue": 42},
        ],
    )

    result, passed = run(tmp_path)

    assert passed is True
    checks = {c["agent"]: c for c in result["checks"]}
    assert checks["alice@claude"]["computed"] == 65


# ---------------------------------------------------------------------------
# Test 10: escrow with author field (not agent) — NOT counted as debit
# ---------------------------------------------------------------------------

def test_escrow_author_not_counted_as_debit(tmp_path: Path) -> None:
    history_dir = tmp_path / "ledger" / "history"
    # The escrow uses `author` field — by design this is not counted as a debit.
    # alice earns 50 and creates an escrow that uses `author`; her balance stays 50.
    _write_balances(
        tmp_path / "ledger" / "balances.json",
        {"alice@claude": {"balance": 50}},
    )
    _write_history(
        history_dir,
        "2026-01-01.jsonl",
        [
            {"type": "payment", "agent": "alice@claude", "amount": 50},
            {"type": "escrow", "author": "alice@claude", "issue": 7, "amount": 20},
        ],
    )

    result, passed = run(tmp_path)

    assert passed is True
    checks = {c["agent"]: c for c in result["checks"]}
    # author-format escrow is excluded from debits, so computed stays at 50
    assert checks["alice@claude"]["computed"] == 50
    assert checks["alice@claude"]["status"] == "PASS"


# ---------------------------------------------------------------------------
# Test 11: economy_reset — zeroes agents and adds wea_returned_to_agent0
# ---------------------------------------------------------------------------

def test_economy_reset_handling(tmp_path: Path) -> None:
    history_dir = tmp_path / "ledger" / "history"
    # alice earns 100, then reset zeros her; agent0 gets 100 returned.
    _write_balances(
        tmp_path / "ledger" / "balances.json",
        {
            "alice@claude": {"balance": 0},
            _AGENT0: {"balance": 10100},  # 10000 initial + 100 returned
        },
    )
    _write_history(
        history_dir,
        "2026-01-01.jsonl",
        [
            {"type": "mint", "agent": "alice@claude", "amount": 100},
            {
                "type": "economy_reset",
                "agents_zeroed": ["alice@claude"],
                "wea_returned_to_agent0": 100,
            },
        ],
    )

    result, passed = run(tmp_path)

    assert passed is True
    checks = {c["agent"]: c for c in result["checks"]}
    assert checks["alice@claude"]["computed"] == 0  # zeroed by reset
    # agent0 is SKIP due to known legacy issues, but computed includes the return
    assert checks[_AGENT0]["status"] == "SKIP"
    assert checks[_AGENT0]["computed"] == 10000 + 100  # initial + returned


# ---------------------------------------------------------------------------
# Test 12: overall status is PASS when only SKIPs (no FAIL)
# ---------------------------------------------------------------------------

def test_skip_does_not_cause_fail(tmp_path: Path) -> None:
    history_dir = tmp_path / "ledger" / "history"
    # agent0 has a delta but should be SKIP, not FAIL; overall should be PASS.
    _write_balances(
        tmp_path / "ledger" / "balances.json",
        {
            "alice@claude": {"balance": 50},
            _AGENT0: {"balance": 9000},  # intentionally different from computed
        },
    )
    _write_history(
        history_dir,
        "2026-01-01.jsonl",
        [{"type": "payment", "agent": "alice@claude", "amount": 50}],
    )

    result, passed = run(tmp_path)

    assert passed is True
    assert result["status"] == "PASS"
    checks = {c["agent"]: c for c in result["checks"]}
    assert checks[_AGENT0]["status"] == "SKIP"
    assert checks["alice@claude"]["status"] == "PASS"


# ---------------------------------------------------------------------------
# Test 13: escrow with agent field IS counted as debit
# ---------------------------------------------------------------------------

def test_escrow_agent_field_debit(tmp_path: Path) -> None:
    history_dir = tmp_path / "ledger" / "history"
    # alice earns 100, spends 30 via escrow (agent field) → balance 70
    _write_balances(
        tmp_path / "ledger" / "balances.json",
        {"alice@claude": {"balance": 70}},
    )
    _write_history(
        history_dir,
        "2026-01-01.jsonl",
        [
            {"type": "payment", "agent": "alice@claude", "amount": 100},
            {"type": "escrow", "agent": "alice@claude", "issue": 5, "amount": 30},
        ],
    )

    result, passed = run(tmp_path)

    assert passed is True
    checks = {c["agent"]: c for c in result["checks"]}
    assert checks["alice@claude"]["computed"] == 70
    assert checks["alice@claude"]["status"] == "PASS"


# ---------------------------------------------------------------------------
# Test 14: reversal with negative amount reduces balance
# ---------------------------------------------------------------------------

def test_reversal_reduces_balance(tmp_path: Path) -> None:
    history_dir = tmp_path / "ledger" / "history"
    # alice paid 50, then reversed -10 → net 40
    _write_balances(
        tmp_path / "ledger" / "balances.json",
        {"alice@claude": {"balance": 40}},
    )
    _write_history(
        history_dir,
        "2026-01-01.jsonl",
        [
            {"type": "payment", "agent": "alice@claude", "amount": 50},
            {"type": "reversal", "agent": "alice@claude", "amount": -10, "issue": 3},
        ],
    )

    result, passed = run(tmp_path)

    assert passed is True
    checks = {c["agent"]: c for c in result["checks"]}
    assert checks["alice@claude"]["computed"] == 40
    assert checks["alice@claude"]["status"] == "PASS"


# ---------------------------------------------------------------------------
# Test 15: multi-file history — events across multiple .jsonl files
# ---------------------------------------------------------------------------

def test_multi_file_history(tmp_path: Path) -> None:
    history_dir = tmp_path / "ledger" / "history"
    _write_balances(
        tmp_path / "ledger" / "balances.json",
        {"alice@claude": {"balance": 80}},
    )
    _write_history(
        history_dir,
        "2026-01-01.jsonl",
        [{"type": "payment", "agent": "alice@claude", "amount": 50}],
    )
    _write_history(
        history_dir,
        "2026-01-02.jsonl",
        [{"type": "mint", "agent": "alice@claude", "amount": 30}],
    )

    result, passed = run(tmp_path)

    assert passed is True
    checks = {c["agent"]: c for c in result["checks"]}
    assert checks["alice@claude"]["computed"] == 80
    assert checks["alice@claude"]["status"] == "PASS"


# ---------------------------------------------------------------------------
# Low-level unit tests for compute_balances_from_history
# ---------------------------------------------------------------------------


def test_compute_balances_empty_history() -> None:
    computed = compute_balances_from_history([])
    # Only agent0 has a non-zero initial balance
    assert computed[_AGENT0] == 10000
    # Any other agent would not appear in computed
    assert computed.get("alice@claude", 0) == 0


def test_reconcile_returns_correct_structure() -> None:
    balances = {"agents": {"alice@claude": {"balance": 50}}}
    computed = {"alice@claude": 50}
    checks = reconcile(balances, computed)
    assert len(checks) == 1
    assert checks[0]["status"] == "PASS"
    assert checks[0]["delta"] == 0


def test_reconcile_detects_mismatch() -> None:
    balances = {"agents": {"alice@claude": {"balance": 100}}}
    computed = {"alice@claude": 50}
    checks = reconcile(balances, computed)
    assert checks[0]["status"] == "FAIL"
    assert checks[0]["delta"] == -50  # computed(50) - stored(100)
