"""Adversarial tests for scripts/check_total_earned_spent_consistency.py.

Seven adversarial scenarios from T2S40 Issue #854:
  1. Event aliasing — pre-rename payment does not silently satisfy new agent's counter
  2. agent0 exclusion bypass — agent0 escrow_create spend never triggers a violation
  3. Dual-recipient mint — each recipient credited once from per_agent, never doubled
  4. Fractional amounts — float amount=0.5 truncated to int 0, no false violation
  5. Many small payments — 100 accept events of 1 WEA accumulate correctly to 100
  6. Negative stored value — corrupted total_earned=-1 is caught as VIOLATION
  7. All-zeros agent — zero stored + no history = PASS
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from check_total_earned_spent_consistency import (  # noqa: E402
    check_consistency,
    compute_earned_spent,
    run,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stored(total_earned: int = 0, total_spent: int = 0) -> dict[str, Any]:
    return {
        "balance": total_earned - total_spent,
        "total_earned": total_earned,
        "total_spent": total_spent,
    }


def _write_ledger(
    tmp_path: Path,
    agents: dict[str, Any],
    history_lines: list[str] | None = None,
) -> None:
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    history_dir = ledger_dir / "history"
    history_dir.mkdir()
    balances = {"version": 1, "agents": agents}
    (ledger_dir / "balances.json").write_text(json.dumps(balances), encoding="utf-8")
    if history_lines:
        content = "\n".join(history_lines) + "\n"
        (history_dir / "2026-01-01.jsonl").write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Scenario 1: Event aliasing — pre-rename ID in history, new ID in balances
# ---------------------------------------------------------------------------
# When an agent is renamed (e.g. claude-old@x → claude-new@x), history events
# remain under the old ID.  The checker must NOT silently pass the new agent's
# stored counter — it must flag a VIOLATION for the new ID and emit a WARNING
# for the orphaned old ID.
# ---------------------------------------------------------------------------


class TestEventAliasing:
    def test_pre_rename_payment_does_not_satisfy_new_agent_counter(
        self, tmp_path: Path
    ) -> None:
        """Payment under old-id@x must not count toward new-id@x's stored total_earned."""
        _write_ledger(
            tmp_path,
            agents={"new-id@x": _stored(total_earned=50, total_spent=0)},
            history_lines=[
                json.dumps({"type": "payment", "agent": "old-id@x", "amount": 50}),
            ],
        )
        result, passed = run(tmp_path)
        assert not passed, (
            "Pre-rename payment must not silently satisfy the new agent's stored counter"
        )
        violation_agents = {v["agent"] for v in result["violations"]}
        assert "new-id@x" in violation_agents, (
            "new-id@x has stored=50 but computed=0; must be a VIOLATION"
        )

    def test_pre_rename_old_id_is_warning_not_violation(
        self, tmp_path: Path
    ) -> None:
        """The orphaned old ID (in history, absent from balances) must emit a WARNING."""
        _write_ledger(
            tmp_path,
            agents={"new-id@x": _stored(total_earned=50, total_spent=0)},
            history_lines=[
                json.dumps({"type": "payment", "agent": "old-id@x", "amount": 50}),
            ],
        )
        result, _ = run(tmp_path)
        warning_agents = {w["agent"] for w in result["warnings"]}
        assert "old-id@x" in warning_agents, (
            "old-id@x is in history with non-zero earned but absent from balances; must be WARNING"
        )

    def test_correct_id_in_history_and_stored_passes(
        self, tmp_path: Path
    ) -> None:
        """Same ID in history and stored passes (control case for aliasing scenario)."""
        _write_ledger(
            tmp_path,
            agents={"new-id@x": _stored(total_earned=50, total_spent=0)},
            history_lines=[
                json.dumps({"type": "payment", "agent": "new-id@x", "amount": 50}),
            ],
        )
        result, passed = run(tmp_path)
        assert passed
        assert result["violations"] == []


# ---------------------------------------------------------------------------
# Scenario 2: agent0 exclusion bypass
# ---------------------------------------------------------------------------
# agent0@system creates escrow_create events (spending WEA).  The checker
# computes spent["agent0@system"] = N from those events, but check_consistency
# skips agent0 entirely — no violation must appear regardless of how large
# the mismatch between computed and stored is.
# ---------------------------------------------------------------------------


