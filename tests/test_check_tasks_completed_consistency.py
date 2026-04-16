"""Tests for scripts/check_tasks_completed_consistency.py.

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

from check_tasks_completed_consistency import (  # noqa: E402
    check_consistency,
    compute_tasks_completed,
    main,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _agent(tasks_completed: int = 0) -> dict[str, Any]:
    return {"balance": 0, "tasks_completed": tasks_completed}


def _agents(**kwargs: dict[str, Any]) -> dict[str, Any]:
    return kwargs


# ---------------------------------------------------------------------------
# compute_tasks_completed tests
# ---------------------------------------------------------------------------


def test_empty_events_returns_empty_dict():
    """No events → empty dict."""
    result = compute_tasks_completed([])
    assert result == {}


def test_payment_event_counts_issue():
    """A single payment event with amount>0 counts the issue."""
    events = [{"type": "payment", "agent": "alice@x", "amount": 10, "issue": 7}]
    result = compute_tasks_completed(events)
    assert result.get("alice@x") == 1


def test_accept_event_counts_issue():
    """An accept event with amount>0 counts the issue."""
    events = [{"type": "accept", "agent": "bob@x", "amount": 5, "issue": 42}]
    result = compute_tasks_completed(events)
    assert result.get("bob@x") == 1


def test_multiple_payments_same_issue_counted_once():
    """Multiple payment events for the same issue → count 1, not many."""
    events = [
        {"type": "payment", "agent": "alice@x", "amount": 1, "issue": 3, "slot": 1},
        {"type": "payment", "agent": "alice@x", "amount": 2, "issue": 3, "slot": 2},
        {"type": "payment", "agent": "alice@x", "amount": 3, "issue": 3, "slot": 3},
    ]
    result = compute_tasks_completed(events)
    assert result.get("alice@x") == 1


def test_payment_and_accept_same_issue_counted_once():
    """Both payment and accept for the same issue → count 1."""
    events = [
        {"type": "payment", "agent": "alice@x", "amount": 25, "issue": 100},
        {"type": "accept", "agent": "alice@x", "amount": 25, "issue": 100},
    ]
    result = compute_tasks_completed(events)
    assert result.get("alice@x") == 1


def test_different_issues_counted_separately():
    """Two distinct issues → count 2."""
    events = [
        {"type": "payment", "agent": "alice@x", "amount": 10, "issue": 1},
        {"type": "payment", "agent": "alice@x", "amount": 10, "issue": 2},
    ]
    result = compute_tasks_completed(events)
    assert result.get("alice@x") == 2


def test_zero_amount_not_counted():
    """Payment with amount=0 does not count as a completed task."""
    events = [{"type": "payment", "agent": "alice@x", "amount": 0, "issue": 5}]
    result = compute_tasks_completed(events)
    assert result.get("alice@x", 0) == 0


def test_negative_amount_not_counted():
    """Payment with negative amount does not count."""
    events = [{"type": "payment", "agent": "alice@x", "amount": -10, "issue": 5}]
    result = compute_tasks_completed(events)
    assert result.get("alice@x", 0) == 0


def test_missing_issue_field_not_counted():
    """Payment without an 'issue' field is skipped."""
    events = [{"type": "payment", "agent": "alice@x", "amount": 20}]
    result = compute_tasks_completed(events)
    assert result.get("alice@x", 0) == 0


def test_null_issue_field_not_counted():
    """Payment with issue=None is skipped."""
    events = [{"type": "payment", "agent": "alice@x", "amount": 20, "issue": None}]
    result = compute_tasks_completed(events)
    assert result.get("alice@x", 0) == 0


def test_trajectory_mint_not_counted():
    """trajectory_mint events do not count toward tasks_completed."""
    events = [
        {
            "type": "trajectory_mint",
            "agents": ["alice@x"],
            "per_agent": [30],
            "issue": 99,
        }
    ]
    result = compute_tasks_completed(events)
    assert result.get("alice@x", 0) == 0


def test_escrow_events_not_counted():
    """escrow_create and escrow_return events do not count."""
    events = [
        {"type": "escrow_create", "author": "alice@x", "amount": 50, "issue": 10},
        {"type": "escrow_return", "recipient": "alice@x", "amount": 50, "issue": 10},
    ]
    result = compute_tasks_completed(events)
    assert result.get("alice@x", 0) == 0


def test_two_agents_independent_counts():
    """Counts for two agents don't bleed into each other."""
    events = [
        {"type": "payment", "agent": "alice@x", "amount": 10, "issue": 1},
        {"type": "payment", "agent": "bob@x", "amount": 10, "issue": 2},
        {"type": "payment", "agent": "bob@x", "amount": 10, "issue": 3},
    ]
    result = compute_tasks_completed(events)
    assert result.get("alice@x") == 1
    assert result.get("bob@x") == 2


