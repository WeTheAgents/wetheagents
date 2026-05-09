"""Tests for check_history_reconciliation — history-to-ledger reconciliation.

Quarantined alongside scripts/_quarantine/check_history_reconciliation.py
(see scripts/_quarantine/README.md for context). Not collected by default
pytest runs; opt in with WEA_RUN_QUARANTINED_TESTS=1.
"""

import json
import os

import pytest

from scripts._quarantine.check_history_reconciliation import (
    BASE_DIR,
    ERRORS,
    check_reconciliation,
    compute_totals,
    load_history,
)


@pytest.fixture(autouse=True)
def clear_errors():
    ERRORS.clear()
    yield
    ERRORS.clear()


def make_entries(events: list[dict], filename: str = "2026-01-01.jsonl"):
    """Wrap raw event dicts as (filename, entry) pairs."""
    return [(filename, e) for e in events]


# ---------------------------------------------------------------------------
# load_history
# ---------------------------------------------------------------------------


class TestLoadHistory:
    def test_empty_directory(self, tmp_path):
        entries = load_history(str(tmp_path))
        assert entries == []

    def test_missing_directory(self, tmp_path):
        missing = str(tmp_path / "nonexistent")
        entries = load_history(missing)
        assert entries == []

    def test_ignores_non_jsonl_files(self, tmp_path):
        (tmp_path / "notes.txt").write_text("not a jsonl file\n")
        (tmp_path / "data.json").write_text('{"type":"payment"}\n')
        entries = load_history(str(tmp_path))
        assert entries == []

    def test_loads_valid_jsonl(self, tmp_path):
        (tmp_path / "2026-01-01.jsonl").write_text(
            '{"type":"payment","agent":"alice@test","amount":10}\n'
            '{"type":"escrow","agent":"alice@test","amount":5}\n'
        )
        entries = load_history(str(tmp_path))
        assert len(entries) == 2
        assert entries[0][0] == "2026-01-01.jsonl"
        assert entries[0][1]["type"] == "payment"

    def test_skips_blank_lines(self, tmp_path):
        (tmp_path / "2026-01-01.jsonl").write_text(
            '{"type":"payment","agent":"alice@test","amount":10}\n'
            "\n"
            '{"type":"escrow","agent":"alice@test","amount":5}\n'
        )
        entries = load_history(str(tmp_path))
        assert len(entries) == 2

    def test_skips_invalid_json(self, tmp_path):
        (tmp_path / "2026-01-01.jsonl").write_text(
            '{"type":"payment","agent":"alice@test","amount":10}\n'
            "not-valid-json\n"
        )
        entries = load_history(str(tmp_path))
        assert len(entries) == 1

    def test_chronological_order(self, tmp_path):
        (tmp_path / "2026-01-02.jsonl").write_text(
            '{"type":"payment","agent":"alice@test","amount":20}\n'
        )
        (tmp_path / "2026-01-01.jsonl").write_text(
            '{"type":"payment","agent":"alice@test","amount":10}\n'
        )
        entries = load_history(str(tmp_path))
        assert entries[0][0] == "2026-01-01.jsonl"
        assert entries[1][0] == "2026-01-02.jsonl"


# ---------------------------------------------------------------------------
# compute_totals
# ---------------------------------------------------------------------------


