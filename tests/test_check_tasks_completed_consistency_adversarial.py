"""Adversarial tests for scripts/check_tasks_completed_consistency.py

Each test targets a bypass vector — inputs that cause the checker to return
PASS when tasks_completed has a real divergence between stored
``balances.json`` metadata and what ``ledger/history/*.jsonl`` actually shows.

All tests are self-contained: in-memory event lists and stored-agent dicts
only.  No real ledger files are read.

Bypass vectors covered:
  1.  [GAP] History-only agent absent from stored → WARNING, not FAIL
  2.  [GAP] Non-dict stored agent info silently skipped → divergence missed
  3.  Unparseable issue values silently dropped → false PASS
  4.  issue=None silently dropped → false PASS when stored agrees
  5.  Wrong event type (trajectory_mint) not counted → both sides 0 → PASS
  6.  accept + payment for same issue — deduped to 1 → PASS (design)
  7.  Symmetric corruption: fake event + inflated stored → false PASS
  8.  agent0@system excluded → its tasks_completed never checked
  9.  Zero-amount payment skipped → boundary check, both sides 0 → PASS
  10. Float issue truncated by int() — deduplication across float/int → PASS
  11. Missing/empty/null agent fields skipped → completion invisible
  12. Event type matching is case-sensitive → false PASS when stored agrees
  13. Invalid JSON lines in history are silently dropped → false PASS
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.check_tasks_completed_consistency import (
    _iter_events,
    check_consistency,
    compute_tasks_completed,
)


# ---------------------------------------------------------------------------
# Test 1 — [GAP] History-only agent absent from stored → WARNING not FAIL
# ---------------------------------------------------------------------------


def test_history_only_agent_absent_from_stored_emits_warning_not_fail() -> None:
    """[CONFIRMED GAP] An agent with qualifying payment events in history but
    no entry in stored_agents produces a warning, not a divergence.

    check_consistency() iterates over stored_agents to detect divergences.
    Agents that appear only in history (absent from stored) are collected into
    a separate warnings list.  The final status is ``PASS`` when
    len(divergences) == 0, regardless of how many warnings exist.

    Real violation: Alice@claude completed two tasks (issues 10 and 20)
    according to history — computed tasks_completed["Alice@claude"] == 2.
    She has no entry in balances.json at all, so her stored count is
    effectively 0.  That is a real discrepancy, but the checker only warns.

    Attack scenario: an operator deletes an agent from balances.json to hide
    their task-completion record.  The missing agent slips through as a
    warning-only anomaly rather than a hard failure.
    """  # GAP: history-only agents produce warnings, not divergences
    events = [
        {"type": "payment", "agent": "Alice@claude", "amount": 30, "issue": 10},
        {"type": "payment", "agent": "Alice@claude", "amount": 25, "issue": 20},
    ]
    stored_agents: dict = {}  # Alice entirely absent

    computed = compute_tasks_completed(events)

    assert computed.get("Alice@claude", 0) == 2, (
        "Alice completed 2 distinct issues according to history."
    )

    status, divergences, warnings, _ = check_consistency(stored_agents, computed)

    # GAP: divergences list is empty → status is PASS
    assert divergences == [], (
        "No divergence is raised for Alice even though she has 2 qualifying "
        "history events but zero stored entry."
    )
    assert status == "PASS", (
        "Checker reports PASS despite Alice being absent from balances.json "
        "while history shows tasks_completed=2.  Missing agents only produce "
        "warnings, not failures."
    )
    assert len(warnings) == 1
    assert warnings[0]["agent"] == "Alice@claude"


# ---------------------------------------------------------------------------
# Test 2 — [GAP] Non-dict stored agent info silently skipped
# ---------------------------------------------------------------------------


def test_non_dict_stored_agent_info_silently_skipped_false_pass() -> None:
    """[CONFIRMED GAP] When a stored agent's value is not a dict the entry is
    silently skipped, even when a real divergence exists.

    check_consistency() contains:
        if not isinstance(info, dict):
            continue

    If balances.json contains an agent entry whose value is not a dict (e.g.,
    an integer, a list, or a bare string), the agent is simply omitted from
    divergence detection.  The checker neither flags the malformed entry nor
    compares it to the history count.

    Real violation: Bob@claude has 3 qualifying payment events in history
    (computed tasks_completed == 3).  His stored entry value is the integer 5
    — perhaps a legacy format or deliberate corruption.  The real discrepancy
    (stored ≈ 5 vs computed == 3) is never raised.

    Attack scenario: an attacker who controls ledger/balances.json replaces an
    agent's dict entry with a bare integer to suppress divergence detection for
    that agent while keeping arbitrary numbers invisible to the checker.
    """  # GAP: non-dict agent entries bypass the divergence loop entirely
    events = [
        {"type": "payment", "agent": "Bob@claude", "amount": 20, "issue": 1},
        {"type": "payment", "agent": "Bob@claude", "amount": 30, "issue": 2},
        {"type": "accept",  "agent": "Bob@claude", "amount": 10, "issue": 3},
    ]
    # Bob's entry is an integer, not a dict — triggers the isinstance guard
    stored_agents: dict = {"Bob@claude": 5}

    computed = compute_tasks_completed(events)

    assert computed.get("Bob@claude", 0) == 3, (
        "Bob completed 3 distinct issues according to history."
    )

    status, divergences, warnings, _ = check_consistency(stored_agents, computed)

    # GAP: Bob is silently skipped — stored 5 vs computed 3 is never flagged
    bob_divs = [d for d in divergences if d["agent"] == "Bob@claude"]
    assert bob_divs == [], (
        "No divergence for Bob even though stored value (5) and computed (3) differ."
    )
    assert status == "PASS", (
        "Checker reports PASS.  Bob's non-dict stored entry bypasses the "
        "divergence check entirely — the real mismatch (5 vs 3) is invisible."
    )


# ---------------------------------------------------------------------------
# Test 3 — Unparseable issue values silently dropped
# ---------------------------------------------------------------------------


def test_unparseable_issue_values_silently_dropped_false_pass() -> None:
    """Bypass vector: issue values that ``int()`` cannot parse are silently
    dropped, causing an under-count that matches a correspondingly low stored
    value.

    compute_tasks_completed() converts issue via ``int(issue)``.  Non-numeric
    strings, string-floats, and container types all raise ``ValueError`` or
    ``TypeError`` and are silently dropped.

    Real violation: Carol@claude completed four tasks.  One task has a normal
    integer issue (issue 7) and three have malformed issue encodings.  The
    real tasks_completed should be 4.  The script computes 1 (drops the
    malformed events).  An operator who processed the same events the same way
    stores tasks_completed=1 too — both sides agree → PASS.

    The genuine extra task completions are entirely invisible to the checker.
    """
    events = [
        {"type": "payment", "agent": "Carol@claude", "amount": 40, "issue": 7},
        # Non-numeric string: int("task-xyz") → ValueError → skipped
        {"type": "payment", "agent": "Carol@claude", "amount": 25, "issue": "task-xyz"},
        # String-float: int("42.5") → ValueError → skipped
        {"type": "payment", "agent": "Carol@claude", "amount": 25, "issue": "42.5"},
        # Non-scalar: int([8]) → TypeError → skipped
        {"type": "accept", "agent": "Carol@claude", "amount": 10, "issue": [8]},
    ]
    stored_agents = {
        "Carol@claude": {"tasks_completed": 1},  # operator also skipped malformed
    }

    computed = compute_tasks_completed(events)

    assert computed.get("Carol@claude", 0) == 1, (
        "Unsupported issue encodings are dropped; only issue 7 is counted."
    )

    status, divergences, _, _ = check_consistency(stored_agents, computed)

    assert status == "PASS", (
        "Checker reports PASS.  Carol actually completed 4 tasks but the "
        "unparseable issue values make three invisible to both sides."
    )
    assert divergences == []


# ---------------------------------------------------------------------------
# Test 4 — issue=None silently dropped → false PASS when stored agrees
# ---------------------------------------------------------------------------


def test_issue_none_silently_dropped_false_pass() -> None:
    """Bypass vector: payment event with issue=None is silently skipped by the
    explicit None-guard.

    compute_tasks_completed() contains:
        issue = e.get("issue")
        if issue is None:
            continue

    A positive-amount payment for a real task that happens to lack an issue
    field (or explicitly has issue=null) is completely invisible.  If the
    operator's stored tasks_completed ALSO omits this completion, both sides
    agree on an under-count → PASS.

    Real violation: Dave@claude completed a real task but the payment event
    was written without the issue field.  stored=1 (one other task), computed=1
    — both correctly count the labelled task and both miss the unlabelled one.
    The unlabelled task completion is undetectable by this checker.
    """
    events = [
        {"type": "payment", "agent": "Dave@claude", "amount": 30, "issue": 5},
        # issue=None: skipped by the explicit None check
        {"type": "payment", "agent": "Dave@claude", "amount": 20, "issue": None},
    ]
    stored_agents = {
        "Dave@claude": {"tasks_completed": 1},  # only issue 5 counted
    }

    computed = compute_tasks_completed(events)

    assert computed.get("Dave@claude", 0) == 1, (
        "issue=None event is skipped; only issue 5 contributes."
    )

    status, divergences, _, _ = check_consistency(stored_agents, computed)

    assert status == "PASS"
    assert divergences == [], (
        "Checker says PASS.  The None-issue completion is invisible — "
        "stored and computed both show 1, missing the unlabelled task."
    )


# ---------------------------------------------------------------------------
# Test 5 — Wrong event type (trajectory_mint) not counted → both sides 0
# ---------------------------------------------------------------------------


def test_trajectory_mint_not_counted_both_sides_zero_pass() -> None:
    """Confirm design: trajectory_mint events do NOT contribute to
    tasks_completed, even when they carry agent and issue fields.

    compute_tasks_completed() only processes events with type 'payment' or
    'accept'.  A trajectory_mint is a minting event, not a task completion.

    If stored tasks_completed=0 and history contains only a trajectory_mint
    for an agent, both sides show 0 → PASS.  This is intentional behavior but
    documents a visibility gap: an agent who ONLY earns from gauntlet mints
    will always show tasks_completed=0 without any checker intervention.
    """
    events = [
        {
            "type": "trajectory_mint",
            "agent": "Eve@claude",
            "amount": 34,
            "issue": 525,
        }
    ]
    stored_agents = {
        "Eve@claude": {"tasks_completed": 0},
    }

    computed = compute_tasks_completed(events)

    assert computed.get("Eve@claude", 0) == 0, (
        "trajectory_mint is not a task completion — not counted."
    )

    status, divergences, _, _ = check_consistency(stored_agents, computed)

    assert status == "PASS"
    assert divergences == []


# ---------------------------------------------------------------------------
# Test 6 — accept + payment for same issue deduped to 1
# ---------------------------------------------------------------------------


def test_accept_and_payment_same_issue_deduped_to_one() -> None:
    """Design verification: multiple qualifying events for the same issue are
    deduplicated — only the distinct issue count matters.

    An agent may receive both an 'accept' and a 'payment' event for the same
    issue (e.g., accept on claim + payment on delivery).  The set-based
    counting ensures the issue is counted only once.

    stored=1, computed=1 → PASS.  Confirms deduplication is working correctly.
    """
    events = [
        {"type": "accept",  "agent": "Frank@claude", "amount": 5,  "issue": 100},
        {"type": "payment", "agent": "Frank@claude", "amount": 50, "issue": 100},
    ]
    stored_agents = {
        "Frank@claude": {"tasks_completed": 1},
    }

    computed = compute_tasks_completed(events)

    assert computed.get("Frank@claude", 0) == 1, (
        "accept + payment for same issue counts as 1 distinct task."
    )

    status, divergences, _, _ = check_consistency(stored_agents, computed)

    assert status == "PASS"
    assert divergences == []


# ---------------------------------------------------------------------------
# Test 7 — Symmetric corruption: fake event + inflated stored → false PASS
# ---------------------------------------------------------------------------


def test_symmetric_corruption_fake_event_and_inflated_stored_false_pass() -> None:
    """Bypass vector: coordinated corruption of both history and stored metadata.

    The checker computes from history and compares to stored.  If an attacker
    inserts a fake payment event into history AND simultaneously inflates the
    stored tasks_completed by exactly one, both sides report the same (wrong)
    value → PASS.

    Real violation: Grace@claude legitimately completed issues 1 and 2.
    Stored tasks_completed should be 2.  An attacker added a fake payment for
    issue 3 to history and bumped stored to 3.  Both sides now show 3 — no
    divergence is raised.  The fake task is completely undetectable.

    This is the fundamental limit of an arithmetic-consistency check: it can
    only verify that the two records agree, not that either is independently
    correct.
    """
    events = [
        {"type": "payment", "agent": "Grace@claude", "amount": 30, "issue": 1},
        {"type": "payment", "agent": "Grace@claude", "amount": 25, "issue": 2},
        # Fake: not a real task completion — inserted to inflate the count
        {"type": "payment", "agent": "Grace@claude", "amount": 20, "issue": 3},
    ]
    stored_agents = {
        # Stored also reflects the inflated count
        "Grace@claude": {"tasks_completed": 3},
    }

    computed = compute_tasks_completed(events)

    assert computed.get("Grace@claude", 0) == 3

    status, divergences, _, _ = check_consistency(stored_agents, computed)

    assert status == "PASS", (
        "Checker says PASS.  Both history and stored show 3 even though only 2 "
        "tasks were legitimately completed.  Symmetric corruption is undetectable."
    )
    assert divergences == []


# ---------------------------------------------------------------------------
# Test 8 — agent0@system excluded → tasks_completed never checked
# ---------------------------------------------------------------------------


def test_agent0_excluded_tasks_completed_never_checked() -> None:
    """Design gap: agent0@system is excluded from divergence reporting by
    _SKIP_AGENTS, so its tasks_completed counter is never validated.

    If agent0's stored tasks_completed is wrong (e.g., it has qualifying
    payment events in history indicating 4 completions, but stored shows 0),
    no divergence is raised.  The exclusion is intentional but means any
    inconsistency in agent0's task count goes undetected.

    An operator could use agent0's excluded status to run untracked operations
    through it: agent0 makes payments, accumulates tasks_completed in history,
    but stored always shows 0 and no checker ever flags the gap.
    """
    events = [
        {"type": "payment", "agent": "agent0@system", "amount": 100, "issue": 1},
        {"type": "payment", "agent": "agent0@system", "amount": 200, "issue": 2},
        {"type": "payment", "agent": "agent0@system", "amount": 150, "issue": 3},
        {"type": "payment", "agent": "agent0@system", "amount": 50,  "issue": 4},
    ]
    stored_agents = {
        # agent0's stored tasks_completed is wildly wrong — never verified
        "agent0@system": {"tasks_completed": 0},
    }

    computed = compute_tasks_completed(events)

    # History shows 4 task completions for agent0
    assert computed.get("agent0@system", 0) == 4

    status, divergences, _, _ = check_consistency(stored_agents, computed)

    # agent0 is skipped entirely
    agent0_divs = [d for d in divergences if d["agent"] == "agent0@system"]
    assert agent0_divs == [], (
        "agent0@system is excluded from divergence checking by design."
    )
    assert status == "PASS", (
        "Checker says PASS.  agent0 has 4 qualifying history events but stored "
        "tasks_completed=0.  The exclusion rule means this is never flagged."
    )


# ---------------------------------------------------------------------------
# Test 9 — Zero-amount payment skipped → boundary check
# ---------------------------------------------------------------------------


def test_zero_amount_payment_not_counted() -> None:
    """Boundary check: payment events with amount=0 are not counted.

    compute_tasks_completed() applies `if amount <= 0: continue`.  A payment
    of exactly 0 WEA is ignored even if it has a valid agent and issue.

    If an operator's stored tasks_completed also ignores zero-value payments,
    both sides show the same (lower) count → PASS.  Any real task that was
    'paid' with 0 WEA (e.g., a clerical entry or test event) is invisible.

    stored=1 (issue 10 only), computed=1 (issue 10 only; issue 20 dropped)
    → PASS despite two qualifying events existing.
    """
    events = [
        {"type": "payment", "agent": "Hank@claude", "amount": 50, "issue": 10},
        # Zero-amount payment: amount <= 0 → skipped
        {"type": "payment", "agent": "Hank@claude", "amount": 0,  "issue": 20},
    ]
    stored_agents = {
        "Hank@claude": {"tasks_completed": 1},
    }

    computed = compute_tasks_completed(events)

    assert computed.get("Hank@claude", 0) == 1, (
        "Zero-amount payment is not counted — only issue 10 qualifies."
    )

    status, divergences, _, _ = check_consistency(stored_agents, computed)

    assert status == "PASS"
    assert divergences == []


# ---------------------------------------------------------------------------
# Test 10 — Float issue truncated by int() → dedup with integer issue
# ---------------------------------------------------------------------------


def test_float_issue_truncated_deduped_with_int_issue_false_pass() -> None:
    """Bypass vector: float issue values are truncated by int(), merging
    distinct-looking issues into the same dedup key.

    compute_tasks_completed() converts issue via int(issue).  For a float like
    42.9, int(42.9) = 42.  A separate event with issue=42 (integer) maps to
    the same key.  The set deduplicates them → count=1.

    Real violation: Ivy@claude completed two different tasks.  One was
    recorded with issue=42 and another with issue=42.9 (a float, perhaps from
    an older serialisation path).  The real count should be 2 (two distinct
    tasks).  The script computes 1 (both map to key 42).  If stored also shows
    1 (matching the truncated computation) → PASS, but one task was missed.
    """
    events = [
        {"type": "payment", "agent": "Ivy@claude", "amount": 30, "issue": 42},
        # Float issue: int(42.9) = 42 — collides with issue 42 → deduped
        {"type": "payment", "agent": "Ivy@claude", "amount": 25, "issue": 42.9},
    ]
    stored_agents = {
        "Ivy@claude": {"tasks_completed": 1},  # matches truncated computation
    }

    computed = compute_tasks_completed(events)

    assert computed.get("Ivy@claude", 0) == 1, (
        "int(42.9) == 42 — both events map to the same issue key; count = 1."
    )

    status, divergences, _, _ = check_consistency(stored_agents, computed)

    assert status == "PASS", (
        "Checker says PASS.  Two distinct task completions (42 and 42.9) are "
        "collapsed into one by int() truncation.  The second task is invisible."
    )
    assert divergences == []


# ---------------------------------------------------------------------------
# Test 11 — Missing/empty/null agent fields skipped → invisible completion
# ---------------------------------------------------------------------------


def test_missing_or_empty_agent_field_silently_skipped() -> None:
    """Bypass vector: payment events with missing, empty, or null agent fields
    are silently skipped.

    compute_tasks_completed() checks ``if not agent: continue`` before
    processing an event.  Missing, empty-string, and null agent values are all
    falsy — each event is dropped.

    If tasks were completed and the payment events were written without a
    usable agent field, the completions are invisible to the checker.  As long
    as stored tasks_completed also omits those ghost completions, both sides
    agree → PASS.
    """
    events = [
        # Legitimate event for Kay
        {"type": "payment", "agent": "Kay@codex", "amount": 30, "issue": 9},
        # Missing agent field → skipped entirely
        {"type": "payment", "amount": 40, "issue": 10},
        # Empty agent field → skipped entirely
        {"type": "payment", "agent": "", "amount": 40, "issue": 11},
        # Null agent field → skipped entirely
        {"type": "payment", "agent": None, "amount": 40, "issue": 12},
    ]
    stored_agents = {
        "Kay@codex": {"tasks_completed": 1},
    }

    computed = compute_tasks_completed(events)

    # Kay is correctly counted; malformed agent fields contribute nothing.
    assert computed.get("Kay@codex", 0) == 1
    assert None not in computed
    assert "" not in computed, (
        "Empty-agent events are skipped; no entry is created for agent=''."
    )

    status, divergences, _, _ = check_consistency(stored_agents, computed)

    assert status == "PASS"
    assert divergences == [], (
        "Checker says PASS.  Payments with missing, empty, or null agent "
        "fields are completely invisible — no agent receives credit, and the "
        "completions are lost."
    )


# ---------------------------------------------------------------------------
# Test 12 — Event type matching is case-sensitive
# ---------------------------------------------------------------------------


def test_event_type_case_sensitivity_silently_drops_events() -> None:
    """Bypass vector: event type matching is strict and case-sensitive."""
    events = [
        {"type": "Payment", "agent": "Mallory@claude", "amount": 10, "issue": 1},
        {"type": "ACCEPT", "agent": "Mallory@claude", "amount": 10, "issue": 2},
    ]
    stored_agents = {
        "Mallory@claude": {"tasks_completed": 0},
    }

    computed = compute_tasks_completed(events)

    assert computed.get("Mallory@claude", 0) == 0, (
        "Only lowercase payment/accept are counted; wrong-case variants are ignored."
    )

    status, divergences, _, _ = check_consistency(stored_agents, computed)

    assert status == "PASS"
    assert divergences == []


# ---------------------------------------------------------------------------
# Test 13 — Invalid JSON lines are silently dropped
# ---------------------------------------------------------------------------


def test_invalid_json_lines_silently_dropped_false_pass(tmp_path: Path) -> None:
    """Bypass vector: malformed JSON lines in history are skipped entirely."""
    history_file = tmp_path / "2026-01-01.jsonl"
    history_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {"type": "payment", "agent": "Eve@claude", "amount": 10, "issue": 1}
                ),
                '{"type": "payment", "agent": "Eve@claude", "amount": 10, "issue": 2',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    events = _iter_events(tmp_path)
    computed = compute_tasks_completed(events)
    stored_agents = {
        "Eve@claude": {"tasks_completed": 1},
    }

    assert len(events) == 1, "Malformed JSON lines are skipped instead of failing."
    assert computed.get("Eve@claude", 0) == 1

    status, divergences, _, _ = check_consistency(stored_agents, computed)

    assert status == "PASS"
    assert divergences == []
