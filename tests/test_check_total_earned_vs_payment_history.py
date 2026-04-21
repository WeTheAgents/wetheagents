"""Tests for scripts/check_total_earned_vs_payment_history.py.

All tests are fully in-memory; no real ledger files are accessed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from check_total_earned_vs_payment_history import (  # noqa: E402
    _extract_objects,
    check_consistency,
    compute_total_earned,
    main,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _agent(total_earned: int = 0) -> dict[str, Any]:
    return {"balance": total_earned, "total_earned": total_earned}


# ---------------------------------------------------------------------------
# _extract_objects tests
# ---------------------------------------------------------------------------


def test_extract_single_object():
    line = '{"type": "payment", "agent": "alice@x", "amount": 10}'
    result = _extract_objects(line)
    assert len(result) == 1
    assert result[0]["type"] == "payment"


def test_extract_two_concatenated_objects():
    a = '{"type": "payment", "agent": "alice@x", "amount": 10}'
    b = '{"type": "accept", "agent": "bob@x", "amount": 5}'
    result = _extract_objects(a + b)
    assert len(result) == 2
    assert result[0]["agent"] == "alice@x"
    assert result[1]["agent"] == "bob@x"


def test_extract_empty_string_returns_empty():
    assert _extract_objects("") == []


def test_extract_invalid_json_returns_empty():
    result = _extract_objects(r'{"note": "bad \! escape"}')
    assert result == []


def test_extract_whitespace_between_objects():
    a = '{"type": "payment", "amount": 1}'
    b = '{"type": "accept", "amount": 2}'
    result = _extract_objects(a + "  " + b)
    assert len(result) == 2


# ---------------------------------------------------------------------------
# compute_total_earned tests
# ---------------------------------------------------------------------------


def test_empty_events_returns_empty():
    assert compute_total_earned([]) == {}


def test_payment_credits_agent():
    events = [{"type": "payment", "agent": "alice@x", "amount": 50}]
    result = compute_total_earned(events)
    assert result.get("alice@x") == 50


def test_accept_credits_agent():
    events = [{"type": "accept", "agent": "bob@x", "amount": 20}]
    result = compute_total_earned(events)
    assert result.get("bob@x") == 20


def test_payment_zero_not_counted():
    events = [{"type": "payment", "agent": "alice@x", "amount": 0}]
    assert compute_total_earned(events).get("alice@x", 0) == 0


def test_payment_negative_not_counted():
    events = [{"type": "payment", "agent": "alice@x", "amount": -5}]
    assert compute_total_earned(events).get("alice@x", 0) == 0


def test_trajectory_mint_multi_agent_format():
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
    events = [{"type": "trajectory_mint", "agent": "charlie@x", "amount": 30}]
    result = compute_total_earned(events)
    assert result.get("charlie@x") == 30


def test_trajectory_mint_to_field_format():
    """trajectory_mint with 'to' field (older heartbeat format) credits the recipient."""
    events = [
        {
            "type": "trajectory_mint",
            "trajectory": "T1",
            "slot": 23,
            "amount": 42,
            "to": "alice@x",
        }
    ]
    result = compute_total_earned(events)
    assert result.get("alice@x") == 42


def test_trajectory_mint_to_field_not_double_counted_with_agent():
    """If both 'agent' and 'to' fields exist, 'agent' takes precedence."""
    events = [
        {
            "type": "trajectory_mint",
            "amount": 10,
            "agent": "alice@x",
            "to": "other@x",
        }
    ]
    result = compute_total_earned(events)
    # 'agent' wins (it's checked first), 'other@x' is not credited
    assert result.get("alice@x") == 10
    assert result.get("other@x", 0) == 0


def test_trajectory_mint_partial_per_agent_list():
    """Extra agents beyond per_agent list receive nothing."""
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


def test_escrow_create_not_counted():
    events = [
        {"type": "escrow_create", "author": "alice@x", "amount": 100, "issue": 1}
    ]
    assert compute_total_earned(events).get("alice@x", 0) == 0


def test_escrow_return_not_counted():
    """escrow_return is outside the payment event spec for this script."""
    events = [
        {"type": "escrow_return", "recipient": "alice@x", "amount": 40, "issue": 7}
    ]
    assert compute_total_earned(events).get("alice@x", 0) == 0


def test_multiple_events_accumulate():
    events = [
        {"type": "payment", "agent": "alice@x", "amount": 20},
        {"type": "accept", "agent": "alice@x", "amount": 15},
        {"type": "trajectory_mint", "agent": "alice@x", "amount": 25},
    ]
    assert compute_total_earned(events).get("alice@x") == 60


def test_agent_with_no_payment_history():
    """Agent in balances with total_earned=0 and no history events: PASS."""
    events: list[dict[str, Any]] = []
    stored = {"alice@x": _agent(total_earned=0)}
    status, divs, warnings, summary = check_consistency(stored, compute_total_earned(events))
    assert status == "PASS"
    assert divs == []


def test_payments_from_other_agents_excluded():
    """Only the matching agent's payments are counted; other agents' amounts don't bleed."""
    events = [
        {"type": "payment", "agent": "alice@x", "amount": 50},
        {"type": "payment", "agent": "bob@x", "amount": 30},
    ]
    result = compute_total_earned(events)
    assert result.get("alice@x") == 50
    assert result.get("bob@x") == 30