class TestAgent0ExclusionBypass:
    def test_agent0_escrow_create_does_not_cause_violation(self) -> None:
        """Large agent0 escrow_create spend must not surface as a violation."""
        events = [
            {"type": "escrow_create", "author": "agent0@system", "amount": 500, "issue": 1},
            {"type": "escrow_create", "author": "agent0@system", "amount": 300, "issue": 2},
        ]
        earned, spent = compute_earned_spent(events)
        # computed spent["agent0@system"] = 800; stored says 0 — a huge mismatch
        stored = {"agent0@system": _stored(total_earned=0, total_spent=0)}
        status, violations, _, _ = check_consistency(stored, earned, spent)
        assert status == "PASS", "agent0 spend mismatch must be silently skipped"
        assert all(v["agent"] != "agent0@system" for v in violations)

    def test_agent0_mismatch_does_not_affect_other_agents(
        self, tmp_path: Path
    ) -> None:
        """agent0 exclusion must not corrupt the check for co-present legitimate agents."""
        _write_ledger(
            tmp_path,
            agents={
                "agent0@system": _stored(total_earned=0, total_spent=9999),
                "alice@x": _stored(total_earned=50, total_spent=0),
            },
            history_lines=[
                json.dumps(
                    {"type": "escrow_create", "author": "agent0@system", "amount": 100, "issue": 1}
                ),
                json.dumps({"type": "payment", "agent": "alice@x", "amount": 50}),
            ],
        )
        result, passed = run(tmp_path)
        # alice@x is consistent; agent0 exclusion must not infect alice's check
        assert passed, "alice@x is consistent and must not be flagged"
        assert all(v["agent"] != "agent0@system" for v in result["violations"])
        assert result["violations"] == []

    def test_agent0_not_present_in_stored_and_not_in_history_passes(self) -> None:
        """agent0 absent from both stored and history must not appear in violations."""
        stored: dict[str, Any] = {}
        status, violations, _, _ = check_consistency(stored, {}, {})
        assert status == "PASS"
        assert all(v["agent"] != "agent0@system" for v in violations)


# ---------------------------------------------------------------------------
# Scenario 3: Dual-recipient mint — no double-credit
# ---------------------------------------------------------------------------
# trajectory_mint with agents=["alice@x", "bob@x"] and per_agent=[30, 30]
# must credit alice exactly 30 and bob exactly 30.  Storing total_earned=60
# for either agent (the full mint amount) must be caught as a VIOLATION.
# ---------------------------------------------------------------------------


class TestDualRecipientMint:
    def _mint_events(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "trajectory_mint",
                "agents": ["alice@x", "bob@x"],
                "per_agent": [30, 30],
                "amount": 60,
                "issue": 1,
            }
        ]

    def test_each_recipient_credited_once(self) -> None:
        """Both agents earn exactly their per_agent share, not the total."""
        earned, _ = compute_earned_spent(self._mint_events())
        assert earned.get("alice@x") == 30
        assert earned.get("bob@x") == 30

    def test_correct_per_agent_stored_values_pass(self) -> None:
        """Stored total_earned=30 for each agent matches per_agent → PASS."""
        earned, spent = compute_earned_spent(self._mint_events())
        stored = {
            "alice@x": _stored(total_earned=30, total_spent=0),
            "bob@x": _stored(total_earned=30, total_spent=0),
        }
        status, violations, _, _ = check_consistency(stored, earned, spent)
        assert status == "PASS"
        assert violations == []

    def test_double_total_stored_for_one_recipient_fails(self) -> None:
        """Stored total_earned=60 for alice (the full mint, not 30) must be VIOLATION."""
        earned, spent = compute_earned_spent(self._mint_events())
        stored = {"alice@x": _stored(total_earned=60, total_spent=0)}
        status, violations, _, _ = check_consistency(stored, earned, spent)
        assert status == "FAIL"
        violation_fields = {
            (v["agent"], v["field"]) for v in violations
        }
        assert ("alice@x", "total_earned") in violation_fields

    def test_mint_event_counted_once_per_recipient_not_twice(self) -> None:
        """Two identical mint events for the same pair must accumulate, not skip."""
        events = self._mint_events() * 2  # repeat the event
        earned, _ = compute_earned_spent(events)
        # Two events × 30 each = 60 per agent
        assert earned.get("alice@x") == 60
        assert earned.get("bob@x") == 60


# ---------------------------------------------------------------------------
# Scenario 4: Fractional amounts
# ---------------------------------------------------------------------------
# The implementation converts amount via int(), so 0.5 → 0.  A stored
# total_earned=0 with a float-amount history event must PASS.  A stored
# total_earned=1 (someone rounded up) must FAIL.
# ---------------------------------------------------------------------------