# ---------------------------------------------------------------------------
# check_consistency tests
# ---------------------------------------------------------------------------


def test_clean_match_returns_pass():
    """Stored tasks_completed matches computed → PASS, no divergences."""
    stored = _agents(**{"alice@x": _agent(tasks_completed=2)})
    computed = {"alice@x": 2}
    status, divergences, warnings, summary = check_consistency(stored, computed)
    assert status == "PASS"
    assert divergences == []


def test_stored_higher_than_computed_returns_fail():
    """Stored tasks_completed > computed → FAIL with divergence entry."""
    stored = _agents(**{"alice@x": _agent(tasks_completed=5)})
    computed = {"alice@x": 3}
    status, divergences, warnings, _ = check_consistency(stored, computed)
    assert status == "FAIL"
    assert len(divergences) == 1
    d = divergences[0]
    assert d["agent"] == "alice@x"
    assert d["field"] == "tasks_completed"
    assert d["stored"] == 5
    assert d["computed"] == 3


def test_stored_lower_than_computed_returns_fail():
    """Stored tasks_completed < computed → FAIL with divergence entry."""
    stored = _agents(**{"alice@x": _agent(tasks_completed=1)})
    computed = {"alice@x": 4}
    status, divergences, _, _ = check_consistency(stored, computed)
    assert status == "FAIL"
    d = divergences[0]
    assert d["stored"] == 1
    assert d["computed"] == 4


def test_agent0_excluded_from_divergences():
    """agent0@system is never reported as a divergence."""
    stored = _agents(**{"agent0@system": _agent(tasks_completed=99)})
    computed = {"agent0@system": 0}
    status, divergences, _, _ = check_consistency(stored, computed)
    assert status == "PASS"
    assert all(d["agent"] != "agent0@system" for d in divergences)


def test_missing_tasks_completed_field_treated_as_zero():
    """Agent entry without tasks_completed defaults to 0."""
    stored = {"alice@x": {"balance": 100}}  # no tasks_completed key
    computed = {"alice@x": 0}
    status, divergences, _, _ = check_consistency(stored, computed)
    assert status == "PASS"


def test_missing_tasks_completed_field_diverges_when_computed_nonzero():
    """Agent without tasks_completed stored (defaults to 0) diverges when computed > 0."""
    stored = {"alice@x": {"balance": 100}}
    computed = {"alice@x": 3}
    status, divergences, _, _ = check_consistency(stored, computed)
    assert status == "FAIL"
    assert divergences[0]["stored"] == 0
    assert divergences[0]["computed"] == 3


def test_history_only_agent_emits_warning_not_fail():
    """Agent with computed > 0 but absent from stored → warning, status stays PASS."""
    stored: dict[str, Any] = {}
    computed = {"ghost@x": 2}
    status, divergences, warnings, _ = check_consistency(stored, computed)
    assert status == "PASS"
    assert divergences == []
    assert any(w["agent"] == "ghost@x" for w in warnings)
    assert warnings[0]["computed_tasks_completed"] == 2


