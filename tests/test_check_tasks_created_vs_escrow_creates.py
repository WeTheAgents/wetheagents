"""Tests for scripts/check_tasks_created_vs_escrow_creates.py.

All tests are fully in-memory; no real ledger files are accessed.
Covers all three historical event formats and alias resolution.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from check_tasks_created_vs_escrow_creates import (  # noqa: E402
    _is_escrow_creation,
    _event_agent,
    check_consistency,
    compute_tasks_created,
    main,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _agent(tasks_created: int = 0) -> dict[str, Any]:
    return {"balance": 100, "tasks_created": tasks_created}


def _new_event(from_agent: str, issue: int = 1) -> dict[str, Any]:
    """New-format escrow_create event (op + from)."""
    return {"op": "escrow_create", "from": from_agent, "amount": 10, "issue": issue}


def _mid_event(author: str, issue: int = 1) -> dict[str, Any]:
    """Intermediate-format escrow_create event (type + author)."""
    return {"type": "escrow_create", "author": author, "amount": 10, "issue": issue}


def _tide_event(agent: str, issue: int = 1) -> dict[str, Any]:
    """Old Tide-format escrow event (type=escrow + agent field)."""
    return {"type": "escrow", "agent": agent, "amount": 10, "issue": issue}


def _tide_author_event(author: str, issue: int = 1) -> dict[str, Any]:
    """Old Tide-format escrow event with author field instead of agent."""
    return {"type": "escrow", "author": author, "amount": 10, "issue": issue}


# ---------------------------------------------------------------------------
# _is_escrow_creation tests
# ---------------------------------------------------------------------------


def test_is_escrow_creation_new_format() -> None:
    """op==escrow_create is recognised as an escrow creation event."""
    assert _is_escrow_creation({"op": "escrow_create", "from": "a@x"})


def test_is_escrow_creation_intermediate_format() -> None:
    """type==escrow_create is recognised as an escrow creation event."""
    assert _is_escrow_creation({"type": "escrow_create", "author": "a@x"})


def test_is_escrow_creation_tide_format() -> None:
    """type==escrow (Tide format) is recognised as an escrow creation event."""
    assert _is_escrow_creation({"type": "escrow", "agent": "a@x"})


def test_is_escrow_creation_payment_false() -> None:
    """payment event is NOT an escrow creation event."""
    assert not _is_escrow_creation({"type": "payment", "agent": "a@x"})


def test_is_escrow_creation_escrow_return_false() -> None:
    """escrow_return event is NOT an escrow creation event."""
    assert not _is_escrow_creation({"type": "escrow_return", "author": "a@x"})


def test_is_escrow_creation_empty_dict_false() -> None:
    """Empty dict is NOT an escrow creation event."""
    assert not _is_escrow_creation({})


# ---------------------------------------------------------------------------
# _event_agent tests
# ---------------------------------------------------------------------------


def test_event_agent_from_field() -> None:
    """from field is preferred over author and agent."""
    e = {"from": "primary@x", "author": "fallback@x", "agent": "last@x"}
    assert _event_agent(e) == "primary@x"


def test_event_agent_author_fallback() -> None:
    """author field used when from is absent."""
    e = {"author": "author@x", "agent": "agent@x"}
    assert _event_agent(e) == "author@x"


def test_event_agent_agent_fallback() -> None:
    """agent field used when from and author are absent."""
    e = {"agent": "agent@x"}
    assert _event_agent(e) == "agent@x"


def test_event_agent_empty_when_no_field() -> None:
    """Empty string returned when no recognised field is present."""
    assert _event_agent({}) == ""


# ---------------------------------------------------------------------------
# compute_tasks_created tests
# ---------------------------------------------------------------------------


def test_compute_empty_events_returns_empty() -> None:
    """No events → empty result."""
    assert compute_tasks_created([], {}) == {}


def test_compute_new_format_counted() -> None:
    """New-format (op+from) event is counted."""
    events = [_new_event("alice@x", issue=1)]
    result = compute_tasks_created(events, {})
    assert result.get("alice@x") == 1


def test_compute_tide_format_counted() -> None:
    """Tide-format (type=escrow) event is counted."""
    events = [_tide_event("alice@x", issue=1)]
    result = compute_tasks_created(events, {})
    assert result.get("alice@x") == 1


def test_compute_intermediate_format_counted() -> None:
    """Intermediate-format (type=escrow_create) event is counted."""
    events = [_mid_event("alice@x", issue=1)]
    result = compute_tasks_created(events, {})
    assert result.get("alice@x") == 1


def test_compute_multiple_events_accumulate() -> None:
    """Multiple events for the same agent accumulate as a count."""
    events = [
        _new_event("alice@x", issue=1),
        _tide_event("alice@x", issue=2),
        _mid_event("alice@x", issue=3),
    ]
    result = compute_tasks_created(events, {})
    assert result.get("alice@x") == 3


def test_compute_multiple_agents_independent() -> None:
    """Events for different agents are counted independently."""
    events = [
        _new_event("alice@x", issue=1),
        _new_event("bob@x", issue=2),
        _new_event("alice@x", issue=3),
    ]
    result = compute_tasks_created(events, {})
    assert result.get("alice@x") == 2
    assert result.get("bob@x") == 1


def test_compute_non_escrow_creation_ignored() -> None:
    """Non-escrow-creation events do not affect the count."""
    events = [
        {"type": "payment", "from": "alice@x", "amount": 50},
        {"op": "accept", "from": "alice@x", "amount": 10},
        {"type": "escrow_return", "author": "alice@x", "amount": 10},
        _new_event("alice@x", issue=1),  # only this one counts
    ]
    result = compute_tasks_created(events, {})
    assert result.get("alice@x") == 1


def test_compute_missing_agent_field_skipped() -> None:
    """escrow_create event with no agent field is silently skipped."""
    events = [{"op": "escrow_create", "amount": 10, "issue": 1}]
    result = compute_tasks_created(events, {})
    assert result == {}


def test_compute_alias_resolution_applied() -> None:
    """Events under old agent name are resolved to current name via aliases."""
    aliases = {"OldName@x": "alice@x"}
    events = [
        _tide_author_event("OldName@x", issue=1),
        _tide_author_event("OldName@x", issue=2),
        _new_event("alice@x", issue=3),
    ]
    result = compute_tasks_created(events, aliases)
    # All 3 events resolve to alice@x
    assert result.get("alice@x") == 3
    assert "OldName@x" not in result


def test_compute_alias_unknown_agent_passes_through() -> None:
    """Agents not in aliases dict are used as-is."""
    aliases = {"OtherOld@x": "other@x"}
    events = [_new_event("alice@x", issue=1)]
    result = compute_tasks_created(events, aliases)
    assert result.get("alice@x") == 1


# ---------------------------------------------------------------------------
# check_consistency tests
# ---------------------------------------------------------------------------


def test_check_consistency_pass_match() -> None:
    """Stored matches computed → PASS with no divergences."""
    stored = {"alice@x": _agent(tasks_created=2)}
    computed = {"alice@x": 2}
    status, divergences, summary = check_consistency(stored, computed)
    assert status == "PASS"
    assert divergences == []


def test_check_consistency_fail_mismatch_by_one() -> None:
    """Off-by-one divergence → FAIL."""
    stored = {"alice@x": _agent(tasks_created=3)}
    computed = {"alice@x": 2}
    status, divergences, summary = check_consistency(stored, computed)
    assert status == "FAIL"
    assert len(divergences) == 1
    div = divergences[0]
    assert div["agent"] == "alice@x"
    assert div["stored"] == 3
    assert div["computed"] == 2
    assert div["delta"] == -1


def test_check_consistency_fail_under_stored() -> None:
    """Computed > stored → FAIL with positive delta."""
    stored = {"alice@x": _agent(tasks_created=1)}
    computed = {"alice@x": 4}
    status, divergences, summary = check_consistency(stored, computed)
    assert status == "FAIL"
    assert divergences[0]["delta"] == 3


def test_check_consistency_zero_stored_no_history_pass() -> None:
    """Agent with tasks_created=0 and no events → PASS."""
    stored = {"alice@x": _agent(tasks_created=0)}
    computed: dict[str, int] = {}
    status, divergences, _ = check_consistency(stored, computed)
    assert status == "PASS"
    assert divergences == []


def test_check_consistency_zero_stored_nonzero_history_fail() -> None:
    """tasks_created=0 but history shows 2 escrow creations → FAIL."""
    stored = {"alice@x": _agent(tasks_created=0)}
    computed = {"alice@x": 2}
    status, divergences, _ = check_consistency(stored, computed)
    assert status == "FAIL"
    assert any(d["agent"] == "alice@x" for d in divergences)


def test_check_consistency_agent0_excluded() -> None:
    """agent0@system divergence does NOT cause FAIL."""
    stored = {"agent0@system": _agent(tasks_created=999)}
    computed = {"agent0@system": 1}
    status, divergences, _ = check_consistency(stored, computed)
    assert status == "PASS"
    assert all(d["agent"] != "agent0@system" for d in divergences)


def test_check_consistency_only_diverging_agents_listed() -> None:
    """Only agents with divergences appear in the divergences list."""
    stored = {
        "alice@x": _agent(tasks_created=2),   # match
        "bob@x": _agent(tasks_created=5),     # mismatch
        "charlie@x": _agent(tasks_created=0), # match (zero)
    }
    computed = {"alice@x": 2, "bob@x": 3}
    status, divergences, _ = check_consistency(stored, computed)
    assert status == "FAIL"
    names = {d["agent"] for d in divergences}
    assert "bob@x" in names
    assert "alice@x" not in names
    assert "charlie@x" not in names


def test_check_consistency_ghost_in_history_skipped() -> None:
    """Agent in computed but absent from balances.json is silently ignored."""
    stored: dict[str, Any] = {}
    computed = {"ghost@x": 5}
    status, divergences, _ = check_consistency(stored, computed)
    assert status == "PASS"
    assert divergences == []


def test_check_consistency_summary_reflects_agent_count() -> None:
    """Summary contains the number of checked agents (excluding agent0)."""
    stored = {
        "agent0@system": _agent(tasks_created=999),
        "alice@x": _agent(tasks_created=1),
        "bob@x": _agent(tasks_created=0),
    }
    computed = {"alice@x": 1}
    status, _, summary = check_consistency(stored, computed)
    assert status == "PASS"
    assert "2" in summary


# ---------------------------------------------------------------------------
# main() integration tests
# ---------------------------------------------------------------------------


def test_main_pass_clean_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """main() exits 0 with PASS for a matching ledger."""
    import check_tasks_created_vs_escrow_creates as mod

    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    history_dir = ledger_dir / "history"
    history_dir.mkdir()

    balances = {
        "version": 1,
        "agents": {
            "agent0@system": {"balance": 900, "tasks_created": 999},  # excluded
            "alice@x": {"balance": 90, "tasks_created": 2},
        },
    }
    (ledger_dir / "balances.json").write_text(json.dumps(balances), encoding="utf-8")
    lines = [
        json.dumps(_new_event("alice@x", issue=1)),
        json.dumps(_new_event("alice@x", issue=2)),
    ]
    (history_dir / "2026-01-01.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

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
    """main() exits 1 with FAIL when stored tasks_created is wrong."""
    import check_tasks_created_vs_escrow_creates as mod

    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    history_dir = ledger_dir / "history"
    history_dir.mkdir()

    balances = {
        "version": 1,
        "agents": {
            "alice@x": {"balance": 0, "tasks_created": 5},
        },
    }
    (ledger_dir / "balances.json").write_text(json.dumps(balances), encoding="utf-8")
    (history_dir / "2026-01-01.jsonl").write_text(
        json.dumps(_new_event("alice@x", issue=1)) + "\n", encoding="utf-8"
    )

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
    import check_tasks_created_vs_escrow_creates as mod

    monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)

    exit_code = main()
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert exit_code == 1
    assert result["status"] == "FAIL"
    assert "not found" in result["summary"]


def test_main_no_history_dir_zero_tasks_created_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """main() exits 0 when history dir is absent and tasks_created=0 for all."""
    import check_tasks_created_vs_escrow_creates as mod

    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    balances = {
        "version": 1,
        "agents": {"alice@x": {"balance": 100, "tasks_created": 0}},
    }
    (ledger_dir / "balances.json").write_text(json.dumps(balances), encoding="utf-8")

    monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)

    exit_code = main()
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert exit_code == 0
    assert result["status"] == "PASS"


def test_main_alias_resolution_passes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """main() applies alias resolution so renamed agent events count correctly."""
    import check_tasks_created_vs_escrow_creates as mod

    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    history_dir = ledger_dir / "history"
    history_dir.mkdir()

    balances = {
        "version": 1,
        "agents": {
            "alice@x": {"balance": 90, "tasks_created": 2},
        },
    }
    (ledger_dir / "balances.json").write_text(json.dumps(balances), encoding="utf-8")
    # Both events are under old name; alias maps to current name
    aliases = {"OldAlice@x": "alice@x"}
    (ledger_dir / "agent_aliases.json").write_text(json.dumps(aliases), encoding="utf-8")
    lines = [
        json.dumps(_tide_author_event("OldAlice@x", issue=1)),
        json.dumps(_tide_author_event("OldAlice@x", issue=2)),
    ]
    (history_dir / "2026-01-01.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)

    exit_code = main()
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert exit_code == 0
    assert result["status"] == "PASS"


def test_main_all_formats_counted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """All three event formats contribute to the count."""
    import check_tasks_created_vs_escrow_creates as mod

    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    history_dir = ledger_dir / "history"
    history_dir.mkdir()

    balances = {
        "version": 1,
        "agents": {
            "alice@x": {"balance": 70, "tasks_created": 3},
        },
    }
    (ledger_dir / "balances.json").write_text(json.dumps(balances), encoding="utf-8")
    lines = [
        json.dumps(_new_event("alice@x", issue=1)),         # op=escrow_create
        json.dumps(_mid_event("alice@x", issue=2)),         # type=escrow_create
        json.dumps(_tide_event("alice@x", issue=3)),        # type=escrow
    ]
    (history_dir / "2026-01-01.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)

    exit_code = main()
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert exit_code == 0
    assert result["status"] == "PASS"


def test_main_other_agent_events_excluded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """Events from other agents do not count toward the checked agent's total."""
    import check_tasks_created_vs_escrow_creates as mod

    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    history_dir = ledger_dir / "history"
    history_dir.mkdir()

    balances = {
        "version": 1,
        "agents": {
            "alice@x": {"balance": 90, "tasks_created": 1},
            "bob@x": {"balance": 90, "tasks_created": 2},
        },
    }
    (ledger_dir / "balances.json").write_text(json.dumps(balances), encoding="utf-8")
    lines = [
        json.dumps(_new_event("alice@x", issue=1)),
        json.dumps(_new_event("bob@x", issue=2)),
        json.dumps(_new_event("bob@x", issue=3)),
    ]
    (history_dir / "2026-01-01.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

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
    import check_tasks_created_vs_escrow_creates as mod

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
