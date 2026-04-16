"""Tests for scripts/check_total_earned_consistency.py.

All tests are fully in-memory; no real ledger files are accessed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

# Make the scripts directory importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from check_total_earned_consistency import (  # noqa: E402
    _extract_objects,
    check_consistency,
    compute_total_earned,
    main,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _agent(total_earned: int = 0) -> dict[str, Any]:
    """Build a minimal stored agent dict with only total_earned."""
    return {"balance": total_earned, "total_earned": total_earned}


def _agents(**kwargs: dict[str, Any]) -> dict[str, Any]:
    """Build a stored_agents dict."""
    return kwargs


# ---------------------------------------------------------------------------
# _extract_objects tests
# ---------------------------------------------------------------------------


def test_extract_objects_single_valid():
    """A single valid JSON object on a line is returned as a one-element list."""
    line = '{"type": "payment", "agent": "alice@x", "amount": 10}'
    result = _extract_objects(line)
    assert len(result) == 1
    assert result[0]["type"] == "payment"


def test_extract_objects_two_concatenated():
    """Two JSON objects concatenated on one line are both extracted."""
    a = '{"type": "payment", "agent": "alice@x", "amount": 10}'
    b = '{"type": "accept", "agent": "bob@x", "amount": 5}'
    result = _extract_objects(a + b)
    assert len(result) == 2
    assert result[0]["agent"] == "alice@x"
    assert result[1]["agent"] == "bob@x"


def test_extract_objects_empty_string():
    """Empty line returns empty list."""
    assert _extract_objects("") == []


def test_extract_objects_invalid_json_returns_empty():
    """A line with an invalid JSON escape is silently skipped."""
    line = r'{"note": "bad \! escape"}'
    result = _extract_objects(line)
    assert result == []


def test_extract_objects_whitespace_between_objects():
    """Whitespace between concatenated objects is handled."""
    a = '{"type": "payment", "amount": 1}'
    b = '{"type": "accept", "amount": 2}'
    result = _extract_objects(a + "  " + b)
    assert len(result) == 2


# ---------------------------------------------------------------------------
# compute_total_earned tests
# ---------------------------------------------------------------------------


def test_empty_events_returns_empty_dict():
    """No events → empty dict."""
    assert compute_total_earned([]) == {}


def test_payment_credits_agent():
    """payment event with positive amount credits the agent."""
    events = [{"type": "payment", "agent": "alice@x", "amount": 50}]
    result = compute_total_earned(events)
    assert result.get("alice@x") == 50


def test_accept_credits_agent():
    """accept event with positive amount credits the agent."""
    events = [{"type": "accept", "agent": "bob@x", "amount": 20}]
    result = compute_total_earned(events)
    assert result.get("bob@x") == 20


def test_payment_zero_not_counted():
    """payment with amount=0 does not count toward total_earned."""
    events = [{"type": "payment", "agent": "alice@x", "amount": 0}]
    result = compute_total_earned(events)
    assert result.get("alice@x", 0) == 0


def test_payment_negative_not_counted():
    """payment with negative amount (reversal-style) does not count."""
    events = [{"type": "payment", "agent": "alice@x", "amount": -5}]
    result = compute_total_earned(events)
    assert result.get("alice@x", 0) == 0


def test_trajectory_mint_multi_agent_format():
    """Multi-agent trajectory_mint credits each agent by its per_agent slot."""
    events = [
        {
            "type": "trajectory_mint",
            "agents": ["alice@x", "bob@x"],
            "per_agent": [10, 15],
            "amount": 25,
        }
    ]
    result = compute_total_earned(events)
    assert result.get("alice@x") == 10
    assert result.get("bob@x") == 15


def test_trajectory_mint_single_agent_format():
    """Single-agent trajectory_mint uses the agent + amount fields."""
    events = [{"type": "trajectory_mint", "agent": "charlie@x", "amount": 30}]
    result = compute_total_earned(events)
    assert result.get("charlie@x") == 30


def test_trajectory_mint_partial_per_agent_list():
    """per_agent list shorter than agents: extra agents receive nothing."""
    events = [
        {
            "type": "trajectory_mint",
            "agents": ["alice@x", "bob@x", "charlie@x"],
            "per_agent": [10, 20],
            "amount": 30,
        }
    ]
    result = compute_total_earned(events)
    assert result.get("alice@x") == 10
    assert result.get("bob@x") == 20
    assert result.get("charlie@x", 0) == 0


def test_escrow_return_recipient_field():
    """escrow_return with recipient field credits that agent."""
    events = [
        {"type": "escrow_return", "recipient": "alice@x", "amount": 40, "issue": 7}
    ]
    result = compute_total_earned(events)
    assert result.get("alice@x") == 40


def test_escrow_return_agent_fallback():
    """escrow_return without recipient falls back to agent field."""
    events = [
        {"type": "escrow_return", "agent": "bob@x", "amount": 25, "issue": 8}
    ]
    result = compute_total_earned(events)
    assert result.get("bob@x") == 25


def test_escrow_create_not_counted():
    """escrow_create is explicitly excluded from total_earned."""
    events = [
        {"type": "escrow_create", "author": "alice@x", "amount": 100, "issue": 1}
    ]
    result = compute_total_earned(events)
    assert result.get("alice@x", 0) == 0


def test_multiple_events_accumulate_correctly():
    """Multiple income events for the same agent accumulate."""
    events = [
        {"type": "payment", "agent": "alice@x", "amount": 20},
        {"type": "accept", "agent": "alice@x", "amount": 15},
        {"type": "trajectory_mint", "agent": "alice@x", "amount": 25},
    ]
    result = compute_total_earned(events)
    assert result.get("alice@x") == 60


def test_ignored_event_types_not_counted():
    """Unrelated events (verification, claim, escrow, reversal) don't affect earned."""
    events = [
        {"type": "verification", "agent": "alice@x", "amount": 999},
        {"type": "claim", "agent": "alice@x", "amount": 50},
        {"type": "escrow", "agent": "alice@x", "amount": 50},
        {"type": "reversal", "agent": "alice@x", "amount": 50},
        {"type": "economy_reset"},
    ]
    result = compute_total_earned(events)
    assert result.get("alice@x", 0) == 0