class TestFractionalAmounts:
    def test_float_amount_truncated_to_zero_no_false_violation(
        self, tmp_path: Path
    ) -> None:
        """amount=0.5 is truncated to 0; stored total_earned=0 must PASS."""
        _write_ledger(
            tmp_path,
            agents={"alice@x": _stored(total_earned=0, total_spent=0)},
            history_lines=[
                json.dumps({"type": "payment", "agent": "alice@x", "amount": 0.5}),
            ],
        )
        result, passed = run(tmp_path)
        assert passed, "fractional amount 0.5 truncates to 0; stored=0 must PASS"
        assert result["violations"] == []

    def test_stored_rounded_up_while_computed_is_zero_fails(
        self, tmp_path: Path
    ) -> None:
        """Stored total_earned=1 vs computed=0 (truncated 0.5) must be VIOLATION."""
        _write_ledger(
            tmp_path,
            agents={"alice@x": _stored(total_earned=1, total_spent=0)},
            history_lines=[
                json.dumps({"type": "payment", "agent": "alice@x", "amount": 0.5}),
            ],
        )
        result, passed = run(tmp_path)
        assert not passed, "stored=1 vs computed=0 (truncated 0.5) must be caught"
        assert any(
            v["agent"] == "alice@x" and v["field"] == "total_earned"
            for v in result["violations"]
        )

    def test_integer_amount_alongside_float_accumulates_correctly(
        self, tmp_path: Path
    ) -> None:
        """Mixed int and float amounts: int(10) + int(0.5)=0 → computed=10."""
        _write_ledger(
            tmp_path,
            agents={"alice@x": _stored(total_earned=10, total_spent=0)},
            history_lines=[
                json.dumps({"type": "payment", "agent": "alice@x", "amount": 10}),
                json.dumps({"type": "payment", "agent": "alice@x", "amount": 0.5}),
            ],
        )
        result, passed = run(tmp_path)
        assert passed, "10 + int(0.5)=0 → computed=10; stored=10 must PASS"


# ---------------------------------------------------------------------------
# Scenario 5: Many small payments
# ---------------------------------------------------------------------------
# 100 accept events of 1 WEA each must accumulate to computed_earned=100,
# matching stored total_earned=100.
# ---------------------------------------------------------------------------


class TestManySmallPayments:
    def test_100_accept_events_accumulate_to_100(self, tmp_path: Path) -> None:
        """100 × accept(amount=1) must yield computed_earned=100 and PASS."""
        history_lines = [
            json.dumps({"type": "accept", "agent": "alice@x", "amount": 1})
            for _ in range(100)
        ]
        _write_ledger(
            tmp_path,
            agents={"alice@x": _stored(total_earned=100, total_spent=0)},
            history_lines=history_lines,
        )
        result, passed = run(tmp_path)
        assert passed, "100 × 1 WEA accept events must accumulate to 100"
        assert result["violations"] == []

    def test_99_accept_events_does_not_match_100_stored(
        self, tmp_path: Path
    ) -> None:
        """99 accept events of 1 WEA vs stored=100 must be caught as VIOLATION."""
        history_lines = [
            json.dumps({"type": "accept", "agent": "alice@x", "amount": 1})
            for _ in range(99)
        ]
        _write_ledger(
            tmp_path,
            agents={"alice@x": _stored(total_earned=100, total_spent=0)},
            history_lines=history_lines,
        )
        result, passed = run(tmp_path)
        assert not passed, "99 WEA computed vs 100 stored must be a VIOLATION"
        assert any(
            v["agent"] == "alice@x" and v["field"] == "total_earned"
            for v in result["violations"]
        )

    def test_many_escrow_creates_accumulate_to_spent(self, tmp_path: Path) -> None:
        """50 escrow_create events of 2 WEA each → computed_spent=100; stored=100 passes."""
        history_lines = [
            json.dumps(
                {"type": "escrow_create", "author": "alice@x", "amount": 2, "issue": i}
            )
            for i in range(50)
        ]
        _write_ledger(
            tmp_path,
            agents={"alice@x": _stored(total_earned=0, total_spent=100)},
            history_lines=history_lines,
        )
        result, passed = run(tmp_path)
        assert passed, "50 × 2 WEA escrow_creates must accumulate to spent=100"
        assert result["violations"] == []


