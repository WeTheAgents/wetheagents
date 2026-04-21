"""Adversarial tests for scripts/check_tasks_created_vs_escrow_creates.py.

Four adversarial scenarios:

  (a) Agent with escrow_create events in history but tasks_created:0 in
      balances.json — the counter has been zeroed while history records prove
      activity.  Should FAIL with computed > stored.

  (b) Two escrow_create events with case-mismatched agent IDs
      (e.g. Claude-1@claude stored vs claude-1@claude in history).
      No case normalisation is applied; only alias resolution happens.
      Case mismatch causes a silent attribution miss → FAIL.

  (c) History file with malformed JSON lines interspersed with valid events.
      _iter_events silently skips unparseable lines; valid events still
      accumulate.  A fully malformed history file paired with a nonzero
      tasks_created still FAILS.

  (d) Agent with negative tasks_created — should FAIL regardless of history
      count.  Also covers the null tasks_created bug (BUG FIX): when
      tasks_created is JSON null the original code raised TypeError; the fix
      treats null as 0 and reports a divergence when history has events.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from check_tasks_created_vs_escrow_creates import (  # noqa: E402
    check_consistency,
    compute_tasks_created,
    main,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _agent(tasks_created: int | None = 0) -> dict[str, Any]:
    """Minimal balances.json agent entry."""
    return {"balance": 100, "tasks_created": tasks_created}


def _new_event(from_agent: str, issue: int = 1) -> dict[str, Any]:
    """New-format escrow_create event (op + from)."""
    return {"op": "escrow_create", "from": from_agent, "amount": 10, "issue": issue}


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


def test_zeroed_counter_two_history_events_fails() -> None:
    """Agent has tasks_created:0 but history records two escrow creations.

    Attack: counter reset to hide task creation activity.
    computed=2, stored=0 → delta=2 → FAIL.
    """
    stored = {"alice@x": _agent(tasks_created=0)}
    events = [
        _new_event("alice@x", issue=11),
        _new_event("alice@x", issue=12),
    ]
    computed = compute_tasks_created(events, {})
    status, divergences, _ = check_consistency(stored, computed)
    assert status == "FAIL"
    div = next(d for d in divergences if d["agent"] == "alice@x")
    assert div["stored"] == 0
    assert div["computed"] == 2
    assert div["delta"] == 2  # computed − stored


def test_zeroed_counter_single_history_event_fails() -> None:
    """Even a single escrow_create event exposes a zeroed counter.

    Boundary case: one event is enough to trigger a divergence.
    computed=1, stored=0 → delta=1 → FAIL.
    """
    stored = {"bob@y": _agent(tasks_created=0)}
    events = [_new_event("bob@y", issue=7)]
    computed = compute_tasks_created(events, {})
    status, divergences, _ = check_consistency(stored, computed)
    assert status == "FAIL"
    div = next(d for d in divergences if d["agent"] == "bob@y")
    assert div["computed"] == 1
    assert div["stored"] == 0


def test_zeroed_counter_no_history_is_genuine_zero_passes() -> None:
    """tasks_created:0 with no history events is not an attack — PASS.

    Distinguishes a legitimate zero from a tampered-zero-with-history.
    """
    stored = {"alice@x": _agent(tasks_created=0)}
    computed: dict[str, int] = {}
    status, divergences, _ = check_consistency(stored, computed)
    assert status == "PASS"
    assert divergences == []


def test_zeroed_counter_multiple_agents_only_attacker_fails() -> None:
    """Only the agent with the zeroed counter diverges; honest agents pass.

    alice has tasks_created=2 matching two history events (honest).
    bob has tasks_created=0 but three history events (tampered).
    Expected: FAIL for bob only.
    """
    stored = {
        "alice@x": _agent(tasks_created=2),
        "bob@y": _agent(tasks_created=0),
    }
    events = [
        _new_event("alice@x", issue=1),
        _new_event("alice@x", issue=2),
        _new_event("bob@y", issue=3),
        _new_event("bob@y", issue=4),
        _new_event("bob@y", issue=5),
    ]
    computed = compute_tasks_created(events, {})
    status, divergences, _ = check_consistency(stored, computed)
    assert status == "FAIL"
    failing = {d["agent"] for d in divergences}
    assert "bob@y" in failing
    assert "alice@x" not in failing


# ---------------------------------------------------------------------------
# (b) Case-mismatched agent IDs
# ---------------------------------------------------------------------------


def test_case_mismatch_titlecase_stored_lowercase_history_fails() -> None:
    """Stored 'Claude-1@claude', history event uses 'claude-1@claude'.

    No case normalisation is performed.  computed['claude-1@claude']=1 while
    computed.get('Claude-1@claude')=0.  Stored counter is 1, computed is 0
    → divergence.

    Expected: FAIL — case shift causes attribution miss for the stored agent.
    """
    stored = {"Claude-1@claude": _agent(tasks_created=1)}
    events = [{"op": "escrow_create", "from": "claude-1@claude", "amount": 10, "issue": 1}]
    computed = compute_tasks_created(events, {})
    status, divergences, _ = check_consistency(stored, computed)
    assert status == "FAIL"
    div = next((d for d in divergences if d["agent"] == "Claude-1@claude"), None)
    assert div is not None
    assert div["stored"] == 1
    assert div["computed"] == 0


def test_case_match_consistent_casing_passes() -> None:
    """Stored and history both use the same casing — exact match → PASS.

    Confirms the positive path: case-consistent attribution works correctly.
    """
    stored = {"claude-1@claude": _agent(tasks_created=1)}
    events = [{"op": "escrow_create", "from": "claude-1@claude", "amount": 10, "issue": 1}]
    computed = compute_tasks_created(events, {})
    status, divergences, _ = check_consistency(stored, computed)
    assert status == "PASS"
    assert divergences == []


def test_case_mismatch_only_affected_agent_diverges() -> None:
    """alice has consistent casing (pass), Bob has a case mismatch (fail).

    Case-mismatch divergence is agent-specific; well-named agents are unaffected.
    """
    stored = {
        "alice@x": _agent(tasks_created=1),
        "Bob@x": _agent(tasks_created=1),
    }
    events = [
        {"op": "escrow_create", "from": "alice@x", "amount": 10, "issue": 1},
        {"op": "escrow_create", "from": "bob@x", "amount": 10, "issue": 2},  # lowercase mismatch
    ]
    computed = compute_tasks_created(events, {})
    status, divergences, _ = check_consistency(stored, computed)
    assert status == "FAIL"
    failing = {d["agent"] for d in divergences}
    assert "Bob@x" in failing
    assert "alice@x" not in failing


def test_alias_resolution_maps_old_name_to_current_passes() -> None:
    """Alias resolution (not case normalisation) corrects renamed-agent history.

    When agent_aliases maps 'OldAlice@x' → 'alice@x', events filed under the
    old name count toward the current name.  This is the supported rename path;
    case mismatch has no analogous mechanism.

    Expected: PASS — two alias-resolved events match tasks_created=2.
    """
    aliases = {"OldAlice@x": "alice@x"}
    stored = {"alice@x": _agent(tasks_created=2)}
    events = [
        {"op": "escrow_create", "from": "OldAlice@x", "amount": 10, "issue": 1},
        {"op": "escrow_create", "from": "OldAlice@x", "amount": 10, "issue": 2},
    ]
    computed = compute_tasks_created(events, aliases)
    status, divergences, _ = check_consistency(stored, computed)
    assert status == "PASS"
    assert divergences == []


# ---------------------------------------------------------------------------
# (c) Malformed JSON lines interspersed with valid events
# ---------------------------------------------------------------------------


def test_malformed_lines_valid_events_still_counted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """main() handles garbage lines without crashing; valid events are counted.

    Valid escrow_create event between garbage lines must be accumulated.
    tasks_created=1 matches one valid event → PASS.
    """
    import check_tasks_created_vs_escrow_creates as mod

    _ledger(tmp_path, {"alice@x": {"balance": 90, "tasks_created": 1}})
    valid_event = json.dumps(_new_event("alice@x", issue=1))
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


def test_fully_malformed_history_zero_tasks_created_passes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """Fully malformed history + tasks_created:0 → PASS.

    No valid events parsed → computed={} → computed.get('alice@x', 0)=0 == stored(0).
    No divergence when both sides are zero.
    """
    import check_tasks_created_vs_escrow_creates as mod

    _ledger(tmp_path, {"alice@x": {"balance": 100, "tasks_created": 0}})
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


def test_fully_malformed_history_nonzero_tasks_created_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """Fully malformed history + tasks_created:3 → FAIL.

    No valid events parsed → computed=0. stored=3 ≠ 0 → divergence.
    A non-zero tasks_created needs corroborating history events.
    """
    import check_tasks_created_vs_escrow_creates as mod

    _ledger(tmp_path, {"alice@x": {"balance": 70, "tasks_created": 3}})
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
    """Valid event in last file is found even when earlier files are garbage.

    _iter_events iterates files in sorted order.  The valid event in the last
    file must be accumulated; malformed earlier files must not crash iteration.
    """
    import check_tasks_created_vs_escrow_creates as mod

    _ledger(tmp_path, {"alice@x": {"balance": 90, "tasks_created": 1}})
    history_dir = tmp_path / "ledger" / "history"
    _write_history(history_dir, "2026-01-01.jsonl", ["garbage", "{bad"])
    _write_history(history_dir, "2026-01-02.jsonl", ["more garbage"])
    valid_event = json.dumps(_new_event("alice@x", issue=5))
    _write_history(history_dir, "2026-01-03.jsonl", ["still garbage", valid_event])

    monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)
    exit_code = main()
    result = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert result["status"] == "PASS"


# ---------------------------------------------------------------------------
# (d) Agent with negative tasks_created — FAIL regardless of history count
# ---------------------------------------------------------------------------


def test_negative_tasks_created_no_history_fails() -> None:
    """tasks_created:-1 with no history events always diverges.

    computed=0 (no events), stored=-1.
    delta = computed − stored = 0 − (−1) = 1 → FAIL.
    """
    stored = {"alice@x": _agent(tasks_created=-1)}
    computed: dict[str, int] = {}
    status, divergences, _ = check_consistency(stored, computed)
    assert status == "FAIL"
    div = next(d for d in divergences if d["agent"] == "alice@x")
    assert div["stored"] == -1
    assert div["computed"] == 0
    assert div["delta"] == 1  # 0 − (−1)


def test_negative_tasks_created_with_matching_count_still_fails() -> None:
    """tasks_created:-3 with 3 history events still FAILS.

    Negative stored can never equal non-negative computed.
    delta = 3 − (−3) = 6.
    """
    stored = {"alice@x": _agent(tasks_created=-3)}
    events = [
        _new_event("alice@x", issue=1),
        _new_event("alice@x", issue=2),
        _new_event("alice@x", issue=3),
    ]
    computed = compute_tasks_created(events, {})
    status, divergences, _ = check_consistency(stored, computed)
    assert status == "FAIL"
    div = next(d for d in divergences if d["agent"] == "alice@x")
    assert div["stored"] == -3
    assert div["computed"] == 3
    assert div["delta"] == 6


def test_negative_tasks_created_only_that_agent_fails() -> None:
    """Two agents: alice is honest, bob has negative tasks_created.

    Failure is agent-specific; alice's clean record is unaffected.
    """
    stored = {
        "alice@x": _agent(tasks_created=2),
        "bob@y": _agent(tasks_created=-2),
    }
    events = [
        _new_event("alice@x", issue=1),
        _new_event("alice@x", issue=2),
    ]
    computed = compute_tasks_created(events, {})
    status, divergences, _ = check_consistency(stored, computed)
    assert status == "FAIL"
    failing = {d["agent"] for d in divergences}
    assert "bob@y" in failing
    assert "alice@x" not in failing


def test_null_tasks_created_with_history_events_fails_not_crashes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """BUG FIX: tasks_created:null (JSON null) must not crash the checker.

    Previously int(None) raised TypeError, allowing an attacker to break
    the consistency check by writing null into balances.json.
    After the fix: null is treated as 0, compared to history count (1),
    a divergence is emitted, and the script exits 1.

    Expected: exit code 1, status=FAIL, divergence for 'alice@x' — no crash.
    """
    import check_tasks_created_vs_escrow_creates as mod

    _ledger(tmp_path, {"alice@x": {"balance": 90, "tasks_created": None}})
    valid_event = json.dumps(_new_event("alice@x", issue=1))
    _write_history(tmp_path / "ledger" / "history", "2026-01-01.jsonl", [valid_event])

    monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)
    exit_code = main()
    result = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert result["status"] == "FAIL"
    assert any(d["agent"] == "alice@x" for d in result["divergences"])


def test_negative_tasks_created_main_integration_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """main() exits 1 when balances.json has a plain negative tasks_created.

    Full pipeline: file I/O, JSON output, exit code.
    computed=0 (no history events), stored=-2 → delta=2 → FAIL.
    """
    import check_tasks_created_vs_escrow_creates as mod

    _ledger(tmp_path, {"alice@x": {"balance": 100, "tasks_created": -2}})
    monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)
    exit_code = main()
    result = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert result["status"] == "FAIL"
    div = next(d for d in result["divergences"] if d["agent"] == "alice@x")
    assert div["stored"] == -2
    assert div["computed"] == 0
    assert div["delta"] == 2


def test_null_tasks_created_no_history_passes_not_crashes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """BUG FIX: tasks_created:null with no history events → PASS, no crash.

    null treated as 0; computed=0 == stored(0) → no divergence.
    """
    import check_tasks_created_vs_escrow_creates as mod

    _ledger(tmp_path, {"alice@x": {"balance": 100, "tasks_created": None}})
    monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)
    exit_code = main()
    result = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert result["status"] == "PASS"
