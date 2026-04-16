"""Adversarial tests for scripts/check_balances_earned_consistency.py

Each test targets a specific bypass vector — inputs that cause the checker to
return PASS (or WARNING-only status, not FAIL) when there is a real
consistency violation between ``total_earned``/``total_spent`` stored in
``balances.json`` and what ``ledger/history/*.jsonl`` actually shows.

All tests are self-contained: in-memory event lists and stored-agent dicts
only.  No real ledger files are read.

Bypass vectors covered:
  1. [GAP] History-only agent absent from stored → WARNING, not FAIL
  2. [GAP] escrow_return with missing issue field silently dropped; paired
           corruption passes
  3. Unknown event type silently ignored → false PASS when stored also ignores
  4. Negative accept amount silently ignored → false PASS
  5. Symmetric corruption: inflated history + matching stored → false PASS
  6. trajectory_mint single-agent with empty agent field drops credit
  7. escrow_return author-fallback credits wrong agent; false PASS if stored
     reflects the same fallback error
  8. per_agent shorter than agents → last agent silently omitted
  9. issue=None wildcard: one unlabelled escrow_create authorises unlimited
     escrow_returns with no issue field
 10. agent0 exclusion allows uninspected relay through escrow chain
"""

from __future__ import annotations

from scripts.check_balances_earned_consistency import (
    check_consistency,
    compute_earned_spent,
)


# ---------------------------------------------------------------------------
# Test 1 — [GAP] History-only agent absent from stored emits WARNING, not FAIL
# ---------------------------------------------------------------------------


def test_history_only_agent_absent_from_stored_emits_warning_not_fail() -> None:
    """[CONFIRMED GAP] Agent with non-zero history earnings but absent from
    stored_agents produces a warning entry, not a divergence.

    check_consistency() loops over stored_agents for divergence detection and
    separately checks history-only agents for warnings.  The final status is
    ``PASS`` when ``len(divergences) == 0``, regardless of how many warnings
    exist.

    A real consistency violation: Alice@claude earned 100 WEA according to
    history (computed_earned["Alice@claude"] == 100) but has no entry at all
    in balances.json.  Her stored total_earned is effectively 0 — a real
    discrepancy.  The checker only warns; it never fails.

    Attack scenario: an operator removes an agent from balances.json to hide
    their accumulated earnings.  The checker considers this a warning-level
    anomaly rather than a hard failure, so the missing agent slips through.
    """
    events = [
        {"type": "payment", "agent": "Alice@claude", "amount": 100},
    ]
    # Alice has no entry in stored_agents at all
    stored_agents: dict = {}

    computed_earned, computed_spent = compute_earned_spent(events)

    assert computed_earned.get("Alice@claude", 0) == 100, (
        "Alice has 100 WEA in history."
    )

    status, divergences, warnings, _ = check_consistency(
        stored_agents, computed_earned, computed_spent
    )

    # GAP: divergences list is empty → status is PASS
    assert divergences == [], (
        "No divergences are raised for Alice even though she is absent from stored."
    )
    assert status == "PASS", (
        "Checker reports PASS despite Alice being absent from balances.json "
        "while history shows 100 WEA earned.  Missing agents only produce "
        "warnings, not failures."
    )
    assert len(warnings) == 1, "Exactly one warning for the history-only agent."
    assert warnings[0]["agent"] == "Alice@claude"


# ---------------------------------------------------------------------------
# Test 2 — [GAP] escrow_return with no issue field silently dropped
# ---------------------------------------------------------------------------


