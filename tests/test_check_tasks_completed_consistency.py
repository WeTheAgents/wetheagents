"""Tests for scripts/check_tasks_completed_consistency.py.

All tests are fully in-memory; no real ledger files are accessed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from check_tasks_completed_consistency import (  # noqa: E402
    check_consistency,
    compute_tasks_completed,
    compute_tasks_created,
    main,
    _TOLERANCE,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _agent(tasks_completed: int = 0, tasks_created: int = 0) -> dict[str, Any]:
    return {"balance": 0, "tasks_completed": tasks_completed, "tasks_created": tasks_created}


def _pass(stored: dict, completed: dict, created: dict | None = None):
    """Call check_consistency and return (status, divergences, warnings, summary)."""
    return check_consistency(stored, completed, created or {})


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
# compute_tasks_created tests
# ---------------------------------------------------------------------------


def test_escrow_create_counts_per_author():
    """escrow_create events counted per author."""
    events = [
        {"type": "escrow_create", "author": "alice@x", "amount": 10, "issue": 1},
        {"type": "escrow_create", "author": "alice@x", "amount": 10, "issue": 2},
        {"type": "escrow_create", "author": "bob@x", "amount": 10, "issue": 3},
    ]
    result = compute_tasks_created(events)
    assert result.get("alice@x") == 2
    assert result.get("bob@x") == 1


def test_non_escrow_create_not_counted_in_created():
    """payment and accept events don't count toward tasks_created."""
    events = [
        {"type": "payment", "agent": "alice@x", "amount": 10, "issue": 1},
        {"type": "accept", "agent": "alice@x", "amount": 10, "issue": 2},
    ]
    result = compute_tasks_created(events)
    assert result.get("alice@x", 0) == 0


def test_escrow_create_missing_author_skipped():
    """escrow_create without author field is skipped."""
    events = [{"type": "escrow_create", "amount": 10, "issue": 1}]
    result = compute_tasks_created(events)
    assert result == {}


# ---------------------------------------------------------------------------
# check_consistency tests
# ---------------------------------------------------------------------------


def test_clean_match_returns_pass():
    """Stored tasks_completed matches computed → PASS, no divergences."""
    stored = {"alice@x": _agent(tasks_completed=2)}
    status, divergences, warnings, summary = _pass(stored, {"alice@x": 2})
    assert status == "PASS"
    assert divergences == []


def test_within_tolerance_returns_pass():
    """Divergence of exactly _TOLERANCE → PASS (boundary, inclusive)."""
    stored = {"alice@x": _agent(tasks_completed=10)}
    computed = {"alice@x": 10 - _TOLERANCE}  # diff == 5
    status, divergences, _, _ = _pass(stored, computed)
    assert status == "PASS"
    assert divergences == []


def test_just_over_tolerance_returns_fail():
    """Divergence of _TOLERANCE + 1 → FAIL."""
    stored = {"alice@x": _agent(tasks_completed=10)}
    computed = {"alice@x": 10 - (_TOLERANCE + 1)}  # diff == 6
    status, divergences, _, _ = _pass(stored, computed)
    assert status == "FAIL"
    assert len(divergences) == 1
    assert divergences[0]["field"] == "tasks_completed"


def test_tasks_completed_off_by_more_than_5_fails():
    """tasks_completed stored=12, computed=2 (diff=10) → FAIL."""
    stored = {"alice@x": _agent(tasks_completed=12)}
    computed = {"alice@x": 2}
    status, divergences, _, _ = _pass(stored, computed)
    assert status == "FAIL"
    d = divergences[0]
    assert d["agent"] == "alice@x"
    assert d["field"] == "tasks_completed"
    assert d["stored"] == 12
    assert d["computed"] == 2
    assert d["diff"] == 10


def test_stored_higher_than_computed_by_more_than_tolerance():
    """Stored tasks_completed > computed + tolerance → FAIL with divergence entry."""
    stored = {"alice@x": _agent(tasks_completed=9)}
    computed = {"alice@x": 2}  # diff = 7 > 5
    status, divergences, warnings, _ = _pass(stored, computed)
    assert status == "FAIL"
    assert len(divergences) == 1
    d = divergences[0]
    assert d["agent"] == "alice@x"
    assert d["field"] == "tasks_completed"
    assert d["stored"] == 9
    assert d["computed"] == 2


def test_stored_lower_than_computed_by_more_than_tolerance():
    """Stored tasks_completed < computed - tolerance → FAIL with divergence entry."""
    stored = {"alice@x": _agent(tasks_completed=1)}
    computed = {"alice@x": 8}  # diff = 7 > 5
    status, divergences, _, _ = _pass(stored, computed)
    assert status == "FAIL"
    d = divergences[0]
    assert d["stored"] == 1
    assert d["computed"] == 8


def test_agent0_excluded_from_divergences():
    """agent0@system is never reported as a divergence."""
    stored = {"agent0@system": _agent(tasks_completed=99)}
    computed = {"agent0@system": 0}
    status, divergences, _, _ = _pass(stored, computed)
    assert status == "PASS"
    assert all(d["agent"] != "agent0@system" for d in divergences)