def test_empty_stored_and_empty_computed_pass():
    """No agents, no history → PASS."""
    status, divergences, warnings, summary = check_consistency({}, {})
    assert status == "PASS"
    assert divergences == []
    assert "0 divergence" in summary


def test_multiple_diverging_agents_all_reported():
    """Multiple agents with divergences are all listed."""
    stored = _agents(
        **{
            "alice@x": _agent(tasks_completed=5),
            "bob@x": _agent(tasks_completed=3),
            "carol@x": _agent(tasks_completed=2),
        }
    )
    computed = {"alice@x": 4, "bob@x": 3, "carol@x": 1}
    status, divergences, _, _ = check_consistency(stored, computed)
    assert status == "FAIL"
    agents = {d["agent"] for d in divergences}
    assert "alice@x" in agents
    assert "carol@x" in agents
    assert "bob@x" not in agents  # matches exactly


# ---------------------------------------------------------------------------
# main() integration tests
# ---------------------------------------------------------------------------


def test_main_json_output_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """main() prints JSON with status PASS and exits 0 for a clean ledger."""
    import check_tasks_completed_consistency as mod

    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    history_dir = ledger_dir / "history"
    history_dir.mkdir()

    balances = {
        "version": 1,
        "agents": {
            "agent0@system": {"balance": 100, "tasks_completed": 0},
            "alice@x": {"balance": 20, "tasks_completed": 2},
        },
    }
    (ledger_dir / "balances.json").write_text(
        json.dumps(balances), encoding="utf-8"
    )

    lines = "\n".join(
        [
            json.dumps({"type": "payment", "agent": "alice@x", "amount": 10, "issue": 1}),
            json.dumps({"type": "accept", "agent": "alice@x", "amount": 10, "issue": 5}),
        ]
    )
    (history_dir / "2026-01-01.jsonl").write_text(lines + "\n", encoding="utf-8")

    monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)

    exit_code = main()
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert exit_code == 0
    assert result["status"] == "PASS"
    assert result["divergences"] == []
    assert "summary" in result


def test_main_json_output_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """main() prints JSON with status FAIL and exits 1 when divergence exists."""
    import check_tasks_completed_consistency as mod

    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    history_dir = ledger_dir / "history"
    history_dir.mkdir()

    # Stored says 5 but history only has 2 distinct issues.
    balances = {
        "version": 1,
        "agents": {
            "alice@x": {"balance": 50, "tasks_completed": 5},
        },
    }
    (ledger_dir / "balances.json").write_text(
        json.dumps(balances), encoding="utf-8"
    )

    lines = "\n".join(
        [
            json.dumps({"type": "payment", "agent": "alice@x", "amount": 10, "issue": 1}),
            json.dumps({"type": "payment", "agent": "alice@x", "amount": 10, "issue": 2}),
        ]
    )
    (history_dir / "2026-01-01.jsonl").write_text(lines + "\n", encoding="utf-8")

    monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)

    exit_code = main()
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert exit_code == 1
    assert result["status"] == "FAIL"
    assert len(result["divergences"]) == 1
    div = result["divergences"][0]
    assert div["agent"] == "alice@x"
    assert div["stored"] == 5
    assert div["computed"] == 2


def test_main_missing_balances_exits_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """main() exits 1 when balances.json is absent."""
    import check_tasks_completed_consistency as mod

    (tmp_path / "ledger").mkdir()
    monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)

    exit_code = main()
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert exit_code == 1
    assert result["status"] == "FAIL"
    assert "not found" in result["summary"]


def test_main_malformed_balances_exits_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """main() exits 1 when balances.json contains invalid JSON."""
    import check_tasks_completed_consistency as mod

    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    (ledger_dir / "balances.json").write_text("{not valid json", encoding="utf-8")

    monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)

    exit_code = main()
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert exit_code == 1
    assert result["status"] == "FAIL"
    assert "not valid JSON" in result["summary"]