class TestComputeTotals:
    def test_empty_entries(self):
        earned, spent, dates = compute_totals([])
        assert earned == {}
        assert spent == {}

    def test_payment_increments_earned(self):
        entries = make_entries([
            {"type": "payment", "agent": "alice@test", "amount": 50},
        ])
        earned, spent, _ = compute_totals(entries)
        assert earned["alice@test"] == 50
        assert spent.get("alice@test", 0) == 0

    def test_escrow_increments_spent(self):
        entries = make_entries([
            {"type": "escrow", "agent": "alice@test", "amount": 30},
        ])
        earned, spent, _ = compute_totals(entries)
        assert spent["alice@test"] == 30
        assert earned.get("alice@test", 0) == 0

    def test_trajectory_mint_increments_earned_per_agent(self):
        entries = make_entries([
            {
                "type": "trajectory_mint",
                "agents": ["alice@test", "bob@test"],
                "per_agent": [10, 15],
            }
        ])
        earned, spent, _ = compute_totals(entries)
        assert earned["alice@test"] == 10
        assert earned["bob@test"] == 15

    def test_reversal_reduces_earned(self):
        entries = make_entries([
            {"type": "payment", "agent": "alice@test", "amount": 20},
            {"type": "reversal", "agent": "alice@test", "amount": -10},
        ])
        earned, spent, _ = compute_totals(entries)
        assert earned["alice@test"] == 10

    def test_escrow_return_increments_earned(self):
        entries = make_entries([
            {"type": "escrow_return", "agent": "alice@test", "amount": 15},
        ])
        earned, spent, _ = compute_totals(entries)
        assert earned["alice@test"] == 15

    def test_economy_reset_zeroes_affected_agents(self):
        entries = make_entries([
            {"type": "payment", "agent": "alice@test", "amount": 50},
            {"type": "economy_reset", "agents_zeroed": ["alice@test"], "wea_returned_to_agent0": 50},
        ])
        earned, spent, _ = compute_totals(entries)
        assert earned["alice@test"] == 0
        assert earned["agent0@system"] == 50

    def test_economy_reset_wea_returned_to_agent0(self):
        entries = make_entries([
            {"type": "economy_reset", "agents_zeroed": [], "wea_returned_to_agent0": 487},
        ])
        earned, _, _ = compute_totals(entries)
        assert earned["agent0@system"] == 487

    def test_escrow_author_field_not_counted_for_spent(self):
        # Escrow with `author` field (not `agent`) should NOT affect total_spent
        entries = make_entries([
            {"type": "escrow", "author": "alice@test", "amount": 100},
        ])
        earned, spent, _ = compute_totals(entries)
        assert spent.get("alice@test", 0) == 0

    def test_multi_agent_independent_totals(self):
        entries = make_entries([
            {"type": "payment", "agent": "alice@test", "amount": 30},
            {"type": "payment", "agent": "bob@test", "amount": 20},
            {"type": "escrow", "agent": "alice@test", "amount": 10},
        ])
        earned, spent, _ = compute_totals(entries)
        assert earned["alice@test"] == 30
        assert earned["bob@test"] == 20
        assert spent["alice@test"] == 10
        assert spent.get("bob@test", 0) == 0

    def test_agent_dates_tracks_files(self):
        entries = [
            ("2026-01-01.jsonl", {"type": "payment", "agent": "alice@test", "amount": 10}),
            ("2026-01-02.jsonl", {"type": "payment", "agent": "alice@test", "amount": 10}),
        ]
        _, _, dates = compute_totals(entries)
        assert dates["alice@test"] == ["2026-01-01.jsonl", "2026-01-02.jsonl"]


# ---------------------------------------------------------------------------
# check_reconciliation
# ---------------------------------------------------------------------------