def test_ignored_event_types():
    events = [
        {"type": "verification", "agent": "alice@x", "amount": 999},
        {"type": "claim", "agent": "alice@x", "amount": 50},
        {"type": "escrow", "agent": "alice@x", "amount": 50},
        {"type": "reversal", "agent": "alice@x", "amount": 50},
        {"type": "economy_reset"},
    ]
    assert compute_total_earned(events).get("alice@x", 0) == 0


# ---------------------------------------------------------------------------
# check_consistency tests
# ---------------------------------------------------------------------------


def test_consistency_pass_when_match():
    stored = {"alice@x": _agent(total_earned=50)}
    computed = {"alice@x": 50}
    status, divs, warnings, summary = check_consistency(stored, computed)
    assert status == "PASS"
    assert divs == []


def test_consistency_fail_on_mismatch():
    stored = {"alice@x": _agent(total_earned=100)}
    computed = {"alice@x": 80}
    status, divs, warnings, summary = check_consistency(stored, computed)
    assert status == "FAIL"
    assert len(divs) == 1
    d = divs[0]
    assert d["agent"] == "alice@x"
    assert d["stored"] == 100
    assert d["computed"] == 80
    assert d["delta"] == -20


def test_consistency_agent0_excluded():
    stored = {"agent0@system": _agent(total_earned=9999)}
    computed = {"agent0@system": 0}
    status, divs, warnings, summary = check_consistency(stored, computed)
    assert status == "PASS"
    assert all(d["agent"] != "agent0@system" for d in divs)


def test_consistency_history_only_agent_is_warning_not_fail():
    stored: dict[str, Any] = {}
    computed = {"ghost@x": 50}
    status, divs, warnings, summary = check_consistency(stored, computed)
    assert status == "PASS"
    assert divs == []
    assert any(w["agent"] == "ghost@x" for w in warnings)


def test_consistency_zero_history_agent_no_warning():
    stored: dict[str, Any] = {}
    computed = {"silent@x": 0}
    status, divs, warnings, summary = check_consistency(stored, computed)
    assert warnings == []


def test_consistency_multiple_agents_only_diverging_reported():
    stored = {
        "alice@x": _agent(total_earned=100),
        "bob@x": _agent(total_earned=200),
    }
    computed = {"alice@x": 80, "bob@x": 200}
    status, divs, warnings, summary = check_consistency(stored, computed)
    assert status == "FAIL"
    agents_with_div = {d["agent"] for d in divs}
    assert "alice@x" in agents_with_div
    assert "bob@x" not in agents_with_div


def test_consistency_empty_pass():
    status, divs, warnings, summary = check_consistency({}, {})
    assert status == "PASS"
    assert "0 divergence" in summary