def test_escrow_return_missing_issue_field_silently_dropped_false_pass() -> None:
    """[CONFIRMED GAP] An escrow_return event without an 'issue' field is
    silently skipped, making a legitimate earned credit invisible.

    compute_earned_spent() first collects issue numbers from escrow_create
    events into escrow_create_issues (a set of ints or None).  For each
    escrow_return it checks ``if issue not in escrow_create_issues``.  When the
    return event has no 'issue' field, ``e.get("issue")`` returns None, and
    None is not in a set of integers → the return is skipped.

    Real violation: Bob@claude returned an escrow of 80 WEA (so his
    total_earned should include 80 from the return) but the event was written
    without the issue field.  The script computes 0 for his earned, matching a
    stored value of 0 → PASS.  The actual total_earned should be 80.

    Attack scenario: an operator who knows about this gap can omit the 'issue'
    field from an escrow_return to make the credit invisible to this checker,
    while a separate (checked) payment keeps the balance arithmetic valid.
    """
    events = [
        # Modern escrow_create for issue 42 — puts 80 WEA into escrow
        {"type": "escrow_create", "author": "Bob@claude", "issue": 42, "amount": 80},
        # Return event MISSING the issue field — issue=None, not in {42} → skipped
        {"type": "escrow_return", "recipient": "Bob@claude", "amount": 80},
    ]
    stored_agents = {
        "Bob@claude": {
            "balance": 0,
            "total_earned": 0,   # operator also missed the return
            "total_spent": 80,
        }
    }

    computed_earned, computed_spent = compute_earned_spent(events)

    # GAP: escrow_return is dropped because its issue=None not in {42}
    assert computed_earned.get("Bob@claude", 0) == 0, (
        "escrow_return is skipped when the issue field is absent."
    )
    assert computed_spent.get("Bob@claude", 0) == 80

    status, divergences, _, _summary = check_consistency(
        stored_agents, computed_earned, computed_spent
    )

    # False PASS: both sides show total_earned=0, no divergence
    assert status == "PASS", (
        "Checker reports PASS even though Bob legitimately earned 80 WEA via "
        "escrow_return — the missing issue field makes the event invisible."
    )
    assert divergences == []


# ---------------------------------------------------------------------------
# Test 3 — Unknown event type silently ignored → false PASS
# ---------------------------------------------------------------------------


def test_unknown_event_type_silently_ignored_false_pass() -> None:
    """Bypass vector: an unrecognised event type is silently discarded.

    compute_earned_spent() only handles trajectory_mint, payment, accept,
    escrow_return, and escrow_create.  Any other type is ignored.  If an
    operator writes a "bonus" event to history but ALSO fails to update
    total_earned (mirroring the script's blind spot), both sides stay at
    the pre-bonus value → PASS.

    The existence of unrecognised events in the history is never flagged.
    A novel event type could be used to inject credits into the running
    balance of a balance-tracking checker (like T1S14) while remaining
    entirely invisible here.
    """
    events = [
        # Recognised: Carol earned 200 WEA via payment
        {"type": "payment", "agent": "Carol@claude", "amount": 200},
        # Unrecognised: "bonus" event for Dave — silently dropped
        {"type": "bonus", "agent": "Dave@claude", "amount": 75},
    ]
    stored_agents = {
        "Carol@claude": {"balance": 200, "total_earned": 200, "total_spent": 0},
        "Dave@claude":  {"balance": 0,   "total_earned": 0,   "total_spent": 0},
    }

    computed_earned, computed_spent = compute_earned_spent(events)

    assert computed_earned.get("Dave@claude", 0) == 0, (
        "'bonus' event type is not handled; Dave's computed earned = 0."
    )

    status, divergences, _, _summary = check_consistency(
        stored_agents, computed_earned, computed_spent
    )

    # False PASS: both computed and stored agree on 0 for Dave
    assert status == "PASS", (
        "Checker says PASS even though a 'bonus' event for Dave exists in "
        "history.  The unrecognised event type is completely invisible."
    )
    assert divergences == []


# ---------------------------------------------------------------------------
# Test 4 — Negative accept amount silently ignored → false PASS
# ---------------------------------------------------------------------------


def test_negative_accept_amount_silently_ignored_false_pass() -> None:
    """Bypass vector: accept events with a negative amount are silently ignored.

    The guard ``if a and amount > 0`` rejects non-positive amounts.  A negative
    accept event (e.g., a clawback or erroneous entry) is completely discarded.
    If the operator's stored total_earned ALSO ignores the negative accept
    (stores the pre-clawback value), both sides agree → PASS.

    A real inconsistency exists: history contains a -60 accept event that
    should reduce total_earned, but the script never applies it.  An attacker
    who manipulates history by inserting a negative accept to undo a payment
    (without adjusting total_earned) cannot be detected by this checker.
    """
    events = [
        {"type": "accept", "agent": "Eve@claude", "amount": 150},
        # Clawback attempt: negative accept — silently dropped
        {"type": "accept", "agent": "Eve@claude", "amount": -60},
    ]
    stored_agents = {
        # Operator also ignored the negative accept
        "Eve@claude": {"balance": 150, "total_earned": 150, "total_spent": 0},
    }

    computed_earned, computed_spent = compute_earned_spent(events)

    # GAP: negative accept is discarded; computed shows 150, not 90
    assert computed_earned.get("Eve@claude", 0) == 150, (
        "Negative accept (-60) is silently ignored; computed total_earned = 150."
    )

    status, divergences, _, _summary = check_consistency(
        stored_agents, computed_earned, computed_spent
    )

    # False PASS: both sides agree on 150
    assert status == "PASS", (
        "Checker says PASS despite a negative accept event in history. "
        "The clawback attempt is completely invisible."
    )
    assert divergences == []