# ---------------------------------------------------------------------------
# check_consistency tests
# ---------------------------------------------------------------------------


def test_check_consistency_pass_when_match():
    """Stored total_earned equals computed → PASS, no divergences."""
    stored = _agents(**{"alice@x": _agent(total_earned=50)})
    computed = {"alice@x": 50}
    status, divergences, warnings, summary = check_consistency(stored, computed)
    assert status == "PASS"
    assert divergences == []


def test_check_consistency_fail_when_mismatch():
    """Stored total_earned differs from computed → FAIL with divergence entry."""
    stored = _agents(**{"alice@x": _agent(total_earned=100)})
    computed = {"alice@x": 80}
    status, divergences, warnings, summary = check_consistency(stored, computed)
    assert status == "FAIL"
    assert len(divergences) == 1
    div = divergences[0]
    assert div["agent"] == "alice@x"
    assert div["field"] == "total_earned"
    assert div["stored"] == 100
    assert div["computed"] == 80


def test_check_consistency_agent0_excluded():
    """agent0@system is never reported as a divergence even if values differ."""
    stored = _agents(**{"agent0@system": _agent(total_earned=9999)})
    computed = {"agent0@system": 0}
    status, divergences, warnings, summary = check_consistency(stored, computed)
    assert status == "PASS"
    assert all(d["agent"] != "agent0@system" for d in divergences)


def test_check_consistency_history_only_agent_is_warning():
    """Agent with non-zero computed earned absent from stored → warning, not FAIL."""
    stored: dict[str, Any] = {}
    computed = {"ghost@x": 50}
    status, divergences, warnings, summary = check_consistency(stored, computed)
    assert status == "PASS"
    assert divergences == []
    assert any(w["agent"] == "ghost@x" for w in warnings)


def test_check_consistency_zero_history_agent_no_warning():
    """Agent in history with zero computed earned does not generate a warning."""
    stored: dict[str, Any] = {}
    computed = {"silent@x": 0}
    status, divergences, warnings, summary = check_consistency(stored, computed)
    assert status == "PASS"
    assert warnings == []


