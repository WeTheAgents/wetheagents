#!/usr/bin/env python3
"""Adversarial tests for scripts/check_total_spent_consistency.py.

Bypass vectors discovered:
  GAP-1: agent0@system excluded by design — any divergence for agent0 is
         silently ignored regardless of magnitude, since _SKIP_AGENTS contains
         "agent0@system" and check_consistency never emits a divergence for it.
  GAP-2: Case-sensitive author lookup — UPPERCASE events (e.g. "CLAUDE-1@CLAUDE")
         accumulate in compute_total_spent under a key that is never matched
         against the lowercase balances.json entry "claude-1@claude"; recorded
         total_spent=0 passes even though real spending exists in history.
  GAP-3: Ghost agent spending never verified — agents present only in history
         (not in balances.json) are silently skipped; their spending is invisible
         to check_consistency, which only iterates over stored_agents.
  GAP-4: Fractional event amount truncated to int — int(99.9) is 99; an agent
         with recorded total_spent=99 passes even when the actual event amount
         was 99.9, masking a sub-WEA discrepancy introduced by float amounts.
  GAP-5: Malformed JSON line silently dropped — _extract_objects breaks on the
         first JSONDecodeError and returns []; an agent whose only escrow_create
         event lives on a malformed line is credited with 0 spent, matching a
         recorded total_spent=0 and producing a false PASS.
  GAP-6: Float total_spent in balances truncated — int(info.get("total_spent"))
         applies int() to the stored value too; int(99.9) == int(99) == 99,
         so a balances entry with total_spent=99.9 passes against events
         summing to 99, hiding the 0.9 WEA discrepancy between record and events.

Non-bypass adversarial cases (correctly handled or edge-bounded):
  ADV-7:  Missing author field → event silently skipped; no attribution.
  ADV-8:  Empty author string → event silently skipped via `if not author`.
  ADV-9:  Amount as numeric string "100" → int("100")=100; correctly parsed.
  ADV-10: Duplicate events without idem_key deduplication → double-counted;
          divergence is correctly detected when recorded value does not match.
  ADV-11: Non-escrow_create event types strictly excluded — payment, accept,
          escrow_return, trajectory_mint, escrow all produce zero credit.
  ADV-12: Non-dict agent value in balances.json → skipped without crash.
  ADV-13: Events split across two history files → all accumulated correctly.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from check_total_spent_consistency import (  # noqa: E402
    _extract_objects,
    check_consistency,
    compute_total_spent,
    main,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _agent(total_spent: int | float = 0, balance: int = 500) -> dict[str, Any]:
    return {"balance": balance, "total_spent": total_spent}


def _escrow_create(author: str, amount: Any, issue: int = 1) -> dict[str, Any]:
    return {"type": "escrow_create", "author": author, "amount": amount, "issue": issue}


# ===========================================================================
# GAP TESTS — confirmed bypass vectors where checker returns PASS despite a
# real inconsistency between recorded total_spent and history events.
# ===========================================================================


def test_gap1_agent0_system_excluded_despite_divergence():
    """GAP-1: agent0@system is excluded by design — huge divergence is invisible.

    Mechanism:
        check_consistency() iterates over stored_agents and skips any agent
        whose identifier appears in _SKIP_AGENTS (which contains "agent0@system").
        No divergence entry is ever emitted for agent0, regardless of how far
        the recorded total_spent deviates from the history-computed value.

    Exploit path:
        agent0@system has total_spent = 9_999 in balances.json.
        History only has escrow_create events by agent0@system summing to 1 WEA.
        The gap is 9_998 WEA — but check_consistency returns PASS because the
        agent is unconditionally skipped before the comparison is reached.
    """
    # GAP: agent0 is in _SKIP_AGENTS; no comparison is ever made.
    stored = {"agent0@system": _agent(total_spent=9_999)}
    computed = {"agent0@system": 1}

    status, divergences, summary = check_consistency(stored, computed)

    # Bypass confirmed: PASS with zero divergences despite 9_998 WEA mismatch.
    assert status == "PASS", f"Expected bypass PASS, got {status}"
    assert divergences == [], f"Expected no divergences reported, got {divergences}"


def test_gap2_case_sensitive_author_mismatch_lowercase_agent():
    """GAP-2: Uppercase author in events is never matched to lowercase balances entry.

    Mechanism:
        compute_total_spent() uses the raw author string as a dict key — no
        normalisation, no case-folding.  check_consistency() then looks up
        each agent_id (from balances.json) in that dict via computed.get(agent_id, 0).
        When history events carry "CLAUDE-1@CLAUDE" but balances has
        "claude-1@claude", the lookup returns 0 for the lowercase key.
        The uppercase variant becomes a ghost in the computed dict, never checked
        because it is absent from balances.json (silently skipped per GAP-3 logic).

    Exploit path:
        balances.json: claude-1@claude, total_spent = 0
        history:       escrow_create, author = "CLAUDE-1@CLAUDE", amount = 100
        compute_total_spent → {"CLAUDE-1@CLAUDE": 100}
        check_consistency  → computed.get("claude-1@claude", 0) == 0 == recorded(0)
        Result: PASS — but 100 WEA of real spending is unattributed.
    """
    # GAP: UPPERCASE author accumulates under a separate key; the lowercase
    # agent in balances sees 0 computed, matching its recorded 0.
    events = [_escrow_create("CLAUDE-1@CLAUDE", 100)]
    stored = {"claude-1@claude": _agent(total_spent=0)}

    computed = compute_total_spent(events)

    # Confirm the uppercase key is present and the lowercase key is absent.
    assert "CLAUDE-1@CLAUDE" in computed, "uppercase key should accumulate"
    assert "claude-1@claude" not in computed, "lowercase key should be absent"

    status, divergences, summary = check_consistency(stored, computed)

    # Bypass confirmed: lowercase agent passes with recorded=0, computed=0.
    assert status == "PASS", f"Expected bypass PASS, got {status}"
    assert divergences == [], f"Expected no divergences reported, got {divergences}"


def test_gap3_ghost_agent_spending_not_verified():
    """GAP-3: Agents present only in history are silently skipped.

    Mechanism:
        check_consistency() iterates exclusively over stored_agents (the agents
        dict from balances.json).  If an agent appears in computed (derived from
        history events) but is absent from stored_agents, there is no code path
        that ever checks or flags it.  The agent's spending is invisible.

    Exploit path:
        balances.json:  no entry for "ghost@system"
        history:        escrow_create, author = "ghost@system", amount = 500
        compute_total_spent → {"ghost@system": 500}
        check_consistency → iterates stored_agents (empty) → no divergences
        Result: PASS — but 500 WEA of real spending has no recorded total_spent.
    """
    # GAP: ghost@system spent 500 WEA (clear history evidence), but since it
    # is not in stored_agents, the check never looks for it.
    events = [
        _escrow_create("ghost@system", 200, issue=1),
        _escrow_create("ghost@system", 300, issue=2),
    ]
    stored: dict[str, Any] = {}  # no agents in balances.json

    computed = compute_total_spent(events)
    assert computed.get("ghost@system") == 500, "sanity: ghost spending computed"

    status, divergences, summary = check_consistency(stored, computed)

    # Bypass confirmed: no agents to check, PASS returned, 500 WEA invisible.
    assert status == "PASS", f"Expected bypass PASS, got {status}"
    assert divergences == [], f"Expected no divergences reported, got {divergences}"


def test_gap4_fractional_event_amount_truncated_to_int():
    """GAP-4: Float event amounts are silently truncated by int().

    Mechanism:
        compute_total_spent() applies int() to every event's amount field:
            amount = int(e.get("amount", 0))
        Python's int() truncates fractional parts without rounding.  A float
        amount such as 99.9 becomes 99, and 0.9 WEA of spending evaporates.
        If the agent's recorded total_spent is 99 (matching the truncated value),
        the comparison passes even though the actual event amount was 99.9.

    Exploit path:
        history:  escrow_create, author="alice@x", amount=99.9 (JSON float)
        computed: int(99.9) == 99  → {"alice@x": 99}
        balances: alice@x, total_spent=99
        check_consistency: 99 == 99 → PASS
        Reality: event amount was 99.9; recorded 99 understates real spending.
    """
    # GAP: float amount truncated; the truncated computed value matches the
    # recorded total_spent, so the discrepancy is invisible.
    events = [_escrow_create("alice@x", 99.9)]  # JSON float
    stored = {"alice@x": _agent(total_spent=99)}

    computed = compute_total_spent(events)
    assert computed.get("alice@x") == 99, "sanity: truncation produces 99"

    status, divergences, summary = check_consistency(stored, computed)

    # Bypass confirmed: 0.9 WEA discrepancy is hidden by int() truncation.
    assert status == "PASS", f"Expected bypass PASS, got {status}"
    assert divergences == [], f"Expected no divergences reported, got {divergences}"


def test_gap5_malformed_json_line_silently_dropped():
    """GAP-5: A malformed JSON line is silently dropped — spending not counted.

    Mechanism:
        _extract_objects() uses raw_decode() in a while loop.  On JSONDecodeError
        it executes `break`, exiting the loop and returning whatever was parsed
        so far.  If the *first* (or only) JSON object on the line is malformed,
        raw_decode raises immediately and the function returns [].  The event
        is lost; no amount is credited to the author.

    Exploit path:
        history line: '{"type": "escrow_create", "author": "alice@x", amount: 100}'
            (unquoted key 'amount' makes the entire object invalid JSON)
        _extract_objects returns []
        compute_total_spent([]) returns {}
        balances: alice@x, total_spent=0
        check_consistency: computed.get("alice@x", 0)==0 == recorded(0) → PASS
        Reality: alice@x did create an escrow of 100 WEA, but the event is lost.
    """
    # Unquoted key `amount` makes the object invalid JSON; raw_decode breaks.
    malformed_line = '{"type": "escrow_create", "author": "alice@x", amount: 100}'

    events_from_malformed = _extract_objects(malformed_line)
    assert events_from_malformed == [], (
        "Sanity: malformed line must produce no events"
    )

    # No events → compute_total_spent returns no credit for alice@x.
    computed = compute_total_spent(events_from_malformed)
    stored = {"alice@x": _agent(total_spent=0)}

    status, divergences, summary = check_consistency(stored, computed)

    # GAP: bypass confirmed — 100 WEA of spending was lost to malformed JSON;
    # alice's total_spent=0 matches computed=0, so PASS is returned.
    assert status == "PASS", f"Expected bypass PASS, got {status}"  # GAP: silent data loss
    assert divergences == [], f"Expected no divergences, got {divergences}"


def test_gap6_float_total_spent_in_balances_truncated():
    """GAP-6: Float total_spent in balances.json is also truncated by int().

    Mechanism:
        check_consistency() applies int() to the stored total_spent value:
            recorded = int(info.get("total_spent", 0))
        int(99.9) == 99.  If history events sum to exactly 99, then both sides
        of the comparison become 99 and PASS is returned, even though the stored
        value was 99.9 — meaning the balances ledger records 0.9 WEA more than
        the history can account for.

    Exploit path:
        balances: alice@x, total_spent=99.9 (float stored in JSON)
        history:  escrow_create, author="alice@x", amount=99
        recorded = int(99.9) = 99
        computed = int(99) = 99
        99 == 99 → PASS
        Reality: recorded value 99.9 does not match event sum 99; 0.9 WEA gap.
    """
    # GAP: both sides are truncated to 99; the 0.9 WEA discrepancy vanishes.
    events = [_escrow_create("alice@x", 99)]
    stored = {"alice@x": _agent(total_spent=99.9)}  # float in balances

    computed = compute_total_spent(events)
    assert computed.get("alice@x") == 99, "sanity: event amount is 99"

    status, divergences, summary = check_consistency(stored, computed)

    # Bypass confirmed: int() applied to both sides hides the 0.9 gap.
    assert status == "PASS", f"Expected bypass PASS, got {status}"  # GAP: float truncation
    assert divergences == [], f"Expected no divergences, got {divergences}"


# ===========================================================================
# NON-BYPASS ADVERSARIAL TESTS — edge cases that are correctly detected or
# correctly bounded (no false PASS introduced).
# ===========================================================================


def test_adv7_missing_author_field_skipped_no_attribution():
    """ADV-7: escrow_create without author field is skipped — correct behavior.

    Events without an author field cannot be attributed to any agent.
    The script correctly skips them via `if not author: continue`.
    This does NOT introduce a false PASS: if an agent has total_spent > 0
    but all their events lack author, the checker will correctly FAIL.
    """
    events = [
        {"type": "escrow_create", "amount": 100, "issue": 1},  # no author
        {"type": "escrow_create", "amount": 50, "issue": 2},   # no author
    ]
    computed = compute_total_spent(events)
    assert computed == {}, "Events without author must not be attributed"

    # Agent with total_spent=0 and no attributed events → correct PASS.
    stored = {"alice@x": _agent(total_spent=0)}
    status, divergences, _ = check_consistency(stored, computed)
    assert status == "PASS"

    # Agent with total_spent=150 and no attributed events → correct FAIL.
    stored_nonzero = {"alice@x": _agent(total_spent=150)}
    status2, divergences2, _ = check_consistency(stored_nonzero, computed)
    assert status2 == "FAIL"
    assert any(d["agent"] == "alice@x" for d in divergences2)


def test_adv8_empty_author_string_events_not_counted():
    """ADV-8: Empty author string is skipped via `if not author: continue`.

    An event with author="" is indistinguishable from a missing author field:
    `e.get("author", "")` returns "", and `if not author` is True → skip.
    No spending is credited, which is correct — an empty identifier is invalid.
    """
    events = [
        {"type": "escrow_create", "author": "", "amount": 200, "issue": 1},
    ]
    computed = compute_total_spent(events)
    assert computed == {}, "Empty author must produce no credit"

    stored = {"alice@x": _agent(total_spent=0)}
    status, divergences, _ = check_consistency(stored, computed)
    assert status == "PASS"


def test_adv9_numeric_string_amount_correctly_parsed():
    """ADV-9: Amount stored as a numeric string is correctly parsed by int().

    int("100") == 100 — Python's int() accepts string representations of
    integers.  This means "amount": "100" in a history event is treated the
    same as "amount": 100.  No bypass here: the computed value matches the
    event's numeric intent.
    """
    events = [_escrow_create("alice@x", "100")]  # string, not int
    computed = compute_total_spent(events)
    assert computed.get("alice@x") == 100, "String '100' must be parsed as int 100"

    stored = {"alice@x": _agent(total_spent=100)}
    status, divergences, _ = check_consistency(stored, computed)
    assert status == "PASS"


def test_adv10_duplicate_events_double_counted_detected():
    """ADV-10: Duplicate escrow_create events are double-counted — correctly flagged.

    compute_total_spent does not deduplicate by idem_key.  Two identical
    escrow_create events for the same author sum to 2x the individual amount.
    If the recorded total_spent equals the single-event amount, the checker
    correctly reports a FAIL — no false PASS is produced.
    """
    # Two identical events — computed = 50 + 50 = 100.
    events = [
        _escrow_create("alice@x", 50, issue=1),
        _escrow_create("alice@x", 50, issue=1),  # exact duplicate
    ]
    computed = compute_total_spent(events)
    assert computed.get("alice@x") == 100, "Duplicate events must double-count"

    # Recorded is 50 (single event); duplicate not reflected → correctly FAIL.
    stored = {"alice@x": _agent(total_spent=50)}
    status, divergences, _ = check_consistency(stored, computed)
    assert status == "FAIL"
    assert any(d["agent"] == "alice@x" for d in divergences)


def test_adv11_non_escrow_create_event_types_excluded():
    """ADV-11: All event types other than escrow_create produce zero credit.

    Only "type": "escrow_create" events count toward total_spent.  Events of
    types payment, accept, trajectory_mint, escrow_return, and the legacy
    "escrow" type are all ignored.  An agent with total_spent=0 and only
    non-escrow_create events in history correctly returns PASS.
    """
    events = [
        {"type": "payment",          "author": "alice@x", "amount": 100},
        {"type": "accept",            "author": "alice@x", "amount": 50},
        {"type": "trajectory_mint",  "author": "alice@x", "amount": 200},
        {"type": "escrow_return",    "author": "alice@x", "amount": 30},
        {"type": "escrow",           "agent":  "alice@x", "amount": 999},
        {"type": "balance_update",   "author": "alice@x", "amount": 40},
    ]
    computed = compute_total_spent(events)
    assert computed == {}, "Non-escrow_create types must produce no credit"

    stored = {"alice@x": _agent(total_spent=0)}
    status, divergences, _ = check_consistency(stored, computed)
    assert status == "PASS"
    assert divergences == []


def test_adv12_non_dict_agent_info_in_balances_skipped():
    """ADV-12: Agents with a non-dict value in balances.json are skipped safely.

    check_consistency() guards: `if not isinstance(info, dict): continue`.
    An agent whose value is an integer (e.g. from a malformed balances.json)
    is silently skipped — no crash, no spurious divergence.
    """
    # Simulate a balances.json where one agent has a bare integer value.
    stored: dict[str, Any] = {
        "malformed-agent@x": 500,          # non-dict: should be skipped
        "good-agent@x": _agent(total_spent=10),
    }
    computed = {"good-agent@x": 10}

    status, divergences, _ = check_consistency(stored, computed)
    assert status == "PASS", "Non-dict agent value must not cause FAIL or crash"
    agents_flagged = {d["agent"] for d in divergences}
    assert "malformed-agent@x" not in agents_flagged


def test_adv13_events_split_across_multiple_history_files():
    """ADV-13: Events from multiple .jsonl files are all accumulated correctly.

    _iter_events() globs all *.jsonl files and processes them in sorted order.
    Spending spread across two files is summed correctly; no file is dropped.
    This test uses main() with a tmp_path fixture to exercise the real file I/O
    path and confirm there is no per-file reset of the accumulator.
    """
    import check_total_spent_consistency as mod

    # Build a temporary ledger with two history files.
    def _run(tmp_path: Path) -> dict[str, Any]:
        ledger = tmp_path / "ledger"
        ledger.mkdir()
        hist = ledger / "history"
        hist.mkdir()

        balances: dict[str, Any] = {
            "version": 1,
            "agents": {"alice@x": {"balance": 700, "total_spent": 300}},
        }
        (ledger / "balances.json").write_text(
            json.dumps(balances), encoding="utf-8"
        )

        # File 1: 100 WEA
        line1 = json.dumps(_escrow_create("alice@x", 100, issue=1))
        (hist / "2026-01-01.jsonl").write_text(line1 + "\n", encoding="utf-8")

        # File 2: 200 WEA (different filename → different file)
        line2 = json.dumps(_escrow_create("alice@x", 200, issue=2))
        (hist / "2026-01-02.jsonl").write_text(line2 + "\n", encoding="utf-8")

        return tmp_path

    import tempfile

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _run(root)

        original_root = mod._repo_root
        mod._repo_root = lambda: root
        try:
            import io
            import contextlib

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                exit_code = main()
        finally:
            mod._repo_root = original_root

        result = json.loads(buf.getvalue())

    # 100 + 200 = 300 == recorded 300 → PASS
    assert exit_code == 0
    assert result["status"] == "PASS", (
        f"Expected PASS (cross-file sum=300==recorded), got {result}"
    )
    assert result["divergences"] == []
