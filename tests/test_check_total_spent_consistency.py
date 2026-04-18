"""Tests for scripts/check_total_spent_consistency.py.

All tests are fully in-memory; no real ledger files are accessed.
Minimum 12 test cases covering all spec-required scenarios.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

# Make the scripts directory importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from check_total_spent_consistency import (  # noqa: E402
    _extract_objects,
    check_consistency,
    compute_total_spent,
    main,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _agent(total_spent: int = 0) -> dict[str, Any]:
    """Build a minimal stored agent dict with only total_spent."""
    return {"balance": 100, "total_spent": total_spent}


def _escrow_create(author: str, amount: int, issue: int = 1) -> dict[str, Any]:
    return {"type": "escrow_create", "author": author, "amount": amount, "issue": issue}


# ---------------------------------------------------------------------------
# _extract_objects tests
# ---------------------------------------------------------------------------


def test_extract_objects_single_valid():
    """A single valid JSON object on a line is returned as a one-element list."""
    line = '{"type": "escrow_create", "author": "alice@x", "amount": 10}'
    result = _extract_objects(line)
    assert len(result) == 1
    assert result[0]["type"] == "escrow_create"


def test_extract_objects_two_concatenated():
    """Two JSON objects concatenated on one line are both extracted."""
    a = '{"type": "escrow_create", "author": "alice@x", "amount": 10, "issue": 1}'
    b = '{"type": "escrow_create", "author": "bob@x", "amount": 5, "issue": 2}'
    result = _extract_objects(a + b)
    assert len(result) == 2
    assert result[0]["author"] == "alice@x"
    assert result[1]["author"] == "bob@x"


def test_extract_objects_invalid_json_returns_empty():
    """A line with an invalid JSON escape is silently skipped."""
    line = r'{"note": "bad \! escape"}'
    result = _extract_objects(line)
    assert result == []


# ---------------------------------------------------------------------------
# compute_total_spent tests
# ---------------------------------------------------------------------------


def test_compute_empty_events_returns_empty_dict():
    """No events — empty dict, consistent with zero total_spent for all agents."""
    assert compute_total_spent([]) == {}


def test_single_escrow_create_credited():
    """A single escrow_create event credits the author."""
    events = [_escrow_create("alice@x", 25, issue=1)]
    result = compute_total_spent(events)
    assert result.get("alice@x") == 25


def test_multiple_escrow_creates_accumulate():
    """Multiple escrow_create events for the same author accumulate correctly."""
    events = [
        _escrow_create("alice@x", 10, issue=1),
        _escrow_create("alice@x", 15, issue=2),
        _escrow_create("alice@x", 30, issue=3),
    ]
    result = compute_total_spent(events)
    assert result.get("alice@x") == 55


def test_author_field_missing_event_skipped():
    """escrow_create without author field is silently skipped."""
    events = [{"type": "escrow_create", "amount": 100, "issue": 1}]
    result = compute_total_spent(events)
    assert result == {}


def test_non_escrow_create_events_ignored():
    """Only escrow_create events count; all other types are ignored."""
    events = [
        {"type": "payment", "author": "alice@x", "amount": 50},
        {"type": "accept", "author": "alice@x", "amount": 30},
        {"type": "trajectory_mint", "author": "alice@x", "amount": 20},
        {"type": "escrow_return", "author": "alice@x", "amount": 10},
        {"type": "escrow", "agent": "alice@x", "amount": 999},
        _escrow_create("alice@x", 7, issue=1),
    ]
    result = compute_total_spent(events)
    assert result.get("alice@x") == 7


# ---------------------------------------------------------------------------
# check_consistency tests
# ---------------------------------------------------------------------------


def test_all_agents_match_pass():
    """All agents' recorded total_spent matches computed → PASS."""
    stored = {
        "alice@x": _agent(total_spent=50),
        "bob@x": _agent(total_spent=0),
    }
    computed = {"alice@x": 50}
    status, divergences, summary = check_consistency(stored, computed)
    assert status == "PASS"
    assert divergences == []


def test_over_counted_fail():
    """Recorded total_spent > computed (over-counted) → FAIL with divergence."""
    stored = {"alice@x": _agent(total_spent=100)}
    computed = {"alice@x": 80}
    status, divergences, summary = check_consistency(stored, computed)
    assert status == "FAIL"
    assert len(divergences) == 1
    div = divergences[0]
    assert div["agent"] == "alice@x"
    assert div["recorded"] == 100
    assert div["computed"] == 80
    assert div["delta"] == -20  # computed - recorded


def test_under_counted_fail():
    """Recorded total_spent < computed (under-counted) → FAIL with divergence."""
    stored = {"bob@x": _agent(total_spent=10)}
    computed = {"bob@x": 30}
    status, divergences, summary = check_consistency(stored, computed)
    assert status == "FAIL"
    assert len(divergences) == 1
    div = divergences[0]
    assert div["agent"] == "bob@x"
    assert div["recorded"] == 10
    assert div["computed"] == 30
    assert div["delta"] == 20  # computed - recorded


