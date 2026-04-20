"""Adversarial tests for scripts/check_total_spent_vs_escrow_creates.py.

Four adversarial scenarios not covered by the baseline test suite:

  (a) Agent with escrow_create events in history but tasks_created: 0 in balances.
      The from-field replay catches total_spent divergence independently of tasks_created.
      Documents the gap: tasks_created manipulation is invisible to this script.

  (b) Case mismatch in agent IDs (e.g. Claude-1@claude vs claude-1@claude).
      No case normalisation occurs; mismatched casing causes a silent attribution miss
      that manifests as a divergence for the stored agent.

  (c) Malformed JSON lines interspersed with valid events in history files.
      _extract_objects silently skips unparseable lines; valid events still accumulate.
      A fully malformed history with a nonzero recorded total_spent still fails.

  (d) Agent with negative total_spent in balances.
      Negative values always diverge from the non-negative history sum — should FAIL.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from check_total_spent_vs_escrow_creates import (  # noqa: E402
    check_consistency,
    compute_spent_from_field,
    main,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _agent(total_spent: int = 0, tasks_created: int = 0) -> dict[str, Any]:
    """Minimal balances.json agent entry with optional tasks_created field."""
    return {"balance": 100, "total_spent": total_spent, "tasks_created": tasks_created}


def _new_event(from_agent: str, amount: int, issue: int = 1) -> dict[str, Any]:
    """New-format escrow_create event (op + from)."""
    return {"op": "escrow_create", "from": from_agent, "amount": amount, "issue": issue}


def _ledger(tmp_path: Path, agents: dict[str, Any]) -> None:
    """Write a minimal balances.json and empty history directory under tmp_path."""
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir(exist_ok=True)
    (ledger_dir / "history").mkdir(exist_ok=True)
    (ledger_dir / "balances.json").write_text(
        json.dumps({"version": 1, "agents": agents}), encoding="utf-8"
    )


def _write_history(history_dir: Path, filename: str, lines: list[str]) -> None:
    """Write raw lines (as-is) to a JSONL history file."""
    history_dir.mkdir(parents=True, exist_ok=True)
    (history_dir / filename).write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# (a) escrow_create events in history but tasks_created: 0 in balances
# ---------------------------------------------------------------------------


def test_escrow_creates_in_history_both_counters_zero_fails() -> None:
    """Agent zeros both total_spent and tasks_created but history shows spending.

    Attack: an agent manipulates balances.json to hide task creation by setting
    tasks_created: 0 AND total_spent: 0.  The from-field replay detects the
    total_spent divergence independently of the tasks_created counter.

    Expected: FAIL — computed (40) > 0 but recorded total_spent = 0.
    """
    stored = {"alice@x": _agent(total_spent=0, tasks_created=0)}
    events = [
        _new_event("alice@x", 25, issue=11),
        _new_event("alice@x", 15, issue=12),
    ]
    computed = compute_spent_from_field(events)
    status, divergences, _ = check_consistency(stored, computed)
    assert status == "FAIL"
    div = next(d for d in divergences if d["agent"] == "alice@x")
    assert div["recorded"] == 0
    assert div["computed"] == 40
    assert div["delta"] == 40  # computed − recorded


def test_escrow_creates_in_history_tasks_created_zero_total_spent_matches_passes() -> None:
    """Agent has tasks_created: 0 but total_spent correctly reflects history.

    The check covers only total_spent; the tasks_created field is not validated.
    This test documents the gap: a manipulated tasks_created counter is invisible
    to this script — only the total_spent divergence is detectable.

    Expected: PASS — total_spent matches history even though tasks_created is wrong.
    """
    stored = {"alice@x": _agent(total_spent=40, tasks_created=0)}
    events = [
        _new_event("alice@x", 25, issue=11),
        _new_event("alice@x", 15, issue=12),
    ]
    computed = compute_spent_from_field(events)
    status, divergences, _ = check_consistency(stored, computed)
    assert status == "PASS"
    assert divergences == []


def test_single_escrow_create_tasks_created_zero_total_spent_zero_fails() -> None:
    """Single escrow_create event, tasks_created=0 AND total_spent=0.

    Even a single event creates a divergence when total_spent is zeroed.

    Expected: FAIL — delta = computed − recorded = 10 − 0 = 10.
    """
    stored = {"bob@y": _agent(total_spent=0, tasks_created=0)}
    events = [_new_event("bob@y", 10, issue=7)]
    computed = compute_spent_from_field(events)
    status, divergences, _ = check_consistency(stored, computed)
    assert status == "FAIL"
    div = next(d for d in divergences if d["agent"] == "bob@y")
    assert div["computed"] == 10
    assert div["recorded"] == 0


# ---------------------------------------------------------------------------
# (b) Case mismatch in agent IDs
# ---------------------------------------------------------------------------


def test_case_mismatch_stored_titlecase_history_lowercase_fails() -> None:
    """Stored agent 'Claude-1@claude' but history event uses 'claude-1@claude'.

    No case normalisation is performed.  computed['claude-1@claude'] = 10 but
    computed.get('Claude-1@claude') returns 0 (key miss).  The stored agent has
    recorded = 10, computed (for stored key) = 0 → divergence.

    Expected: FAIL — case-shifted from field hides attribution for the stored agent.
    """
    stored = {"Claude-1@claude": _agent(total_spent=10)}
    events = [{"op": "escrow_create", "from": "claude-1@claude", "amount": 10, "issue": 1}]
    computed = compute_spent_from_field(events)
    status, divergences, _ = check_consistency(stored, computed)
    assert status == "FAIL"
    div = next((d for d in divergences if d["agent"] == "Claude-1@claude"), None)
    assert div is not None
    assert div["recorded"] == 10
    assert div["computed"] == 0


def test_case_match_consistent_casing_passes() -> None:
    """Stored and history both use the same casing — exact match → PASS.

    Baseline: consistent casing with no divergence.

    Expected: PASS.
    """
    stored = {"claude-1@claude": _agent(total_spent=10)}
    events = [{"op": "escrow_create", "from": "claude-1@claude", "amount": 10, "issue": 1}]
    computed = compute_spent_from_field(events)
    status, divergences, _ = check_consistency(stored, computed)
    assert status == "PASS"
    assert divergences == []


def test_case_mismatch_stored_lowercase_history_uppercase_fails() -> None:
    """Stored agent 'claude-1@claude' but history event uses 'CLAUDE-1@CLAUDE'.

    Reverse direction: uppercase in history, lowercase in stored.
    computed['CLAUDE-1@CLAUDE'] = 20 but computed.get('claude-1@claude') = 0.
    recorded = 20, computed (for stored key) = 0 → divergence.

    Expected: FAIL — same gap, opposite case direction.
    """
    stored = {"claude-1@claude": _agent(total_spent=20)}
    events = [{"op": "escrow_create", "from": "CLAUDE-1@CLAUDE", "amount": 20, "issue": 2}]
    computed = compute_spent_from_field(events)
    status, divergences, _ = check_consistency(stored, computed)
    assert status == "FAIL"
    div = next((d for d in divergences if d["agent"] == "claude-1@claude"), None)
    assert div is not None
    assert div["computed"] == 0
    assert div["recorded"] == 20


def test_mixed_case_two_agents_only_mismatched_agent_fails() -> None:
    """alice has matching casing (PASS), Bob has a case mismatch (FAIL).

    Verifies that the case-mismatch failure is agent-specific, not global.
    Correctly-matched agents are not affected by nearby mismatches.

    Expected: FAIL status; divergence only for 'Bob@x', not 'alice@x'.
    """
    stored = {
        "alice@x": _agent(total_spent=5),
        "Bob@x": _agent(total_spent=15),
    }
    events = [
        {"op": "escrow_create", "from": "alice@x", "amount": 5, "issue": 1},
        {"op": "escrow_create", "from": "bob@x", "amount": 15, "issue": 2},  # lowercase mismatch
    ]
    computed = compute_spent_from_field(events)
    status, divergences, _ = check_consistency(stored, computed)
    assert status == "FAIL"
    agents_with_div = {d["agent"] for d in divergences}
    assert "Bob@x" in agents_with_div
    assert "alice@x" not in agents_with_div


# ---------------------------------------------------------------------------
# (c) Malformed JSON lines interspersed with valid events
# ---------------------------------------------------------------------------


def test_malformed_lines_valid_events_still_counted_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """main() handles history file with malformed lines without crashing.

    Valid escrow_create events interspersed with garbage lines must still be
    accumulated.  The check must PASS when valid events sum to recorded total_spent.

    Expected: exit code 0, status=PASS — valid events found, no crash.
    """
    import check_total_spent_vs_escrow_creates as mod

    _ledger(tmp_path, {"alice@x": {"balance": 75, "total_spent": 25}})
    valid_event = json.dumps({"op": "escrow_create", "from": "alice@x", "amount": 25, "issue": 1})
    _write_history(tmp_path / "ledger" / "history", "2026-01-01.jsonl", [
        "not json at all",
        "{broken",
        valid_event,
        "another bad line",
    ])

    monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)
    exit_code = main()
    result = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert result["status"] == "PASS"


def test_fully_malformed_history_zero_total_spent_passes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """Fully malformed history + agent with total_spent: 0 → PASS.

    No valid events are parsed → computed = {}.
    computed.get('alice@x', 0) = 0 == recorded (0) → no divergence.

    Expected: exit code 0, status=PASS — consistent zero on both sides.
    """
    import check_total_spent_vs_escrow_creates as mod

    _ledger(tmp_path, {"alice@x": {"balance": 100, "total_spent": 0}})
    _write_history(tmp_path / "ledger" / "history", "2026-01-01.jsonl", [
        "garbage",
        "{bad json",
        "also bad",
    ])

    monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)
    exit_code = main()
    result = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert result["status"] == "PASS"


def test_fully_malformed_history_nonzero_total_spent_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """Fully malformed history + agent with total_spent: 30 → FAIL.

    No valid events parsed → computed = {} → computed.get('alice@x', 0) = 0.
    recorded = 30 ≠ 0 → divergence.

    Expected: exit code 1, status=FAIL — a non-zero total_spent needs history proof.
    """
    import check_total_spent_vs_escrow_creates as mod

    _ledger(tmp_path, {"alice@x": {"balance": 70, "total_spent": 30}})
    _write_history(tmp_path / "ledger" / "history", "2026-01-01.jsonl", [
        "garbage",
        "{broken",
        "not valid json",
    ])

    monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)
    exit_code = main()
    result = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert result["status"] == "FAIL"
    assert any(d["agent"] == "alice@x" for d in result["divergences"])


def test_malformed_lines_across_multiple_files_valid_event_counted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """Malformed lines in early files; valid escrow_create in the last file.

    The checker iterates files in sorted order.  A valid event in the last file
    must be found even when earlier files contain only garbage.

    Expected: exit code 0, status=PASS — event in last file counted correctly.
    """
    import check_total_spent_vs_escrow_creates as mod

    _ledger(tmp_path, {"alice@x": {"balance": 80, "total_spent": 20}})
    history_dir = tmp_path / "ledger" / "history"
    _write_history(history_dir, "2026-01-01.jsonl", ["garbage", "{bad"])
    _write_history(history_dir, "2026-01-02.jsonl", ["more garbage"])
    valid_event = json.dumps({"op": "escrow_create", "from": "alice@x", "amount": 20, "issue": 5})
    _write_history(history_dir, "2026-01-03.jsonl", ["still garbage", valid_event])

    monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)
    exit_code = main()
    result = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert result["status"] == "PASS"


# ---------------------------------------------------------------------------
# (d) Agent with negative total_spent — should FAIL regardless of history sum
# ---------------------------------------------------------------------------


def test_negative_total_spent_no_history_fails() -> None:
    """Agent has total_spent: -5 but no history events.

    computed = 0 (no events), recorded = -5.
    delta = computed − recorded = 0 − (−5) = 5 → divergence.
    Negative total_spent invariably diverges from the non-negative history sum.

    Expected: FAIL — delta is 5.
    """
    stored = {"alice@x": _agent(total_spent=-5)}
    computed: dict[str, int] = {}
    status, divergences, _ = check_consistency(stored, computed)
    assert status == "FAIL"
    div = next(d for d in divergences if d["agent"] == "alice@x")
    assert div["recorded"] == -5
    assert div["computed"] == 0
    assert div["delta"] == 5  # 0 − (−5)


def test_negative_total_spent_with_matching_history_still_fails() -> None:
    """Agent has total_spent: -10 and history sum = 10.

    Negative recorded can never equal non-negative computed.
    delta = 10 − (−10) = 20.

    Expected: FAIL — even with real spending in history, negative recorded diverges.
    """
    stored = {"alice@x": _agent(total_spent=-10)}
    events = [_new_event("alice@x", 10, issue=1)]
    computed = compute_spent_from_field(events)
    status, divergences, _ = check_consistency(stored, computed)
    assert status == "FAIL"
    div = next(d for d in divergences if d["agent"] == "alice@x")
    assert div["recorded"] == -10
    assert div["computed"] == 10
    assert div["delta"] == 20


def test_negative_total_spent_only_that_agent_fails() -> None:
    """Two agents: alice has correct total_spent, bob has negative total_spent.

    Verifies that the negative total_spent failure is agent-specific.

    Expected: FAIL status; divergence only for 'bob@x'.
    """
    stored = {
        "alice@x": _agent(total_spent=15),
        "bob@x": _agent(total_spent=-3),
    }
    events = [_new_event("alice@x", 15, issue=1)]
    computed = compute_spent_from_field(events)
    status, divergences, _ = check_consistency(stored, computed)
    assert status == "FAIL"
    agents_with_div = {d["agent"] for d in divergences}
    assert "bob@x" in agents_with_div
    assert "alice@x" not in agents_with_div


def test_negative_total_spent_main_integration_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """main() exits 1 when balances.json contains an agent with negative total_spent.

    Full pipeline: file I/O, JSON output, exit code.
    No history events are present — computed = 0.
    recorded = -7 ≠ 0 → divergence detected end-to-end.

    Expected: exit code 1, status=FAIL, divergence entry for 'alice@x'.
    """
    import check_total_spent_vs_escrow_creates as mod

    _ledger(tmp_path, {"alice@x": {"balance": 100, "total_spent": -7}})
    # Empty history — no events written.
    monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)

    exit_code = main()
    result = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert result["status"] == "FAIL"
    assert any(d["agent"] == "alice@x" for d in result["divergences"])