# ---------------------------------------------------------------------------
# Test 5 — Symmetric corruption: inflated history + inflated stored → false PASS
# ---------------------------------------------------------------------------


def test_symmetric_corruption_inflated_history_and_stored_false_pass() -> None:
    """Bypass vector: paired corruption of history and stored metadata.

    The checker computes totals from history, then compares to stored values.
    If an attacker inserts a fake payment event into history AND also inflates
    stored total_earned by the same amount, both sides report the same (wrong)
    value → PASS.

    This is the fundamental limitation of an arithmetic-consistency check: it
    can only verify that the two records agree with each other, not that either
    record is independently correct.  A coordinated ledger manipulation that
    touches both history files and balances.json is completely undetectable.
    """
    events = [
        # Legitimate payment: Frank earned 100 WEA
        {"type": "payment", "agent": "Frank@claude", "amount": 100},
        # Fraudulent extra payment: not a real task reward
        {"type": "payment", "agent": "Frank@claude", "amount": 50},
    ]
    stored_agents = {
        # Stored also reflects the fraudulent +50 — consistent with history
        "Frank@claude": {"balance": 150, "total_earned": 150, "total_spent": 0},
    }

    computed_earned, computed_spent = compute_earned_spent(events)

    assert computed_earned.get("Frank@claude", 0) == 150

    status, divergences, _, _summary = check_consistency(
        stored_agents, computed_earned, computed_spent
    )

    # False PASS: fabricated event and stored agree → no divergence
    assert status == "PASS", (
        "Checker says PASS when both history and stored metadata are equally "
        "inflated.  Symmetric corruption of two sources is undetectable."
    )
    assert divergences == []


# ---------------------------------------------------------------------------
# Test 6 — trajectory_mint single-agent with empty agent field drops credit
# ---------------------------------------------------------------------------


def test_trajectory_mint_single_agent_empty_field_drops_credit() -> None:
    """Bypass vector: a single-agent trajectory_mint with agent="" is a no-op.

    For the single-agent mint format (no 'agents' list, uses 'agent' + 'amount'
    fields), the code checks ``if a:`` before crediting.  An empty string is
    falsy — the entire credit is silently dropped.

    If the operator's stored total_earned for the intended recipient ALSO shows
    0 (because they made the same omission), the checker sees 0 == 0 → PASS.
    The intended 40 WEA payment is invisible.
    """
    events = [
        {
            "type": "trajectory_mint",
            # Single-agent format; 'agent' field is empty — no credit applied
            "agent": "",
            "amount": 40,
        }
    ]
    stored_agents = {
        # Intended recipient added to stored but total_earned not updated
        "Grace@claude": {"balance": 0, "total_earned": 0, "total_spent": 0},
    }

    computed_earned, computed_spent = compute_earned_spent(events)

    assert computed_earned.get("Grace@claude", 0) == 0, (
        "Empty agent field in single-agent trajectory_mint drops the credit."
    )

    status, divergences, _, _summary = check_consistency(
        stored_agents, computed_earned, computed_spent
    )

    assert status == "PASS", (
        "Checker says PASS.  The 40 WEA trajectory_mint with agent='' is "
        "invisible — no credit appears in either computed or stored."
    )
    assert divergences == []


# ---------------------------------------------------------------------------
# Test 7 — escrow_return author-fallback credits wrong agent
# ---------------------------------------------------------------------------