def test_zero_escrows_zero_recorded_pass():
    """Agent with no escrow_create events and total_spent=0 → PASS."""
    stored = {"alice@x": _agent(total_spent=0)}
    computed: dict[str, int] = {}
    status, divergences, summary = check_consistency(stored, computed)
    assert status == "PASS"
    assert divergences == []


def test_zero_escrows_nonzero_recorded_fail():
    """Agent with no escrow_create events but total_spent>0 → FAIL."""
    stored = {"alice@x": _agent(total_spent=50)}
    computed: dict[str, int] = {}
    status, divergences, summary = check_consistency(stored, computed)
    assert status == "FAIL"
    assert any(d["agent"] == "alice@x" for d in divergences)


def test_mixed_pass_fail():
    """Multiple agents: only the diverging ones appear in divergences."""
    stored = {
        "alice@x": _agent(total_spent=100),  # match
        "bob@x": _agent(total_spent=200),    # mismatch
        "charlie@x": _agent(total_spent=0),  # match (zero)
    }
    computed = {"alice@x": 100, "bob@x": 150}
    status, divergences, summary = check_consistency(stored, computed)
    assert status == "FAIL"
    agents_with_div = {d["agent"] for d in divergences}
    assert "alice@x" not in agents_with_div
    assert "bob@x" in agents_with_div
    assert "charlie@x" not in agents_with_div


def test_agent0_excluded_from_check():
    """agent0@system is excluded — divergence does not cause FAIL."""
    stored = {"agent0@system": _agent(total_spent=9999)}
    computed = {"agent0@system": 100}
    status, divergences, summary = check_consistency(stored, computed)
    assert status == "PASS"
    assert all(d["agent"] != "agent0@system" for d in divergences)


def test_empty_history_zero_spent_pass():
    """Empty history with all agents having total_spent=0 → PASS."""
    stored = {
        "alice@x": _agent(total_spent=0),
        "bob@x": _agent(total_spent=0),
    }
    computed: dict[str, int] = {}
    status, divergences, summary = check_consistency(stored, computed)
    assert status == "PASS"
    assert divergences == []


def test_no_agents_in_balances_pass():
    """No agents in balances → trivial PASS."""
    status, divergences, summary = check_consistency({}, {})
    assert status == "PASS"
    assert divergences == []


def test_unknown_agent_in_history_skipped():
    """Agent appearing only in history (not in balances) is skipped — no FAIL."""
    computed = {"ghost@x": 100}
    stored: dict[str, Any] = {}
    status, divergences, summary = check_consistency(stored, computed)
    assert status == "PASS"
    assert divergences == []


def test_delta_field_present_and_correct():
    """Divergence entry contains delta = computed - recorded."""
    stored = {"alice@x": _agent(total_spent=40)}
    computed = {"alice@x": 55}
    _, divergences, _ = check_consistency(stored, computed)
    assert len(divergences) == 1
    assert divergences[0]["delta"] == 55 - 40


def test_summary_reflects_checked_count():
    """Summary reports the number of checked agents (excluding agent0)."""
    stored = {
        "agent0@system": _agent(total_spent=9999),
        "alice@x": _agent(total_spent=10),
        "bob@x": _agent(total_spent=20),
    }
    computed = {"alice@x": 10, "bob@x": 20}
    status, divergences, summary = check_consistency(stored, computed)
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
    """main() prints JSON with status PASS and exits 0 for a clean ledger."""
    import check_total_spent_consistency as mod

    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    history_dir = ledger_dir / "history"
    history_dir.mkdir()

    balances = {
        "version": 1,
        "agents": {
            "agent0@system": {"balance": 900, "total_spent": 999},  # excluded
            "alice@x": {"balance": 75, "total_spent": 25},
        },
    }
    (ledger_dir / "balances.json").write_text(json.dumps(balances), encoding="utf-8")
    history_line = json.dumps(_escrow_create("alice@x", 25, issue=1))
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
    """main() exits 1 and reports divergence when stored total_spent is wrong."""
    import check_total_spent_consistency as mod

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
    history_line = json.dumps(_escrow_create("alice@x", 10, issue=1))
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
    import check_total_spent_consistency as mod

    monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)

    exit_code = main()
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert exit_code == 1
    assert result["status"] == "FAIL"
    assert "not found" in result["summary"]


def test_main_concatenated_objects_on_one_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """main() correctly handles a history line with two concatenated JSON objects."""
    import check_total_spent_consistency as mod

    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    history_dir = ledger_dir / "history"
    history_dir.mkdir()

    obj1 = _escrow_create("alice@x", 10, issue=1)
    obj2 = _escrow_create("alice@x", 15, issue=2)
    concatenated_line = json.dumps(obj1) + json.dumps(obj2)

    balances = {
        "version": 1,
        "agents": {
            "alice@x": {"balance": 975, "total_spent": 25},
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