def test_check_consistency_multiple_agents_some_diverge():
    """Only diverging agents appear in divergences list."""
    stored = _agents(
        **{
            "alice@x": _agent(total_earned=100),
            "bob@x": _agent(total_earned=200),
        }
    )
    computed = {"alice@x": 80, "bob@x": 200}
    status, divergences, warnings, summary = check_consistency(stored, computed)
    assert status == "FAIL"
    agents_with_div = {d["agent"] for d in divergences}
    assert "alice@x" in agents_with_div
    assert "bob@x" not in agents_with_div


def test_check_consistency_empty_stored_empty_computed():
    """No stored agents, no history → PASS with zero divergences."""
    status, divergences, warnings, summary = check_consistency({}, {})
    assert status == "PASS"
    assert divergences == []
    assert "0 divergence" in summary


def test_check_consistency_summary_counts_stored_agents():
    """Summary counts checked stored agents (excluding agent0)."""
    stored = _agents(
        **{
            "agent0@system": _agent(total_earned=0),
            "alice@x": _agent(total_earned=10),
            "bob@x": _agent(total_earned=20),
        }
    )
    computed = {"alice@x": 10, "bob@x": 20}
    status, divergences, warnings, summary = check_consistency(stored, computed)
    assert status == "PASS"
    assert "2 stored agent" in summary


# ---------------------------------------------------------------------------
# main() integration tests
# ---------------------------------------------------------------------------


def test_main_pass_clean_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """main() prints JSON with status PASS and exits 0 for a clean ledger."""
    import check_total_earned_consistency as mod

    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    history_dir = ledger_dir / "history"
    history_dir.mkdir()

    balances = {
        "version": 1,
        "agents": {
            "agent0@system": {"balance": 990, "total_earned": 0},
            "alice@x": {"balance": 10, "total_earned": 10},
        },
    }
    (ledger_dir / "balances.json").write_text(json.dumps(balances), encoding="utf-8")
    history_line = json.dumps({"type": "payment", "agent": "alice@x", "amount": 10})
    (history_dir / "2026-01-01.jsonl").write_text(history_line + "\n", encoding="utf-8")

    monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)

    exit_code = main()
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert exit_code == 0
    assert result["status"] == "PASS"
    assert result["divergences"] == []
    assert "summary" in result


def test_main_fail_diverging_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """main() exits 1 and reports divergence when stored total_earned is wrong."""
    import check_total_earned_consistency as mod

    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    history_dir = ledger_dir / "history"
    history_dir.mkdir()

    balances = {
        "version": 1,
        "agents": {
            "alice@x": {"balance": 999, "total_earned": 999},
        },
    }
    (ledger_dir / "balances.json").write_text(json.dumps(balances), encoding="utf-8")
    history_line = json.dumps({"type": "payment", "agent": "alice@x", "amount": 10})
    (history_dir / "2026-01-01.jsonl").write_text(history_line + "\n", encoding="utf-8")

    monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)

    exit_code = main()
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert exit_code == 1
    assert result["status"] == "FAIL"
    assert any(d["agent"] == "alice@x" for d in result["divergences"])


def test_main_missing_balances_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """main() exits 1 with FAIL when balances.json is absent."""
    import check_total_earned_consistency as mod

    # No balances.json in tmp_path
    monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)

    exit_code = main()
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert exit_code == 1
    assert result["status"] == "FAIL"
    assert "not found" in result["summary"]


def test_main_multi_object_line_parsed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """main() correctly handles a history line with two concatenated JSON objects."""
    import check_total_earned_consistency as mod

    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    history_dir = ledger_dir / "history"
    history_dir.mkdir()

    # Two trajectory_mints concatenated on one line
    obj1 = {"type": "trajectory_mint", "agents": ["alice@x"], "per_agent": [20], "amount": 20}
    obj2 = {"type": "trajectory_mint", "agents": ["bob@x"], "per_agent": [15], "amount": 15}
    concatenated_line = json.dumps(obj1) + json.dumps(obj2)

    balances = {
        "version": 1,
        "agents": {
            "alice@x": {"balance": 20, "total_earned": 20},
            "bob@x": {"balance": 15, "total_earned": 15},
        },
    }
    (ledger_dir / "balances.json").write_text(json.dumps(balances), encoding="utf-8")
    (history_dir / "2026-01-01.jsonl").write_text(concatenated_line + "\n", encoding="utf-8")

    monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)

    exit_code = main()
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert exit_code == 0
    assert result["status"] == "PASS"