def test_escrow_return_author_fallback_credits_wrong_agent_false_pass() -> None:
    """Bypass vector: escrow_return without a 'recipient' field falls back to
    'author', which may be the wrong entity.

    The recipient resolution logic is:
        recip = e.get("recipient") or e.get("author") or e.get("agent", "")

    If 'recipient' is absent, the script credits 'author'.  In an escrow_return
    event, the 'author' is typically the task poster (who locked the funds), not
    the intended return recipient.  If the script and the operator both apply the
    same wrong fallback, both sides credit the author → PASS.

    Real violation: Hank@claude posted the task (author) and Ivy@claude should
    receive the return, but the event was written without a 'recipient' field.
    The checker credits Hank (the author), matching a stored value that also
    credits Hank — so no divergence is raised even though Ivy should have been
    paid.
    """
    events = [
        # Modern escrow_create by Hank
        {
            "type": "escrow_create",
            "author": "Hank@claude",
            "issue": 7,
            "amount": 60,
        },
        # Return without explicit recipient — falls back to 'author' = Hank
        {
            "type": "escrow_return",
            "author": "Hank@claude",   # should have been recipient: Ivy@claude
            "issue": 7,
            "amount": 60,
        },
    ]
    stored_agents = {
        # Operator also applied the fallback: Hank credited, Ivy not
        "Hank@claude": {"balance": 0, "total_earned": 60, "total_spent": 60},
        "Ivy@claude":  {"balance": 0, "total_earned": 0,  "total_spent": 0},
    }

    computed_earned, computed_spent = compute_earned_spent(events)

    # Hank gets the escrow_return credit via author fallback
    assert computed_earned.get("Hank@claude", 0) == 60, (
        "Hank credited via author fallback because recipient field is absent."
    )
    assert computed_earned.get("Ivy@claude", 0) == 0, (
        "Ivy receives nothing even though she was the intended recipient."
    )

    status, divergences, _, _summary = check_consistency(
        stored_agents, computed_earned, computed_spent
    )

    # False PASS: both sides applied the same wrong fallback
    assert status == "PASS", (
        "Checker says PASS.  Wrong-agent fallback is undetectable when stored "
        "and computed both apply the same incorrect author substitution."
    )
    assert divergences == []


# ---------------------------------------------------------------------------
# Test 8 — per_agent shorter than agents silently omits last agent
# ---------------------------------------------------------------------------


def test_per_agent_shorter_than_agents_last_agent_silently_omitted() -> None:
    """Bypass vector: when per_agent list is shorter than the agents list, the
    loop silently skips the trailing agents.

    The loop ``for i, a in enumerate(agents_list): if i < len(per_agent)``
    stops crediting once per_agent is exhausted.  The last agent in the list
    receives 0 WEA.  If the stored total_earned for that agent is also 0
    (because the operator processed the same truncated event), the checker
    sees 0 == 0 → PASS.

    The intended payment to the omitted agent is invisible to both the checker
    and the operator.
    """
    events = [
        {
            "type": "trajectory_mint",
            "agents": ["Jack@claude", "Kay@codex", "Leo@claude"],
            "per_agent": [15, 25],   # Leo is silently omitted (list too short)
        }
    ]
    stored_agents = {
        "Jack@claude": {"balance": 15, "total_earned": 15, "total_spent": 0},
        "Kay@codex":   {"balance": 25, "total_earned": 25, "total_spent": 0},
        "Leo@claude":  {"balance": 0,  "total_earned": 0,  "total_spent": 0},
    }

    computed_earned, _ = compute_earned_spent(events)

    assert computed_earned.get("Jack@claude", 0) == 15
    assert computed_earned.get("Kay@codex", 0) == 25
    assert computed_earned.get("Leo@claude", 0) == 0, (
        "Leo is omitted because per_agent is shorter than agents."
    )

    status, divergences, _, _summary = check_consistency(
        stored_agents, computed_earned, computed_spent={}
    )

    # False PASS: both sides show 0 for Leo → no divergence
    assert status == "PASS", (
        "Checker says PASS.  Leo was supposed to receive payment but per_agent "
        "truncation is consistent across history and stored — neither flags it."
    )
    assert divergences == []


# ---------------------------------------------------------------------------
# Test 9 — issue=None wildcard: one unlabelled escrow_create unlocks many returns
# ---------------------------------------------------------------------------