# ---------------------------------------------------------------------------
# Scenario 6: Negative stored value
# ---------------------------------------------------------------------------
# total_earned=-1 in balances.json is a corrupted value.  The checker must
# detect it as a VIOLATION (computed=0 ≠ stored=-1).
# ---------------------------------------------------------------------------


class TestNegativeStoredValue:
    def test_negative_total_earned_is_violation(self) -> None:
        """Stored total_earned=-1 with no history events → computed=0 ≠ -1 → VIOLATION."""
        stored = {"alice@x": _stored(total_earned=-1, total_spent=0)}
        status, violations, _, _ = check_consistency(stored, {}, {})
        assert status == "FAIL", "negative stored total_earned must be caught as VIOLATION"
        assert any(
            v["agent"] == "alice@x" and v["field"] == "total_earned"
            for v in violations
        )

    def test_negative_total_spent_is_violation(self) -> None:
        """Stored total_spent=-5 with no history events → computed=0 ≠ -5 → VIOLATION."""
        stored = {"alice@x": _stored(total_earned=0, total_spent=-5)}
        status, violations, _, _ = check_consistency(stored, {}, {})
        assert status == "FAIL"
        assert any(
            v["agent"] == "alice@x" and v["field"] == "total_spent"
            for v in violations
        )

    def test_negative_earned_violation_has_correct_delta(self) -> None:
        """Violation delta for total_earned=-1 vs computed=0 must be +1."""
        stored = {"alice@x": _stored(total_earned=-1, total_spent=0)}
        _, violations, _, _ = check_consistency(stored, {}, {})
        viol = next(v for v in violations if v["field"] == "total_earned")
        assert viol["stored"] == -1
        assert viol["computed"] == 0
        assert viol["delta"] == 1  # computed - stored = 0 - (-1) = 1

    def test_run_integration_negative_stored_fails(self, tmp_path: Path) -> None:
        """Integration: balances.json with total_earned=-1 produces FAIL exit."""
        _write_ledger(
            tmp_path,
            agents={"alice@x": _stored(total_earned=-1, total_spent=0)},
        )
        result, passed = run(tmp_path)
        assert not passed
        assert result["status"] == "FAIL"


# ---------------------------------------------------------------------------
# Scenario 7: Agent with all zeros
# ---------------------------------------------------------------------------
# An agent with total_earned=0, total_spent=0, and no history events must
# produce a PASS — no phantom violations or warnings.
# ---------------------------------------------------------------------------


class TestAllZerosAgent:
    def test_all_zeros_no_history_passes(self) -> None:
        """total_earned=0, total_spent=0, no events → PASS with no violations."""
        stored = {"alice@x": _stored(total_earned=0, total_spent=0)}
        status, violations, warnings, _ = check_consistency(stored, {}, {})
        assert status == "PASS"
        assert violations == []

    def test_all_zeros_agent_not_emitted_as_warning(self) -> None:
        """A zero-balance stored agent with no history must not appear in warnings."""
        stored = {"alice@x": _stored(total_earned=0, total_spent=0)}
        _, _, warnings, _ = check_consistency(stored, {}, {})
        # The warning path only fires for agents in history but absent from stored
        assert not any(w["agent"] == "alice@x" for w in warnings)

    def test_multiple_zero_agents_all_pass(self, tmp_path: Path) -> None:
        """Several freshly registered agents with all zeros must all pass consistently."""
        _write_ledger(
            tmp_path,
            agents={
                "alice@x": _stored(total_earned=0, total_spent=0),
                "bob@x": _stored(total_earned=0, total_spent=0),
                "carol@x": _stored(total_earned=0, total_spent=0),
            },
        )
        result, passed = run(tmp_path)
        assert passed
        assert result["violations"] == []
        assert "3 stored agent(s)" in result["summary"]

    def test_zero_agent_coexists_with_active_agent(self, tmp_path: Path) -> None:
        """A zero-balance agent alongside an active agent must not cause cross-contamination."""
        _write_ledger(
            tmp_path,
            agents={
                "alice@x": _stored(total_earned=50, total_spent=0),
                "bob@x": _stored(total_earned=0, total_spent=0),
            },
            history_lines=[
                json.dumps({"type": "payment", "agent": "alice@x", "amount": 50}),
            ],
        )
        result, passed = run(tmp_path)
        assert passed, "alice consistent, bob zero — must PASS"
        assert result["violations"] == []
