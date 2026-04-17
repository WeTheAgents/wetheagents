"""Adversarial tests for scripts/check_balance_history_reconciliation.py

T2S9 red-team suite: probes the checker under hostile and edge-case conditions.
Covers tampering, history surplus, float truncation, malformed JSONL,
ghost agents, empty history, duplicate entries, multi-agent drift,
wrong event semantics, and a negative-amount escrow exploit.

All tests use tmp_path fixtures — no real ledger/ files are read.
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


def _write_history(history_dir: Path, filename: str, events: list) -> None:
    history_dir.mkdir(parents=True, exist_ok=True)
    lines = "\n".join(json.dumps(e) for e in events)
    (history_dir / filename).write_text(lines, encoding="utf-8")


# ---------------------------------------------------------------------------
# Test 1: Direct balance edit without history event → FAIL
# ---------------------------------------------------------------------------


def test_direct_balance_edit_detected(tmp_path: Path) -> None:
    """Balance manually bumped to 200 but history only accounts for 100.
    Simulates direct ledger tampering: stored > computed → FAIL."""
    _write_balances(
        tmp_path / "ledger" / "balances.json",
        {"alice@claude": {"balance": 200}},
    )
    _write_history(
        tmp_path / "ledger" / "history",
        "2026-01-01.jsonl",
        [{"type": "payment", "agent": "alice@claude", "amount": 100}],
    )

    result, passed = run(tmp_path)

    assert passed is False
    assert result["status"] == "FAIL"
    checks = {c["agent"]: c for c in result["checks"]}
    assert checks["alice@claude"]["status"] == "FAIL"
    assert checks["alice@claude"]["stored"] == 200
    assert checks["alice@claude"]["computed"] == 100
    # computed(100) - stored(200) = -100
    assert checks["alice@claude"]["delta"] == -100


# ---------------------------------------------------------------------------
# Test 2: Extra credit in history not reflected in balance → FAIL
# ---------------------------------------------------------------------------


def test_extra_history_credit_not_in_balance_fails(tmp_path: Path) -> None:
    """History records 200 WEA earned but balance.json shows only 100.
    Could indicate suppressed income or a partial history prune."""
    _write_balances(
        tmp_path / "ledger" / "balances.json",
        {"alice@claude": {"balance": 100}},
    )
    _write_history(
        tmp_path / "ledger" / "history",
        "2026-01-01.jsonl",
        [
            {"type": "payment", "agent": "alice@claude", "amount": 100},
            {"type": "mint", "agent": "alice@claude", "amount": 100},
        ],
    )

    result, passed = run(tmp_path)

    assert passed is False
    assert result["status"] == "FAIL"
    checks = {c["agent"]: c for c in result["checks"]}
    assert checks["alice@claude"]["status"] == "FAIL"
    assert checks["alice@claude"]["computed"] == 200
    # computed(200) - stored(100) = +100
    assert checks["alice@claude"]["delta"] == 100


# ---------------------------------------------------------------------------
# Test 3: Floating-point accumulation edge case
# ---------------------------------------------------------------------------


def test_float_amount_truncation_causes_drift(tmp_path: Path) -> None:
    """JSONL amounts can be floats. compute_balances_from_history() casts with
    int(), which truncates rather than rounds.
    Three payments of 33.4 → int(33.4)*3 = 99, not 100.
    Balance stored as 100 (naive expectation) → checker reports FAIL."""
    _write_balances(
        tmp_path / "ledger" / "balances.json",
        {"alice@claude": {"balance": 100}},
    )
    history_dir = tmp_path / "ledger" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    # Write raw JSONL with float amounts (json.dumps would round-trip fine,
    # so write the raw text to preserve the float literal)
    (history_dir / "2026-01-01.jsonl").write_text(
        '{"type": "payment", "agent": "alice@claude", "amount": 33.4}\n'
        '{"type": "payment", "agent": "alice@claude", "amount": 33.4}\n'
        '{"type": "payment", "agent": "alice@claude", "amount": 33.4}\n',
        encoding="utf-8",
    )

    result, passed = run(tmp_path)

    # int(33.4) = 33; 3 * 33 = 99; stored = 100 → drift = -1
    assert passed is False
    checks = {c["agent"]: c for c in result["checks"]}
    assert checks["alice@claude"]["computed"] == 99
    assert checks["alice@claude"]["stored"] == 100
    assert checks["alice@claude"]["delta"] == -1


# ---------------------------------------------------------------------------
# Test 4: Entirely malformed JSONL → must not crash
# ---------------------------------------------------------------------------


def test_all_malformed_jsonl_no_crash(tmp_path: Path) -> None:
    """A .jsonl file containing ONLY invalid JSON lines must not raise.
    Checker skips every bad line → effective history empty.
    Agent with non-zero stored balance must FAIL (computed 0 ≠ stored 50)."""
    _write_balances(
        tmp_path / "ledger" / "balances.json",
        {"alice@claude": {"balance": 50}},
    )
    history_dir = tmp_path / "ledger" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    (history_dir / "2026-01-01.jsonl").write_text(
        "this is not json\n"
        "{broken: 'syntax',\n"
        "another bad line\n"
        "   \n",  # whitespace-only line — also skipped
        encoding="utf-8",
    )

    # Must not raise; returns a normal result dict
    result, passed = run(tmp_path)

    assert passed is False  # computed 0 ≠ stored 50
    checks = {c["agent"]: c for c in result["checks"]}
    assert checks["alice@claude"]["computed"] == 0
    assert checks["alice@claude"]["status"] == "FAIL"


# ---------------------------------------------------------------------------
# Test 5: Agent in balances with zero history → PASS
# ---------------------------------------------------------------------------


def test_fresh_agent_zero_balance_zero_history_passes(tmp_path: Path) -> None:
    """Freshly registered agent: balance=0, no history events at all.
    Checker must confirm 0 == 0 and return PASS — onboarding must not fail."""
    _write_balances(
        tmp_path / "ledger" / "balances.json",
        {"newcomer@claude": {"balance": 0}},
    )
    # History dir exists but has no events for newcomer
    history_dir = tmp_path / "ledger" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    (history_dir / "2026-01-01.jsonl").write_text("", encoding="utf-8")

    result, passed = run(tmp_path)

    assert passed is True
    assert result["status"] == "PASS"
    checks = {c["agent"]: c for c in result["checks"]}
    assert checks["newcomer@claude"]["status"] == "PASS"
    assert checks["newcomer@claude"]["computed"] == 0
    assert checks["newcomer@claude"]["stored"] == 0


# ---------------------------------------------------------------------------
# Test 6: Agent in history but not in balances → FAIL
# ---------------------------------------------------------------------------


def test_ghost_agent_in_history_not_in_balances(tmp_path: Path) -> None:
    """ghost@test has payment events in history but no entry in balances.json.

    The reconciler must fail closed here: non-zero history for an agent with no
    stored balance entry is a real discrepancy, not a warning-only condition."""
    _write_balances(
        tmp_path / "ledger" / "balances.json",
        {"alice@claude": {"balance": 50}},
    )
    _write_history(
        tmp_path / "ledger" / "history",
        "2026-01-01.jsonl",
        [
            {"type": "payment", "agent": "alice@claude", "amount": 50},
            # ghost@test earns 100 but has no balances.json entry
            {"type": "payment", "agent": "ghost@test", "amount": 100},
        ],
    )

    result, passed = run(tmp_path)

    assert passed is False
    checks = {c["agent"]: c for c in result["checks"]}
    assert checks["ghost@test"]["status"] == "FAIL"
    assert checks["ghost@test"]["computed"] == 100
    assert checks["ghost@test"]["stored"] == 0


# ---------------------------------------------------------------------------
# Test 7: Empty history directory, balance=0 → PASS
# ---------------------------------------------------------------------------


def test_empty_history_dir_zero_balance_passes(tmp_path: Path) -> None:
    """History directory exists but contains no .jsonl files.
    Agent with balance=0 → computed 0 == stored 0 → PASS."""
    _write_balances(
        tmp_path / "ledger" / "balances.json",
        {"alice@claude": {"balance": 0}},
    )
    (tmp_path / "ledger" / "history").mkdir(parents=True, exist_ok=True)

    result, passed = run(tmp_path)

    assert passed is True
    assert result["status"] == "PASS"
    checks = {c["agent"]: c for c in result["checks"]}
    assert checks["alice@claude"]["status"] == "PASS"
    assert checks["alice@claude"]["computed"] == 0


# ---------------------------------------------------------------------------
# Test 8: Empty history directory, balance>0 → FAIL
# ---------------------------------------------------------------------------


def test_empty_history_dir_nonzero_balance_fails(tmp_path: Path) -> None:
    """History directory exists but is empty.
    Agent with balance=100 → computed 0 ≠ stored 100 → FAIL."""
    _write_balances(
        tmp_path / "ledger" / "balances.json",
        {"alice@claude": {"balance": 100}},
    )
    (tmp_path / "ledger" / "history").mkdir(parents=True, exist_ok=True)

    result, passed = run(tmp_path)

    assert passed is False
    assert result["status"] == "FAIL"
    checks = {c["agent"]: c for c in result["checks"]}
    assert checks["alice@claude"]["status"] == "FAIL"
    assert checks["alice@claude"]["computed"] == 0
    assert checks["alice@claude"]["stored"] == 100
    # computed(0) - stored(100) = -100
    assert checks["alice@claude"]["delta"] == -100


# ---------------------------------------------------------------------------
# Test 9: Duplicate JSONL entries → detect double-count
# ---------------------------------------------------------------------------


def test_duplicate_payment_entries_double_counted(tmp_path: Path) -> None:
    """Same payment event recorded twice (e.g., replay bug or import error).
    Unlike escrow_return, payment events have no deduplication: both are summed.
    Balance stored as single payment (50) → computed doubles to 100 → FAIL."""
    _write_balances(
        tmp_path / "ledger" / "balances.json",
        {"alice@claude": {"balance": 50}},
    )
    _write_history(
        tmp_path / "ledger" / "history",
        "2026-01-01.jsonl",
        [
            {"type": "payment", "agent": "alice@claude", "amount": 50},
            {"type": "payment", "agent": "alice@claude", "amount": 50},  # duplicate
        ],
    )

    result, passed = run(tmp_path)

    assert passed is False
    checks = {c["agent"]: c for c in result["checks"]}
    assert checks["alice@claude"]["computed"] == 100  # double-counted
    assert checks["alice@claude"]["stored"] == 50
    # computed(100) - stored(50) = +50
    assert checks["alice@claude"]["delta"] == 50
    assert checks["alice@claude"]["status"] == "FAIL"


# ---------------------------------------------------------------------------
# Test 10: Multi-agent drift → only the drifted agent is reported FAIL
# ---------------------------------------------------------------------------


def test_multi_agent_only_drifted_agent_flagged(tmp_path: Path) -> None:
    """Three agents: alice and carol reconcile correctly, bob has drift.
    Only bob appears as FAIL; summary counts must be exact."""
    _write_balances(
        tmp_path / "ledger" / "balances.json",
        {
            "alice@claude": {"balance": 50},
            "bob@codex": {"balance": 999},  # tampered — history credits only 70
            "carol@gemini": {"balance": 30},
        },
    )
    _write_history(
        tmp_path / "ledger" / "history",
        "2026-01-01.jsonl",
        [
            {"type": "payment", "agent": "alice@claude", "amount": 50},
            {"type": "payment", "agent": "bob@codex", "amount": 70},
            {"type": "payment", "agent": "carol@gemini", "amount": 30},
        ],
    )

    result, passed = run(tmp_path)

    assert passed is False
    checks = {c["agent"]: c for c in result["checks"]}
    assert checks["alice@claude"]["status"] == "PASS"
    assert checks["carol@gemini"]["status"] == "PASS"
    assert checks["bob@codex"]["status"] == "FAIL"
    # computed(70) - stored(999) = -929
    assert checks["bob@codex"]["delta"] == -929
    assert "2 PASS" in result["summary"]
    assert "1 FAIL" in result["summary"]


# ---------------------------------------------------------------------------
# Test 11: Wrong event type counted — escrow must NOT be treated as income
# ---------------------------------------------------------------------------


def test_escrow_counted_as_income_detected(tmp_path: Path) -> None:
    """Adversarial scenario: balance.json inflated as if escrow was a credit.
    alice earns 100 via payment, then creates escrow for 30 (a debit).
    Correct computed balance = 70.  Stored 130 (100 + 30 escrow as income) → FAIL."""
    _write_balances(
        tmp_path / "ledger" / "balances.json",
        {"alice@claude": {"balance": 130}},  # fraudulently inflated
    )
    _write_history(
        tmp_path / "ledger" / "history",
        "2026-01-01.jsonl",
        [
            {"type": "payment", "agent": "alice@claude", "amount": 100},
            {"type": "escrow", "agent": "alice@claude", "issue": 5, "amount": 30},
        ],
    )

    result, passed = run(tmp_path)

    assert passed is False
    checks = {c["agent"]: c for c in result["checks"]}
    assert checks["alice@claude"]["status"] == "FAIL"
    # escrow is a debit: 100 - 30 = 70
    assert checks["alice@claude"]["computed"] == 70
    # computed(70) - stored(130) = -60
    assert checks["alice@claude"]["delta"] == -60


# ---------------------------------------------------------------------------
# Test 12 (bonus): Negative escrow amount acts as a stealth credit
# ---------------------------------------------------------------------------


def test_negative_escrow_amount_acts_as_credit(tmp_path: Path) -> None:
    """ADVERSARIAL FINDING: escrow with amount=-50 causes
    balance[agent] -= -50  →  balance[agent] += 50 (unintended credit).
    If balance.json is set to match this inflation (150), checker returns PASS.
    This documents a gap: negative-amount escrow events silently inflate
    balances and are undetectable when the stored balance is adjusted to match."""
    _write_balances(
        tmp_path / "ledger" / "balances.json",
        {"alice@claude": {"balance": 150}},  # inflated via negative-escrow exploit
    )
    _write_history(
        tmp_path / "ledger" / "history",
        "2026-01-01.jsonl",
        [
            {"type": "payment", "agent": "alice@claude", "amount": 100},
            # Negative escrow: balance[agent] -= -50  →  +50 (exploit)
            {"type": "escrow", "agent": "alice@claude", "issue": 9, "amount": -50},
        ],
    )

    result, passed = run(tmp_path)

    # Checker computes: 100 - (-50) = 150 == stored 150 → PASS
    # ADVERSARIAL FINDING: negative-amount escrow exploits are undetectable
    # when balance.json is also set to the inflated value.
    assert passed is True  # gap: negative-escrow exploit goes undetected
    checks = {c["agent"]: c for c in result["checks"]}
    assert checks["alice@claude"]["computed"] == 150
    assert checks["alice@claude"]["status"] == "PASS"