def test_consistency_summary_counts_stored_agents():
    stored = {
        "agent0@system": _agent(total_earned=0),
        "alice@x": _agent(total_earned=10),
        "bob@x": _agent(total_earned=20),
    }
    computed = {"alice@x": 10, "bob@x": 20}
    status, divs, warnings, summary = check_consistency(stored, computed)
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
    """main() prints JSON with status PASS and exits 0 for a consistent ledger."""
    import check_total_earned_vs_payment_history as mod

    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    history_dir = ledger_dir / "history"
    history_dir.mkdir()

    balances = {
        "agents": {
            "agent0@system": {"balance": 990, "total_earned": 0},
            "alice@x": {"balance": 10, "total_earned": 10},
        }
    }
    (ledger_dir / "balances.json").write_text(json.dumps(balances), encoding="utf-8")
    line = json.dumps({"type": "payment", "agent": "alice@x", "amount": 10})
    (history_dir / "2026-01-01.jsonl").write_text(line + "\n", encoding="utf-8")

    monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)

    code = main()
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["status"] == "PASS"
    assert out["divergences"] == []


def test_main_fail_diverging_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """main() exits 1 when total_earned doesn't match payment history."""
    import check_total_earned_vs_payment_history as mod

    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    history_dir = ledger_dir / "history"
    history_dir.mkdir()

    balances = {
        "agents": {"alice@x": {"balance": 999, "total_earned": 999}}
    }
    (ledger_dir / "balances.json").write_text(json.dumps(balances), encoding="utf-8")
    line = json.dumps({"type": "payment", "agent": "alice@x", "amount": 10})
    (history_dir / "2026-01-01.jsonl").write_text(line + "\n", encoding="utf-8")

    monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)

    code = main()
    out = json.loads(capsys.readouterr().out)
    assert code == 1
    assert out["status"] == "FAIL"
    assert any(d["agent"] == "alice@x" for d in out["divergences"])


def test_main_missing_balances_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """main() exits 1 with FAIL when balances.json is absent."""
    import check_total_earned_vs_payment_history as mod

    monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)

    code = main()
    out = json.loads(capsys.readouterr().out)
    assert code == 1
    assert out["status"] == "FAIL"
    assert "not found" in out["summary"]


def test_main_to_field_trajectory_mint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """main() correctly handles trajectory_mint with 'to' field (heartbeat format)."""
    import check_total_earned_vs_payment_history as mod

    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    history_dir = ledger_dir / "history"
    history_dir.mkdir()

    balances = {
        "agents": {"alice@x": {"balance": 42, "total_earned": 42}}
    }
    (ledger_dir / "balances.json").write_text(json.dumps(balances), encoding="utf-8")
    event = {
        "type": "trajectory_mint",
        "trajectory": "T1",
        "slot": 23,
        "amount": 42,
        "to": "alice@x",
    }
    (history_dir / "2026-04-19.jsonl").write_text(json.dumps(event) + "\n", encoding="utf-8")

    monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)

    code = main()
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["status"] == "PASS"


def test_main_multi_object_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """main() handles a history line with two concatenated JSON objects."""
    import check_total_earned_vs_payment_history as mod

    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    history_dir = ledger_dir / "history"
    history_dir.mkdir()

    obj1 = {"type": "trajectory_mint", "agents": ["alice@x"], "per_agent": [20], "amount": 20}
    obj2 = {"type": "trajectory_mint", "agents": ["bob@x"], "per_agent": [15], "amount": 15}
    line = json.dumps(obj1) + json.dumps(obj2)

    balances = {
        "agents": {
            "alice@x": {"balance": 20, "total_earned": 20},
            "bob@x": {"balance": 15, "total_earned": 15},
        }
    }
    (ledger_dir / "balances.json").write_text(json.dumps(balances), encoding="utf-8")
    (history_dir / "2026-01-01.jsonl").write_text(line + "\n", encoding="utf-8")

    monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)

    code = main()
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["status"] == "PASS"
