"""Tests for scripts/check_history_balance_flow.py.

Coverage:
  (a) clean history → PASS
  (b) balance goes negative mid-history → FAIL
  (c) final balance mismatch → FAIL
  (d) missing agent in history vs balances → FAIL

Plus edge cases: trajectory_mint, escrow_return deduplication, economy_reset,
agent_removal, registration_confirmed, and missing/invalid files.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.check_history_balance_flow import (
    compare_final,
    load_events,
    replay,
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
# (a) Clean history → PASS
# ---------------------------------------------------------------------------


def test_clean_history_passes(tmp_path: Path) -> None:
    """All events consistent: no negatives, final balances match."""
    _write_balances(
        tmp_path / "ledger" / "balances.json",
        {
            "alice@claude": {"balance": 80},
            "bob@codex": {"balance": 20},
        },
    )
    _write_history(
        tmp_path / "ledger" / "history",
        "2026-01-01.jsonl",
        [
            {"type": "payment", "agent": "alice@claude", "amount": 100, "timestamp": "2026-01-01T01:00:00Z"},
            {"type": "escrow", "agent": "alice@claude", "amount": 20, "issue": 1, "timestamp": "2026-01-01T02:00:00Z"},
            {"type": "payment", "agent": "bob@codex", "amount": 20, "timestamp": "2026-01-01T03:00:00Z"},
        ],
    )

    result, passed = run(tmp_path)

    assert passed is True
    assert result["status"] == "PASS"
    assert result["negative_violations"] == []
    assert result["final_mismatches"] == []
    assert result["events_replayed"] > 0


def test_multiple_agents_clean(tmp_path: Path) -> None:
    """Multiple agents, multi-file history, all balances correct."""
    history_dir = tmp_path / "ledger" / "history"
    _write_balances(
        tmp_path / "ledger" / "balances.json",
        {
            "alice@claude": {"balance": 50},
            "bob@codex": {"balance": 30},
        },
    )
    _write_history(history_dir, "2026-01-01.jsonl", [
        {"type": "payment", "agent": "alice@claude", "amount": 50},
    ])
    _write_history(history_dir, "2026-01-02.jsonl", [
        {"type": "mint", "agent": "bob@codex", "amount": 30},
    ])

    result, passed = run(tmp_path)

    assert passed is True
    assert result["status"] == "PASS"


# ---------------------------------------------------------------------------
# (b) Balance goes negative mid-history → FAIL
# ---------------------------------------------------------------------------


def test_negative_balance_mid_history_fails(tmp_path: Path) -> None:
    """Agent escrows more than her balance — goes negative mid-history.

    Even though a later payment brings balance back to a non-negative value,
    the mid-history violation must cause FAIL.
    """
    # alice: payment +50, escrow -60 (→ -10), payment +10 (→ 0)
    # Final balance is 0 — but she went negative mid-history.
    _write_balances(
        tmp_path / "ledger" / "balances.json",
        {"alice@claude": {"balance": 0}},
    )
    _write_history(
        tmp_path / "ledger" / "history",
        "2026-01-01.jsonl",
        [
            {"type": "payment", "agent": "alice@claude", "amount": 50, "timestamp": "2026-01-01T01:00:00Z"},
            {"type": "escrow", "agent": "alice@claude", "amount": 60, "issue": 7, "timestamp": "2026-01-01T02:00:00Z"},
            {"type": "payment", "agent": "alice@claude", "amount": 10, "timestamp": "2026-01-01T03:00:00Z"},
        ],
    )

    result, passed = run(tmp_path)

    assert passed is False
    assert result["status"] == "FAIL"
    assert len(result["negative_violations"]) >= 1
    agents_with_violation = [v["agent"] for v in result["negative_violations"]]
    assert "alice@claude" in agents_with_violation
    # Verify the balance was -10 at violation time
    alice_violation = next(v for v in result["negative_violations"] if v["agent"] == "alice@claude")
    assert alice_violation["balance"] == -10


def test_reversal_causes_negative(tmp_path: Path) -> None:
    """Reversal of more than agent earned creates negative balance."""
    # bob: payment +30, reversal -50 (→ -20)
    _write_balances(
        tmp_path / "ledger" / "balances.json",
        {"bob@codex": {"balance": -20}},  # balances.json reflects the error too
    )
    _write_history(
        tmp_path / "ledger" / "history",
        "2026-01-01.jsonl",
        [
            {"type": "payment", "agent": "bob@codex", "amount": 30, "timestamp": "2026-01-01T01:00:00Z"},
            {"type": "reversal", "agent": "bob@codex", "amount": -50, "issue": 3, "timestamp": "2026-01-01T02:00:00Z"},
        ],
    )

    result, passed = run(tmp_path)

    assert passed is False
    assert result["status"] == "FAIL"
    assert any(v["agent"] == "bob@codex" for v in result["negative_violations"])


# ---------------------------------------------------------------------------
# (c) Final balance mismatch → FAIL
# ---------------------------------------------------------------------------


def test_final_balance_mismatch_fails(tmp_path: Path) -> None:
    """History justifies 50 WEA but balances.json records 100 WEA — mismatch."""
    _write_balances(
        tmp_path / "ledger" / "balances.json",
        {"alice@claude": {"balance": 100}},
    )
    _write_history(
        tmp_path / "ledger" / "history",
        "2026-01-01.jsonl",
        [{"type": "payment", "agent": "alice@claude", "amount": 50}],
    )

    result, passed = run(tmp_path)

    assert passed is False
    assert result["status"] == "FAIL"
    assert result["negative_violations"] == []  # no negative balances
    assert len(result["final_mismatches"]) == 1
    mismatch = result["final_mismatches"][0]
    assert mismatch["agent"] == "alice@claude"
    assert mismatch["stored"] == 100
    assert mismatch["computed"] == 50
    assert mismatch["delta"] == -50  # computed - stored


def test_history_undercounts_balance(tmp_path: Path) -> None:
    """History shows less than balances.json — undocumented credit."""
    _write_balances(
        tmp_path / "ledger" / "balances.json",
        {"carol@gemini": {"balance": 200}},
    )
    _write_history(
        tmp_path / "ledger" / "history",
        "2026-01-01.jsonl",
        [{"type": "mint", "agent": "carol@gemini", "amount": 100}],
    )

    result, passed = run(tmp_path)

    assert passed is False
    assert result["status"] == "FAIL"
    mismatches = {m["agent"]: m for m in result["final_mismatches"]}
    assert "carol@gemini" in mismatches
    assert mismatches["carol@gemini"]["delta"] == -100  # 100 computed - 200 stored


# ---------------------------------------------------------------------------
# (d) Missing agent in history vs balances → FAIL
# ---------------------------------------------------------------------------


def test_agent_in_balances_but_not_history_fails(tmp_path: Path) -> None:
    """Agent has non-zero balance in balances.json but zero history — FAIL.

    The history cannot justify the balance; this is drift.
    """
    _write_balances(
        tmp_path / "ledger" / "balances.json",
        {
            "alice@claude": {"balance": 50},
            "ghost@codex": {"balance": 100},  # no history events for ghost
        },
    )
    _write_history(
        tmp_path / "ledger" / "history",
        "2026-01-01.jsonl",
        [{"type": "payment", "agent": "alice@claude", "amount": 50}],
    )

    result, passed = run(tmp_path)

    assert passed is False
    assert result["status"] == "FAIL"
    mismatches = {m["agent"]: m for m in result["final_mismatches"]}
    assert "ghost@codex" in mismatches
    assert mismatches["ghost@codex"]["stored"] == 100
    assert mismatches["ghost@codex"]["computed"] == 0


def test_agent_in_history_but_not_balances_fails(tmp_path: Path) -> None:
    """Agent earns WEA in history but is absent from balances.json — drift."""
    _write_balances(
        tmp_path / "ledger" / "balances.json",
        {"alice@claude": {"balance": 50}},
    )
    _write_history(
        tmp_path / "ledger" / "history",
        "2026-01-01.jsonl",
        [
            {"type": "payment", "agent": "alice@claude", "amount": 50},
            {"type": "payment", "agent": "phantom@test", "amount": 99},
        ],
    )

    result, passed = run(tmp_path)

    assert passed is False
    assert result["status"] == "FAIL"
    mismatches = {m["agent"]: m for m in result["final_mismatches"]}
    assert "phantom@test" in mismatches
    assert mismatches["phantom@test"]["stored"] is None
    assert mismatches["phantom@test"]["computed"] == 99


def test_agent_zero_balance_in_both_passes(tmp_path: Path) -> None:
    """Agent with zero balance in both history and balances.json → PASS."""
    _write_balances(
        tmp_path / "ledger" / "balances.json",
        {"alice@claude": {"balance": 50}, "zero@test": {"balance": 0}},
    )
    _write_history(
        tmp_path / "ledger" / "history",
        "2026-01-01.jsonl",
        [{"type": "payment", "agent": "alice@claude", "amount": 50}],
    )

    result, passed = run(tmp_path)

    assert passed is True
    assert result["status"] == "PASS"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_trajectory_mint_list_format(tmp_path: Path) -> None:
    """trajectory_mint with agents/per_agent list format credits each agent."""
    _write_balances(
        tmp_path / "ledger" / "balances.json",
        {
            "alice@claude": {"balance": 25},
            "bob@codex": {"balance": 15},
        },
    )
    _write_history(
        tmp_path / "ledger" / "history",
        "2026-01-01.jsonl",
        [{
            "type": "trajectory_mint",
            "agents": ["alice@claude", "bob@codex"],
            "per_agent": [25, 15],
            "amount": 40,
        }],
    )

    result, passed = run(tmp_path)

    assert passed is True
    assert result["status"] == "PASS"
    assert result["negative_violations"] == []


def test_escrow_return_deduplication(tmp_path: Path) -> None:
    """Duplicate escrow_return rows for same issue are counted once only."""
    # alice: payment +100, escrow_create -30, escrow_return +30 (× 2 rows)
    # net = 100; duplicate second return must not inflate to 130
    _write_balances(
        tmp_path / "ledger" / "balances.json",
        {"alice@claude": {"balance": 100}},
    )
    _write_history(
        tmp_path / "ledger" / "history",
        "2026-01-01.jsonl",
        [
            {"type": "payment", "agent": "alice@claude", "amount": 100},
            {"type": "escrow_create", "agent": "alice@claude", "amount": 30, "issue": 5},
            {"type": "escrow_return", "agent": "alice@claude", "amount": 30, "issue": 5},
            {"type": "escrow_return", "agent": "alice@claude", "amount": 30, "issue": 5},
        ],
    )

    result, passed = run(tmp_path)

    assert passed is True
    assert result["status"] == "PASS"
    assert result["negative_violations"] == []


def test_economy_reset_clears_pre_bootstrap_violations(tmp_path: Path) -> None:
    """Negative balances before economy_reset are cleared and not reported."""
    # Pre-bootstrap: alice earns 50, then a reversal of -100 → negative.
    # economy_reset zeros alice, returns 0 to agent0.
    # Post-reset: alice has 0, matches balances.json.
    _write_balances(
        tmp_path / "ledger" / "balances.json",
        {"alice@claude": {"balance": 0}},
    )
    _write_history(
        tmp_path / "ledger" / "history",
        "2026-01-01.jsonl",
        [
            {"type": "payment", "agent": "alice@claude", "amount": 50, "timestamp": "2026-01-01T01:00:00Z"},
            {"type": "reversal", "agent": "alice@claude", "amount": -100, "timestamp": "2026-01-01T02:00:00Z"},
            {
                "type": "economy_reset",
                "agents_zeroed": ["alice@claude"],
                "wea_returned_to_agent0": 0,
                "new_supply": 10000,
                "timestamp": "2026-01-01T03:00:00Z",
            },
        ],
    )

    result, passed = run(tmp_path)

    assert passed is True
    assert result["status"] == "PASS"
    assert result["negative_violations"] == []  # cleared by reset


def test_missing_balances_json_fails(tmp_path: Path) -> None:
    """Missing balances.json → FAIL with descriptive message."""
    result, passed = run(tmp_path)

    assert passed is False
    assert result["status"] == "FAIL"
    assert "not found" in result["summary"]


def test_empty_history_dir_all_zero_balances_pass(tmp_path: Path) -> None:
    """No history events + all agents at zero balance → PASS."""
    _write_balances(
        tmp_path / "ledger" / "balances.json",
        {"alice@claude": {"balance": 0}},
    )
    # No history directory at all.

    result, passed = run(tmp_path)

    assert passed is True
    assert result["status"] == "PASS"
    assert result["events_replayed"] == 0


def test_accept_event_credits_agent(tmp_path: Path) -> None:
    """accept events credit the agent's balance."""
    _write_balances(
        tmp_path / "ledger" / "balances.json",
        {"alice@claude": {"balance": 45}},
    )
    _write_history(
        tmp_path / "ledger" / "history",
        "2026-01-01.jsonl",
        [
            {"type": "payment", "agent": "alice@claude", "amount": 20},
            {"type": "accept", "agent": "alice@claude", "amount": 25, "issue": 10},
        ],
    )

    result, passed = run(tmp_path)

    assert passed is True
    assert result["negative_violations"] == []