def test_zero_history_agent_returns_pass():
    """Agent in balances with tasks_completed=0 and no history events → PASS."""
    stored = {"newbie@x": _agent(tasks_completed=0)}
    computed: dict[str, int] = {}  # agent not in history at all
    status, divergences, _, _ = _pass(stored, computed)
    assert status == "PASS"
    assert divergences == []


def test_agent_not_in_history_zero_stored_pass():
    """Agent absent from history defaults to computed=0; stored=0 → PASS."""
    stored = {"ghost@x": {"balance": 50, "tasks_completed": 0}}
    status, divergences, _, _ = _pass(stored, {})
    assert status == "PASS"
    assert divergences == []


def test_missing_tasks_completed_field_treated_as_zero():
    """Agent entry without tasks_completed defaults to 0."""
    stored = {"alice@x": {"balance": 100}}  # no tasks_completed key
    computed = {"alice@x": 0}
    status, divergences, _, _ = _pass(stored, computed)
    assert status == "PASS"


def test_missing_tasks_completed_field_diverges_when_computed_over_tolerance():
    """Agent without tasks_completed (defaults 0) diverges when computed > tolerance."""
    stored = {"alice@x": {"balance": 100}}
    computed = {"alice@x": _TOLERANCE + 1}  # diff == 6
    status, divergences, _, _ = _pass(stored, computed)
    assert status == "FAIL"
    assert divergences[0]["stored"] == 0
    assert divergences[0]["computed"] == _TOLERANCE + 1


def test_history_only_agent_emits_warning_not_fail():
    """Agent with computed > 0 but absent from stored → warning, status stays PASS."""
    stored: dict[str, Any] = {}
    computed = {"ghost@x": 2}
    status, divergences, warnings, _ = _pass(stored, computed)
    assert status == "PASS"
    assert divergences == []
    assert any(w["agent"] == "ghost@x" for w in warnings)
    assert warnings[0]["computed_tasks_completed"] == 2


def test_empty_stored_and_empty_computed_pass():
    """No agents, no history → PASS."""
    status, divergences, warnings, summary = _pass({}, {})
    assert status == "PASS"
    assert divergences == []
    assert "0 divergence" in summary


def test_multiple_diverging_agents_all_reported():
    """Multiple agents with large divergences are all listed; non-diverging excluded."""
    stored = {
        "alice@x": _agent(tasks_completed=15),
        "bob@x": _agent(tasks_completed=3),
        "carol@x": _agent(tasks_completed=12),
    }
    computed = {"alice@x": 6, "bob@x": 3, "carol@x": 4}  # alice diff=9, bob=0, carol=8
    status, divergences, _, _ = _pass(stored, computed)
    assert status == "FAIL"
    agents = {d["agent"] for d in divergences}
    assert "alice@x" in agents
    assert "carol@x" in agents
    assert "bob@x" not in agents  # exactly matches


def test_tasks_created_divergence_beyond_tolerance_fails():
    """tasks_created off by more than tolerance → FAIL."""
    stored = {"alice@x": _agent(tasks_completed=0, tasks_created=20)}
    status, divergences, _, _ = check_consistency(stored, {}, {"alice@x": 5})
    assert status == "FAIL"
    d = next(x for x in divergences if x["field"] == "tasks_created")
    assert d["stored"] == 20
    assert d["computed"] == 5
    assert d["diff"] == 15


def test_tasks_created_within_tolerance_passes():
    """tasks_created diff <= tolerance → PASS."""
    stored = {"alice@x": _agent(tasks_completed=0, tasks_created=5)}
    status, divergences, _, _ = check_consistency(stored, {}, {"alice@x": 2})  # diff=3
    assert status == "PASS"
    assert all(d["field"] != "tasks_created" for d in divergences)


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
            "agent0@system": {"balance": 100, "tasks_completed": 0, "tasks_created": 0},
            "alice@x": {"balance": 20, "tasks_completed": 2, "tasks_created": 0},
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

    monkeypatch.setattr(mod, "_repo_root", lambda override=None: tmp_path)

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
    """main() prints JSON with status FAIL and exits 1 when divergence > tolerance."""
    import check_tasks_completed_consistency as mod

    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    history_dir = ledger_dir / "history"
    history_dir.mkdir()

    # Stored says 12 but history only has 2 distinct issues (diff=10 > tolerance).
    balances = {
        "version": 1,
        "agents": {
            "alice@x": {"balance": 50, "tasks_completed": 12, "tasks_created": 0},
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

    monkeypatch.setattr(mod, "_repo_root", lambda override=None: tmp_path)

    exit_code = main()
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert exit_code == 1
    assert result["status"] == "FAIL"
    assert len(result["divergences"]) == 1
    div = result["divergences"][0]
    assert div["agent"] == "alice@x"
    assert div["stored"] == 12
    assert div["computed"] == 2


def test_main_missing_balances_exits_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """main() exits 1 when balances.json is absent."""
    import check_tasks_completed_consistency as mod

    (tmp_path / "ledger").mkdir()
    monkeypatch.setattr(mod, "_repo_root", lambda override=None: tmp_path)

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

    monkeypatch.setattr(mod, "_repo_root", lambda override=None: tmp_path)

    exit_code = main()
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert exit_code == 1
    assert result["status"] == "FAIL"
    assert "not valid JSON" in result["summary"]