def test_issue_none_wildcard_one_create_authorises_many_returns() -> None:
    """Bypass vector: a single escrow_create without an issue field adds None
    to escrow_create_issues, authorising every subsequent escrow_return that
    also lacks an issue field.

    compute_earned_spent() checks ``if issue not in escrow_create_issues`` to
    filter old-format returns.  When any escrow_create has issue=None (absent
    'issue' field), None enters the set.  All escrow_return events with
    issue=None then pass the gate — regardless of amount, recipient, or how
    many of them exist.

    Attack: write one small unlabelled escrow_create to 'authorise' None, then
    write arbitrarily large or numerous escrow_return events with no issue field.
    The amounts of these returns are never cross-validated against the create.
    If stored total_earned matches the summed returns, the checker says PASS.
    """
    events = [
        # A single small unlabelled escrow_create: no 'issue' field → None enters set
        {"type": "escrow_create", "author": "Mia@claude", "amount": 1},
        # Three large returns, all without issue field — all pass the None gate
        {"type": "escrow_return", "recipient": "Mia@claude", "amount": 500},
        {"type": "escrow_return", "recipient": "Mia@claude", "amount": 500},
        {"type": "escrow_return", "recipient": "Mia@claude", "amount": 500},
    ]
    stored_agents = {
        "Mia@claude": {
            "balance": 1499,
            "total_earned": 1500,
            "total_spent": 1,
        }
    }

    computed_earned, computed_spent = compute_earned_spent(events)

    # All three returns pass because None is in escrow_create_issues
    assert computed_earned.get("Mia@claude", 0) == 1500, (
        "Three unlabelled escrow_returns are each authorised by the single None key."
    )
    assert computed_spent.get("Mia@claude", 0) == 1

    status, divergences, _, _summary = check_consistency(
        stored_agents, computed_earned, computed_spent
    )

    # False PASS: computed matches stored; no divergence despite 1 WEA escrowed
    # releasing 1500 WEA via three returns
    assert status == "PASS", (
        "Checker says PASS.  A single unlabelled escrow_create (amount=1) "
        "authorises three escrow_returns totalling 1500 WEA because they all "
        "share the None issue key.  No amount validation exists."
    )
    assert divergences == []


# ---------------------------------------------------------------------------
# Test 10 — agent0 exclusion allows uninspected relay through escrow chain
# ---------------------------------------------------------------------------


def test_agent0_exclusion_allows_uninspected_relay() -> None:
    """Bypass vector: agent0@system is excluded from divergence reporting,
    making it an unmonitored relay for credit injection.

    The checker skips agent0 by design (_SKIP_AGENTS).  Any amount debited
    from agent0 (via escrow_create) or credited to agent0 is never compared
    against stored values.  If a beneficiary's balance reflects a credit
    routed through agent0, the checker only validates the beneficiary's side.
    As long as stored total_earned for the beneficiary matches computed, the
    chain passes — even if agent0's own books are wildly inconsistent.

    Scenario: agent0 creates a large escrow (9999 WEA) that is then returned
    to Nina@claude.  agent0's stored balance is stale/wrong, but the checker
    never notices.  Nina's 9999 credit matches stored → PASS.
    """
    events = [
        # agent0 creates a massive escrow — its debit is never audited
        {
            "type": "escrow_create",
            "author": "agent0@system",
            "issue": 99,
            "amount": 9999,
        },
        # The escrow is returned to Nina
        {
            "type": "escrow_return",
            "recipient": "Nina@claude",
            "issue": 99,
            "amount": 9999,
        },
    ]
    stored_agents = {
        "agent0@system": {
            "balance": 10000,   # stale — not updated for the 9999 spend
            "total_earned": 0,
            "total_spent": 0,   # wrong: should be 9999
        },
        "Nina@claude": {
            "balance": 9999,
            "total_earned": 9999,
            "total_spent": 0,
        },
    }

    computed_earned, computed_spent = compute_earned_spent(events)

    assert computed_spent.get("agent0@system", 0) == 9999
    assert computed_earned.get("Nina@claude", 0) == 9999

    status, divergences, _, _summary = check_consistency(
        stored_agents, computed_earned, computed_spent
    )

    # agent0 is excluded — its 0 stored_spent vs 9999 computed_spent is never flagged
    agent0_divs = [d for d in divergences if d["agent"] == "agent0@system"]
    assert agent0_divs == [], (
        "agent0@system is excluded from divergence checking by design."
    )

    # Nina's credit matches stored → no divergence for Nina either
    nina_divs = [d for d in divergences if d["agent"] == "Nina@claude"]
    assert nina_divs == []

    assert status == "PASS", (
        "Checker says PASS.  agent0 created a 9999 WEA escrow not reflected in "
        "its stored total_spent, but the exclusion rule means this is never "
        "checked.  The full relay credit lands on Nina without any source audit."
    )