def test_mechanic_type_normalization(tmp_path: Path) -> None:
    """Events with type=mechanic + event=action are correctly dispatched."""
    # History row: {"type": "standard", "event": "escrow_return", ...}
    _write_balances(
        tmp_path / "ledger" / "balances.json",
        {"alice@claude": {"balance": 130}},
    )
    _write_history(
        tmp_path / "ledger" / "history",
        "2026-01-01.jsonl",
        [
            {"type": "payment", "agent": "alice@claude", "amount": 100},
            {"type": "standard", "event": "escrow_return", "agent": "alice@claude",
             "amount": 30, "issue": 99},
        ],
    )

    result, passed = run(tmp_path)

    assert passed is True
    assert result["status"] == "PASS"


# ---------------------------------------------------------------------------
# Unit tests for replay() and compare_final() in isolation
# ---------------------------------------------------------------------------


def test_replay_returns_correct_final_balance() -> None:
    """replay() accumulates credits and debits correctly."""
    events = [
        {"type": "payment", "agent": "alice@claude", "amount": 100},
        {"type": "escrow", "agent": "alice@claude", "amount": 30, "issue": 1},
        {"type": "escrow_return", "agent": "alice@claude", "amount": 10, "issue": 1},
    ]
    result = replay(events)

    # 100 - 30 + 10 = 80
    assert result["final_balances"]["alice@claude"] == 80
    assert result["negative_violations"] == []


def test_compare_final_reports_mismatch() -> None:
    """compare_final() returns mismatch for divergent agents."""
    computed = {"alice@claude": 50}
    balances_json = {"agents": {"alice@claude": {"balance": 100}}}

    mismatches = compare_final(computed, balances_json)

    assert len(mismatches) == 1
    assert mismatches[0]["agent"] == "alice@claude"
    assert mismatches[0]["delta"] == -50


def test_compare_final_skips_agent0() -> None:
    """agent0@system is always SKIP'd in final comparison."""
    computed = {"agent0@system": 0}  # different from stored
    balances_json = {"agents": {"agent0@system": {"balance": 9999}}}

    mismatches = compare_final(computed, balances_json)

    assert mismatches == []
