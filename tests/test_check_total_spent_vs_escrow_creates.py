"""Tests for scripts/check_total_spent_vs_escrow_creates.py.

All tests are fully in-memory; no real ledger files are accessed.
Covers both old-format (type+author) and new-format (op+from) events.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from check_total_spent_vs_escrow_creates import (  # noqa: E402
    _extract_objects,
    _is_escrow_create,
    check_consistency,
    compute_spent_from_field,
    main,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _agent(total_spent: int = 0) -> dict[str, Any]:
    return {"balance": 100, "total_spent": total_spent}


def _new_event(from_agent: str, amount: int, issue: int = 1) -> dict[str, Any]:
    """New-format escrow_create event (op + from)."""
    return {"op": "escrow_create", "from": from_agent, "amount": amount, "issue": issue}


def _old_event(author: str, amount: int, issue: int = 1) -> dict[str, Any]:
    """Old-format escrow_create event (type + author, NO from field)."""
    return {"type": "escrow_create", "author": author, "amount": amount, "issue": issue}


def _old_event_with_from(from_agent: str, amount: int, issue: int = 1) -> dict[str, Any]:
    """Old-format event that also has a from field (hybrid)."""
    return {
        "type": "escrow_create",
        "author": from_agent,
        "from": from_agent,
        "amount": amount,
        "issue": issue,
    }


# ---------------------------------------------------------------------------
# _is_escrow_create tests
# ---------------------------------------------------------------------------


def test_is_escrow_create_new_format() -> None:
    """op==escrow_create recognised as escrow_create event."""
    assert _is_escrow_create({"op": "escrow_create", "from": "alice@x", "amount": 10})


def test_is_escrow_create_old_format() -> None:
    """type==escrow_create recognised as escrow_create event."""
    assert _is_escrow_create({"type": "escrow_create", "author": "alice@x", "amount": 10})


def test_is_escrow_create_payment_false() -> None:
    """payment event is NOT escrow_create."""
    assert not _is_escrow_create({"type": "payment", "agent": "alice@x", "amount": 10})


def test_is_escrow_create_empty_dict_false() -> None:
    """Empty dict is NOT escrow_create."""
    assert not _is_escrow_create({})


# ---------------------------------------------------------------------------
# compute_spent_from_field tests
# ---------------------------------------------------------------------------


def test_compute_empty_events_returns_empty() -> None:
    """No events → empty result."""
    assert compute_spent_from_field([]) == {}


def test_compute_new_format_event_counted() -> None:
    """New-format (op+from) event is counted via from field."""
    events = [_new_event("alice@x", 30)]
    result = compute_spent_from_field(events)
    assert result.get("alice@x") == 30


def test_compute_old_format_no_from_skipped() -> None:
    """Old-format event with author but no from field is skipped."""
    events = [_old_event("alice@x", 50)]
    result = compute_spent_from_field(events)
    assert result == {}


def test_compute_old_format_with_from_counted() -> None:
    """Old-format event that ALSO has a from field IS counted."""
    events = [_old_event_with_from("alice@x", 20)]
    result = compute_spent_from_field(events)
    assert result.get("alice@x") == 20


def test_compute_multiple_new_events_accumulate() -> None:
    """Multiple new-format events for same agent accumulate correctly."""
    events = [
        _new_event("alice@x", 10, issue=1),
        _new_event("alice@x", 15, issue=2),
        _new_event("alice@x", 5, issue=3),
    ]
    result = compute_spent_from_field(events)
    assert result.get("alice@x") == 30


def test_compute_multiple_agents_independent() -> None:
    """Events for different agents are summed independently."""
    events = [
        _new_event("alice@x", 20, issue=1),
        _new_event("bob@x", 35, issue=2),
        _new_event("alice@x", 10, issue=3),
    ]
    result = compute_spent_from_field(events)
    assert result.get("alice@x") == 30
    assert result.get("bob@x") == 35


def test_compute_non_escrow_create_ignored() -> None:
    """Non-escrow_create events do not contribute to spent totals."""
    events = [
        {"type": "payment", "from": "alice@x", "amount": 100},
        {"op": "accept", "from": "alice@x", "amount": 50},
        {"op": "trajectory_mint", "from": "alice@x", "amount": 40},
        {"type": "escrow_return", "from": "alice@x", "amount": 25},
        _new_event("alice@x", 7, issue=1),
    ]
    result = compute_spent_from_field(events)
    assert result.get("alice@x") == 7


def test_compute_missing_from_field_skipped() -> None:
    """escrow_create without from field is silently skipped."""
    events = [{"op": "escrow_create", "amount": 99, "issue": 1}]
    result = compute_spent_from_field(events)
    assert result == {}


def test_compute_empty_from_field_skipped() -> None:
    """escrow_create with empty string from field is skipped."""
    events = [{"op": "escrow_create", "from": "", "amount": 50, "issue": 1}]
    result = compute_spent_from_field(events)
    assert result == {}


def test_compute_mixed_old_and_new_only_new_counted() -> None:
    """Mix of old (no from) and new (with from) events: only new counted."""
    events = [
        _old_event("alice@x", 100, issue=1),   # no from — skipped
        _new_event("alice@x", 40, issue=2),    # has from — counted
        _old_event("alice@x", 60, issue=3),    # no from — skipped
    ]
    result = compute_spent_from_field(events)
    assert result.get("alice@x") == 40


# ---------------------------------------------------------------------------
# check_consistency tests
# ---------------------------------------------------------------------------


def test_check_consistency_pass_match() -> None:
    """Recorded matches computed → PASS with no divergences."""
    stored = {"alice@x": _agent(total_spent=30)}
    computed = {"alice@x": 30}
    status, divergences, summary = check_consistency(stored, computed)
    assert status == "PASS"
    assert divergences == []


def test_check_consistency_fail_over_recorded() -> None:
    """Recorded > computed → FAIL, negative delta."""
    stored = {"alice@x": _agent(total_spent=100)}
    computed = {"alice@x": 60}
    status, divergences, summary = check_consistency(stored, computed)
    assert status == "FAIL"
    assert len(divergences) == 1
    div = divergences[0]
    assert div["agent"] == "alice@x"
    assert div["recorded"] == 100
    assert div["computed"] == 60
    assert div["delta"] == -40


def test_check_consistency_fail_under_recorded() -> None:
    """Recorded < computed → FAIL, positive delta."""
    stored = {"alice@x": _agent(total_spent=10)}
    computed = {"alice@x": 50}
    status, divergences, summary = check_consistency(stored, computed)
    assert status == "FAIL"
    assert len(divergences) == 1
    div = divergences[0]
    assert div["delta"] == 40  # 50 - 10


def test_check_consistency_zero_recorded_no_history_pass() -> None:
    """Agent with total_spent=0 and no events → PASS."""
    stored = {"alice@x": _agent(total_spent=0)}
    computed: dict[str, int] = {}
    status, divergences, _ = check_consistency(stored, computed)
    assert status == "PASS"
    assert divergences == []


def test_check_consistency_zero_recorded_nonzero_history_fail() -> None:
    """total_spent=0 but history shows spending → FAIL."""
    stored = {"alice@x": _agent(total_spent=0)}
    computed = {"alice@x": 75}
    status, divergences, _ = check_consistency(stored, computed)
    assert status == "FAIL"
    assert any(d["agent"] == "alice@x" for d in divergences)


def test_check_consistency_agent0_excluded() -> None:
    """agent0@system divergence does NOT cause FAIL."""
    stored = {"agent0@system": _agent(total_spent=9999)}
    computed = {"agent0@system": 1}
    status, divergences, _ = check_consistency(stored, computed)
    assert status == "PASS"
    assert all(d["agent"] != "agent0@system" for d in divergences)


def test_check_consistency_mixed_pass_and_fail() -> None:
    """Only diverging agents appear in divergences."""
    stored = {
        "alice@x": _agent(total_spent=50),   # match
        "bob@x": _agent(total_spent=200),    # mismatch
        "charlie@x": _agent(total_spent=0),  # match (zero)
    }
    computed = {"alice@x": 50, "bob@x": 150}
    status, divergences, _ = check_consistency(stored, computed)
    assert status == "FAIL"
    agents_with_div = {d["agent"] for d in divergences}
    assert "bob@x" in agents_with_div
    assert "alice@x" not in agents_with_div
    assert "charlie@x" not in agents_with_div


def test_check_consistency_ghost_agent_in_history_skipped() -> None:
    """Agent in computed but not in balances.json is silently skipped."""
    computed = {"ghost@x": 100}
    stored: dict[str, Any] = {}
    status, divergences, _ = check_consistency(stored, computed)
    assert status == "PASS"
    assert divergences == []


def test_check_consistency_summary_reflects_count() -> None:
    """Summary includes the number of checked agents (excluding agent0)."""
    stored = {
        "agent0@system": _agent(total_spent=9999),
        "alice@x": _agent(total_spent=10),
        "bob@x": _agent(total_spent=20),
    }
    computed = {"alice@x": 10, "bob@x": 20}
    status, _, summary = check_consistency(stored, computed)
    assert status == "PASS"
    assert "2" in summary


# ---------------------------------------------------------------------------
# _extract_objects tests
# ---------------------------------------------------------------------------


def test_extract_single_object() -> None:
    """Single JSON object on a line is extracted."""
    line = '{"op": "escrow_create", "from": "alice@x", "amount": 10}'
    result = _extract_objects(line)
    assert len(result) == 1
    assert result[0]["op"] == "escrow_create"


def test_extract_two_concatenated_objects() -> None:
    """Two concatenated JSON objects on one line are both extracted."""
    a = '{"op": "escrow_create", "from": "alice@x", "amount": 10, "issue": 1}'
    b = '{"op": "escrow_create", "from": "bob@x", "amount": 20, "issue": 2}'
    result = _extract_objects(a + b)
    assert len(result) == 2
    assert result[0]["from"] == "alice@x"
    assert result[1]["from"] == "bob@x"


def test_extract_invalid_json_returns_empty() -> None:
    """Invalid JSON line is silently skipped."""
    line = r'{"note": "bad \! escape"}'
    result = _extract_objects(line)
    assert result == []


# ---------------------------------------------------------------------------
# main() integration tests
# ---------------------------------------------------------------------------


def test_main_pass_clean_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """main() exits 0 with PASS for a matching ledger."""
    import check_total_spent_vs_escrow_creates as mod

    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    history_dir = ledger_dir / "history"
    history_dir.mkdir()

    balances = {
        "version": 1,
        "agents": {
            "agent0@system": {"balance": 900, "total_spent": 9999},  # excluded
            "alice@x": {"balance": 70, "total_spent": 30},
        },
    }
    (ledger_dir / "balances.json").write_text(json.dumps(balances), encoding="utf-8")
    history_line = json.dumps(_new_event("alice@x", 30, issue=1))
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
    """main() exits 1 with FAIL when recorded total_spent is wrong."""
    import check_total_spent_vs_escrow_creates as mod

    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    history_dir = ledger_dir / "history"
    history_dir.mkdir()

    balances = {
        "version": 1,
        "agents": {
            "alice@x": {"balance": 0, "total_spent": 999},
        },
    }
    (ledger_dir / "balances.json").write_text(json.dumps(balances), encoding="utf-8")
    history_line = json.dumps(_new_event("alice@x", 10, issue=1))
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
    import check_total_spent_vs_escrow_creates as mod

    monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)

    exit_code = main()
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert exit_code == 1
    assert result["status"] == "FAIL"
    assert "not found" in result["summary"]


def test_main_old_format_events_not_counted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """Old-format events (author only, no from) do not inflate computed total.

    Agent has total_spent=0 and only old-format history → PASS because
    old events are skipped (no from field).
    """
    import check_total_spent_vs_escrow_creates as mod

    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    history_dir = ledger_dir / "history"
    history_dir.mkdir()

    balances = {
        "version": 1,
        "agents": {
            "alice@x": {"balance": 100, "total_spent": 0},
        },
    }
    (ledger_dir / "balances.json").write_text(json.dumps(balances), encoding="utf-8")
    # Old-format event — has author but no from → should be skipped
    history_line = json.dumps(_old_event("alice@x", 50, issue=1))
    (history_dir / "2026-01-01.jsonl").write_text(history_line + "\n", encoding="utf-8")

    monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)

    exit_code = main()
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert exit_code == 0
    assert result["status"] == "PASS"


def test_main_concatenated_objects_both_counted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """Two concatenated objects on one line are both counted."""
    import check_total_spent_vs_escrow_creates as mod

    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    history_dir = ledger_dir / "history"
    history_dir.mkdir()

    obj1 = _new_event("alice@x", 10, issue=1)
    obj2 = _new_event("alice@x", 15, issue=2)
    line = json.dumps(obj1) + json.dumps(obj2)

    balances = {
        "version": 1,
        "agents": {
            "alice@x": {"balance": 975, "total_spent": 25},
        },
    }
    (ledger_dir / "balances.json").write_text(json.dumps(balances), encoding="utf-8")
    (history_dir / "2026-01-01.jsonl").write_text(line + "\n", encoding="utf-8")

    monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)

    exit_code = main()
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert exit_code == 0
    assert result["status"] == "PASS"


def test_main_output_has_required_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """JSON output always contains status, divergences, and summary fields."""
    import check_total_spent_vs_escrow_creates as mod

    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    (ledger_dir / "history").mkdir()
    (ledger_dir / "balances.json").write_text(
        json.dumps({"version": 1, "agents": {}}), encoding="utf-8"
    )
    monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)

    main()
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert "status" in result
    assert "divergences" in result
    assert "summary" in result


def test_main_empty_history_zero_spent_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """Empty history directory + total_spent=0 → PASS."""
    import check_total_spent_vs_escrow_creates as mod

    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    (ledger_dir / "history").mkdir()  # empty directory

    balances = {
        "version": 1,
        "agents": {
            "alice@x": {"balance": 100, "total_spent": 0},
        },
    }
    (ledger_dir / "balances.json").write_text(json.dumps(balances), encoding="utf-8")
    monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)

    exit_code = main()
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert exit_code == 0
    assert result["status"] == "PASS"
