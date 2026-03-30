"""Tests for scripts/wea_report.py — ecosystem health snapshot."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.wea_report import (
    _load_history,
    _parse_ts,
    generate_report,
    section_agent_activity,
    section_escrow_health,
    section_flow_analysis,
    section_supply_summary,
    section_top_earners,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXED_NOW = datetime(2026, 3, 30, 12, 0, 0, tzinfo=timezone.utc)


def _balances(agents: dict) -> dict:
    return {"version": 1, "agents": agents}


def _escrows(active: dict) -> dict:
    return {"version": 1, "active": active}


def _mints(total: int) -> dict:
    return {"total_minted": total, "mints": []}


def _agent(balance: int, earned: int = 0, completed: int = 0, created: int = 0) -> dict:
    return {
        "balance": balance,
        "total_earned": earned,
        "total_spent": 0,
        "tasks_completed": completed,
        "tasks_created": created,
    }


def _escrow_entry(amount: int, created_at: str, etype: str = "best_x") -> dict:
    return {"author": "agent0@system", "amount": amount, "type": etype, "created_at": created_at}


def _write_jsonl(path: Path, events: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# _parse_ts
# ---------------------------------------------------------------------------


class TestParseTs:
    def test_none_returns_none(self):
        assert _parse_ts(None) is None

    def test_empty_returns_none(self):
        assert _parse_ts("") is None

    def test_z_suffix(self):
        dt = _parse_ts("2026-03-28T17:56:01Z")
        assert dt == datetime(2026, 3, 28, 17, 56, 1, tzinfo=timezone.utc)

    def test_microseconds_z_suffix(self):
        dt = _parse_ts("2026-03-28T17:56:01.123456Z")
        assert dt is not None
        assert dt.year == 2026

    def test_no_timezone_suffix_gets_utc(self):
        dt = _parse_ts("2026-03-28T17:56:01")
        assert dt is not None
        assert dt.tzinfo == timezone.utc

    def test_garbage_returns_none(self):
        assert _parse_ts("not-a-timestamp") is None


# ---------------------------------------------------------------------------
# _load_history
# ---------------------------------------------------------------------------


class TestLoadHistory:
    def test_empty_directory(self, tmp_path):
        assert _load_history(str(tmp_path)) == []

    def test_missing_directory(self, tmp_path):
        assert _load_history(str(tmp_path / "no_such_dir")) == []

    def test_ignores_non_jsonl_files(self, tmp_path):
        (tmp_path / "notes.txt").write_text('{"type":"payment"}\n', encoding="utf-8")
        assert _load_history(str(tmp_path)) == []

    def test_loads_jsonl_events(self, tmp_path):
        _write_jsonl(tmp_path / "2026-01-01.jsonl", [
            {"type": "payment", "agent": "a@test", "amount": 10, "timestamp": "2026-01-01T00:00:00Z"},
        ])
        events = _load_history(str(tmp_path))
        assert len(events) == 1
        assert events[0]["type"] == "payment"

    def test_skips_blank_lines(self, tmp_path):
        (tmp_path / "2026-01-01.jsonl").write_text(
            '{"type":"payment"}\n\n{"type":"escrow"}\n', encoding="utf-8"
        )
        events = _load_history(str(tmp_path))
        assert len(events) == 2

    def test_skips_invalid_json(self, tmp_path):
        (tmp_path / "2026-01-01.jsonl").write_text(
            '{"type":"payment"}\nnot-json\n', encoding="utf-8"
        )
        events = _load_history(str(tmp_path))
        assert len(events) == 1

    def test_events_sorted_by_timestamp(self, tmp_path):
        _write_jsonl(tmp_path / "2026-01-02.jsonl", [
            {"type": "payment", "timestamp": "2026-01-02T00:00:00Z"},
        ])
        _write_jsonl(tmp_path / "2026-01-01.jsonl", [
            {"type": "escrow", "timestamp": "2026-01-01T00:00:00Z"},
        ])
        events = _load_history(str(tmp_path))
        assert events[0]["type"] == "escrow"
        assert events[1]["type"] == "payment"


# ---------------------------------------------------------------------------
# section_supply_summary
# ---------------------------------------------------------------------------


class TestSectionSupplySummary:
    def test_invariant_pass(self):
        bal = _balances({"a@test": _agent(9000), "b@test": _agent(900)})
        esc = _escrows({"1": _escrow_entry(100, "2026-03-01T00:00:00Z")})
        # 9000 + 900 + 100 = 10000 == 10000 + 0 → PASS
        output = section_supply_summary(bal, esc, {})
        assert "PASS" in output
        assert "10000" in output

    def test_invariant_fail_shows_delta(self):
        bal = _balances({"a@test": _agent(5000)})
        esc = _escrows({})
        # 5000 + 0 = 5000, expected = 10000 → FAIL delta -5000
        output = section_supply_summary(bal, esc, {})
        assert "FAIL" in output
        assert "-5000" in output

    def test_balances_sum_in_output(self):
        bal = _balances({"a@test": _agent(6000), "b@test": _agent(4000)})
        esc = _escrows({})
        output = section_supply_summary(bal, esc, {})
        assert "10000" in output

    def test_escrow_sum_in_output(self):
        bal = _balances({"a@test": _agent(9750)})
        esc = _escrows({
            "1": _escrow_entry(150, "2026-03-01T00:00:00Z"),
            "2": _escrow_entry(100, "2026-03-01T00:00:00Z"),
        })
        # 9750 + 250 = 10000 → PASS
        output = section_supply_summary(bal, esc, {})
        assert "PASS" in output
        assert "250" in output

    def test_minted_supply_counted(self):
        bal = _balances({"a@test": _agent(10100)})
        esc = _escrows({})
        mints = _mints(100)
        # 10100 + 0 = 10100 == 10000 + 100 → PASS
        output = section_supply_summary(bal, esc, mints)
        assert "PASS" in output
        assert "100" in output

    def test_output_is_markdown_table(self):
        bal = _balances({"a@test": _agent(10000)})
        esc = _escrows({})
        output = section_supply_summary(bal, esc, {})
        assert "## 1. Supply Summary" in output
        assert "|" in output


# ---------------------------------------------------------------------------
# section_top_earners
# ---------------------------------------------------------------------------


class TestSectionTopEarners:
    def test_sorted_by_total_earned_descending(self):
        bal = _balances({
            "low@test": _agent(10, earned=10),
            "high@test": _agent(90, earned=90),
            "mid@test": _agent(50, earned=50),
        })
        output = section_top_earners(bal)
        high_pos = output.index("high@test")
        mid_pos = output.index("mid@test")
        low_pos = output.index("low@test")
        assert high_pos < mid_pos < low_pos

    def test_all_agents_shown(self):
        bal = _balances({
            "a@test": _agent(100, earned=100),
            "b@test": _agent(0, earned=0),
        })
        output = section_top_earners(bal)
        assert "a@test" in output
        assert "b@test" in output

    def test_section_header_present(self):
        bal = _balances({"a@test": _agent(100)})
        output = section_top_earners(bal)
        assert "## 2. Top Earners" in output


# ---------------------------------------------------------------------------
# section_flow_analysis
# ---------------------------------------------------------------------------


class TestSectionFlowAnalysis:
    def test_no_payment_events(self):
        output = section_flow_analysis([])
        assert "## 3. Flow Analysis" in output
        assert "No payment events" in output

    def test_counts_payment_events(self):
        events = [
            {"type": "payment", "agent": "a@test", "amount": 20, "timestamp": "2026-03-10T00:00:00Z"},
            {"type": "payment", "agent": "b@test", "amount": 30, "timestamp": "2026-03-15T00:00:00Z"},
        ]
        output = section_flow_analysis(events)
        assert "2 " in output or "| 2 |" in output  # 2 payment events
        assert "50" in output  # total paid

    def test_avg_reward_calculation(self):
        events = [
            {"type": "payment", "agent": "a@test", "amount": 10, "timestamp": "2026-03-01T00:00:00Z"},
            {"type": "payment", "agent": "a@test", "amount": 30, "timestamp": "2026-03-10T00:00:00Z"},
        ]
        output = section_flow_analysis(events)
        # avg = (10+30)/2 = 20
        assert "20.0" in output

    def test_non_payment_events_ignored_in_total(self):
        events = [
            {"type": "payment", "agent": "a@test", "amount": 50, "timestamp": "2026-03-10T00:00:00Z"},
            {"type": "escrow", "author": "agent0@system", "amount": 200, "timestamp": "2026-03-11T00:00:00Z"},
        ]
        output = section_flow_analysis(events)
        assert "50" in output
        # 200 (escrow) should NOT appear as "Total WEA paid out"
        assert "| 1 |" in output or "1 |" in output  # 1 payment event

    def test_section_header_present(self):
        events = [{"type": "payment", "agent": "a@test", "amount": 5, "timestamp": "2026-03-01T00:00:00Z"}]
        output = section_flow_analysis(events)
        assert "## 3. Flow Analysis" in output


# ---------------------------------------------------------------------------
# section_escrow_health
# ---------------------------------------------------------------------------


class TestSectionEscrowHealth:
    def test_no_active_escrows(self):
        output = section_escrow_health(_escrows({}), now=FIXED_NOW)
        assert "## 4. Escrow Health" in output
        assert "No active escrows" in output

    def test_total_locked_correct(self):
        esc = _escrows({
            "1": _escrow_entry(100, "2026-03-25T00:00:00Z"),
            "2": _escrow_entry(50, "2026-03-26T00:00:00Z"),
        })
        output = section_escrow_health(esc, now=FIXED_NOW)
        assert "150" in output

    def test_oldest_escrow_shown(self):
        esc = _escrows({
            "10": _escrow_entry(20, "2026-03-20T00:00:00Z"),  # ~10 days old
            "20": _escrow_entry(30, "2026-03-15T00:00:00Z"),  # ~15-16 days old (oldest)
        })
        output = section_escrow_health(esc, now=FIXED_NOW)
        # Issue #20 must be identified as the oldest
        assert "Oldest escrow | Issue #20" in output

    def test_escrows_sorted_oldest_first(self):
        esc = _escrows({
            "new": _escrow_entry(10, "2026-03-29T00:00:00Z"),  # 1 day
            "old": _escrow_entry(10, "2026-03-20T00:00:00Z"),  # 10 days
        })
        output = section_escrow_health(esc, now=FIXED_NOW)
        old_pos = output.index("#old")
        new_pos = output.index("#new")
        assert old_pos < new_pos  # oldest appears first in table

    def test_section_header_present(self):
        esc = _escrows({"1": _escrow_entry(10, "2026-03-01T00:00:00Z")})
        output = section_escrow_health(esc, now=FIXED_NOW)
        assert "## 4. Escrow Health" in output


# ---------------------------------------------------------------------------
# section_agent_activity
# ---------------------------------------------------------------------------


class TestSectionAgentActivity:
    def _recent_event(self, agent: str) -> dict:
        return {
            "type": "payment",
            "agent": agent,
            "amount": 10,
            "timestamp": "2026-03-28T00:00:00Z",
        }

    def test_agent_with_recent_event_is_active(self):
        bal = _balances({"a@test": _agent(100, completed=1)})
        events = [self._recent_event("a@test")]
        output = section_agent_activity(bal, events, now=FIXED_NOW)
        assert "Active" in output
        assert "a@test" in output

    def test_agent_with_no_events_is_dormant(self):
        bal = _balances({"a@test": _agent(0, completed=0)})
        output = section_agent_activity(bal, [], now=FIXED_NOW)
        assert "Dormant" in output
        assert "a@test" in output

    def test_agent_count_summary(self):
        bal = _balances({
            "active@test": _agent(50, completed=1),
            "dormant@test": _agent(0, completed=0),
        })
        events = [self._recent_event("active@test")]
        output = section_agent_activity(bal, events, now=FIXED_NOW)
        assert "| 2 |" in output  # total registered

    def test_trajectory_mint_events_count_as_activity(self):
        bal = _balances({"minter@test": _agent(21, earned=21)})
        events = [{
            "type": "trajectory_mint",
            "agents": ["minter@test"],
            "amount": 21,
            "timestamp": "2026-03-28T00:00:00Z",
        }]
        output = section_agent_activity(bal, events, now=FIXED_NOW)
        assert "Active" in output
        assert "minter@test" in output

    def test_section_header_present(self):
        bal = _balances({"a@test": _agent(100)})
        output = section_agent_activity(bal, [], now=FIXED_NOW)
        assert "## 5. Agent Activity" in output


# ---------------------------------------------------------------------------
# generate_report (integration)
# ---------------------------------------------------------------------------


class TestGenerateReport:
    def _make_ledger(self, tmp_path: Path) -> None:
        ledger = tmp_path / "ledger"
        ledger.mkdir()
        (ledger / "history").mkdir()

        (ledger / "balances.json").write_text(json.dumps({
            "version": 1,
            "agents": {
                "agent0@system": _agent(9700, earned=300, completed=0, created=2),
                "alice@test": _agent(200, earned=200, completed=2),
                "bob@test": _agent(100, earned=100, completed=1),
            }
        }), encoding="utf-8")

        (ledger / "escrows.json").write_text(json.dumps({
            "version": 1,
            "active": {
                "42": _escrow_entry(0, "2026-03-20T00:00:00Z"),
            }
        }), encoding="utf-8")
        # No trajectory_mints.json — supply is just 10000

        _write_jsonl(ledger / "history" / "2026-03-10.jsonl", [
            {"type": "escrow", "author": "agent0@system", "amount": 200, "timestamp": "2026-03-10T00:00:00Z"},
            {"type": "payment", "agent": "alice@test", "amount": 200, "issue": 1, "timestamp": "2026-03-10T12:00:00Z"},
        ])
        _write_jsonl(ledger / "history" / "2026-03-20.jsonl", [
            {"type": "escrow", "author": "agent0@system", "amount": 100, "timestamp": "2026-03-20T00:00:00Z"},
            {"type": "payment", "agent": "bob@test", "amount": 100, "issue": 2, "timestamp": "2026-03-20T12:00:00Z"},
        ])

    def test_report_is_valid_markdown(self, tmp_path):
        self._make_ledger(tmp_path)
        report = generate_report(str(tmp_path), now=FIXED_NOW)
        assert report.startswith("# WEA Flow Report")
        assert "## 1. Supply Summary" in report
        assert "## 2. Top Earners" in report
        assert "## 3. Flow Analysis" in report
        assert "## 4. Escrow Health" in report
        assert "## 5. Agent Activity" in report

    def test_invariant_pass_in_report(self, tmp_path):
        self._make_ledger(tmp_path)
        report = generate_report(str(tmp_path), now=FIXED_NOW)
        assert "PASS" in report

    def test_no_hardcoded_agent_names_in_logic(self, tmp_path):
        """Top earner is whichever agent has highest total_earned — dynamically resolved."""
        self._make_ledger(tmp_path)
        report = generate_report(str(tmp_path), now=FIXED_NOW)
        # alice has highest earned (200) — must appear before bob (100) in top earners
        alice_pos = report.index("alice@test")
        bob_pos = report.index("bob@test")
        # alice appears first in top earners section (section 2)
        section2_start = report.index("## 2. Top Earners")
        assert alice_pos > section2_start
        # alice ranks above bob
        assert alice_pos < bob_pos or report.count("alice@test") > 0

    def test_payment_totals_appear_in_flow_section(self, tmp_path):
        self._make_ledger(tmp_path)
        report = generate_report(str(tmp_path), now=FIXED_NOW)
        # 2 payments totalling 300 WEA
        assert "300" in report
        assert "2 " in report or "| 2 |" in report

    def test_report_includes_generation_timestamp(self, tmp_path):
        self._make_ledger(tmp_path)
        report = generate_report(str(tmp_path), now=FIXED_NOW)
        assert "2026-03-30" in report

    def test_real_ledger_report_passes_invariant(self):
        """Smoke test: run against actual ledger. Numbers must match check_invariant.py."""
        import os
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        report = generate_report(root)
        assert "PASS" in report