class TestCheckReconciliation:
    def _make_balances(self, agents: dict) -> dict:
        return {"version": 1, "agents": agents}

    def test_correct_ledger_no_errors(self):
        """Case 1: fully correct ledger — no discrepancies."""
        balances = self._make_balances({
            "alice@test": {"total_earned": 50, "total_spent": 0},
        })
        earned = {"alice@test": 50}
        spent: dict = {}
        dates: dict = {}
        check_reconciliation(balances, earned, spent, dates)
        assert ERRORS == []

    def test_missing_payment_entry_fails(self):
        """Case 2: payment recorded in balances but absent from history — FAIL."""
        balances = self._make_balances({
            "alice@test": {"total_earned": 50, "total_spent": 0},
        })
        # History shows 30, not 50
        earned = {"alice@test": 30}
        spent: dict = {}
        dates: dict = {}
        check_reconciliation(balances, earned, spent, dates)
        assert any("alice@test" in e and "total_earned" in e for e in ERRORS)

    def test_phantom_payment_fails(self):
        """Case 3: payment exists in history but not in balances — FAIL."""
        balances = self._make_balances({
            "alice@test": {"total_earned": 0, "total_spent": 0},
        })
        # History shows 40 earned, balances shows 0
        earned = {"alice@test": 40}
        spent: dict = {}
        dates: dict = {}
        check_reconciliation(balances, earned, spent, dates)
        assert any("alice@test" in e and "total_earned" in e for e in ERRORS)

    def test_wrong_amount_fails(self):
        """Case 4: amount in balances differs from history sum — FAIL."""
        balances = self._make_balances({
            "alice@test": {"total_earned": 100, "total_spent": 20},
        })
        earned = {"alice@test": 100}
        spent = {"alice@test": 25}  # off by 5
        dates: dict = {}
        check_reconciliation(balances, earned, spent, dates)
        assert any("alice@test" in e and "total_spent" in e for e in ERRORS)

    def test_multi_agent_ledger_all_correct(self):
        """Case 5: multiple agents, all totals match — no errors."""
        balances = self._make_balances({
            "alice@test": {"total_earned": 50, "total_spent": 10},
            "bob@test":   {"total_earned": 30, "total_spent": 0},
            "carol@test": {"total_earned": 0,  "total_spent": 0},
        })
        earned = {"alice@test": 50, "bob@test": 30, "carol@test": 0}
        spent = {"alice@test": 10}
        dates: dict = {}
        check_reconciliation(balances, earned, spent, dates)
        assert ERRORS == []

    def test_zero_balance_agent_passes(self):
        """Case 6: agent with zero earned/spent — should pass cleanly."""
        balances = self._make_balances({
            "newbie@test": {"total_earned": 0, "total_spent": 0},
        })
        earned: dict = {}
        spent: dict = {}
        dates: dict = {}
        check_reconciliation(balances, earned, spent, dates)
        assert ERRORS == []

    def test_injected_discrepancy_is_caught(self):
        """Case 7: injected discrepancy (delta +5 in spent) is detected and reported."""
        balances = self._make_balances({
            "alice@test": {"total_earned": 50, "total_spent": 20},
        })
        # Inject: history shows only 15 spent, but ledger says 20
        earned = {"alice@test": 50}
        spent = {"alice@test": 15}
        dates = {"alice@test": ["2026-01-01.jsonl"]}
        check_reconciliation(balances, earned, spent, dates)
        assert any("alice@test" in e and "total_spent" in e for e in ERRORS)
        # Delta should be reported
        assert any("-5" in e or "+5" in e for e in ERRORS)

    def test_error_includes_date_info(self):
        """Case 8: discrepancy report includes which date files contributed."""
        balances = self._make_balances({
            "alice@test": {"total_earned": 100, "total_spent": 0},
        })
        earned = {"alice@test": 80}
        spent: dict = {}
        dates = {"alice@test": ["2026-03-10.jsonl", "2026-03-15.jsonl"]}
        check_reconciliation(balances, earned, spent, dates)
        assert any("2026-03-10.jsonl" in e for e in ERRORS)


# ---------------------------------------------------------------------------
# Integration: empty history should not fail
# ---------------------------------------------------------------------------


class TestEmptyHistory:
    def test_no_history_events_passes(self):
        """MUST NOT fail on empty history directory."""
        entries: list = []
        earned, spent, dates = compute_totals(entries)
        balances = {
            "version": 1,
            "agents": {
                "alice@test": {"total_earned": 0, "total_spent": 0},
            },
        }
        check_reconciliation(balances, earned, spent, dates)
        assert ERRORS == []

    def test_multiple_agents_no_history(self):
        """Multiple agents with zero balances — no history needed to pass."""
        entries: list = []
        earned, spent, dates = compute_totals(entries)
        balances = {
            "version": 1,
            "agents": {
                "alice@test": {"total_earned": 0, "total_spent": 0},
                "bob@test":   {"total_earned": 0, "total_spent": 0},
            },
        }
        check_reconciliation(balances, earned, spent, dates)
        assert ERRORS == []


# ---------------------------------------------------------------------------
# Integration: real ledger must reconcile cleanly
# ---------------------------------------------------------------------------


class TestRealLedger:
    def test_real_ledger_reconciles(self):
        """MUST: current ledger/balances.json matches ledger/history/*.jsonl."""
        ledger_dir = os.path.join(BASE_DIR, "ledger")
        balances_path = os.path.join(ledger_dir, "balances.json")
        history_dir = os.path.join(ledger_dir, "history")

        if not os.path.exists(balances_path):
            pytest.skip("balances.json not found — skipping real-ledger test")

        with open(balances_path, encoding="utf-8") as f:
            balances = json.load(f)

        entries = load_history(history_dir)
        earned, spent, agent_dates = compute_totals(entries)
        check_reconciliation(balances, earned, spent, agent_dates)

        assert ERRORS == [], (
            "Real ledger has discrepancies:\n" + "\n".join(ERRORS)
        )
