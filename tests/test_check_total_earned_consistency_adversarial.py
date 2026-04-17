"""Adversarial tests for scripts/check_total_earned_consistency.py

Each test targets a specific bypass vector — inputs that cause the checker to
return PASS (or WARNING-only status, not FAIL) when there is a real consistency
violation between ``total_earned`` stored in ``balances.json`` and what
``ledger/history/*.jsonl`` actually shows.

All tests are self-contained: in-memory event lists and stored-agent dicts
only.  No real ledger files are read.

Bypass vectors covered:
  1. [GAP] History-only agent absent from stored → WARNING, not FAIL
  2. [GAP] Malformed JSON prefix on a line drops all events on that line
  3. Unknown event type silently ignored → false PASS
  4. Symmetric corruption: inflated history + matching stored → false PASS
  5. trajectory_mint negative amount not guarded (unlike payment/accept)
  6. escrow_return fallback to agent field credits wrong entity
  7. per_agent shorter than agents silently omits last agent
  8. Empty agent field in single-agent trajectory_mint drops credit
  9. escrow_return with no escrow_create filter → uncorroborated credit counted
 10. escrow_return negative amount not guarded — subtracts from earned
 11. agent0@system excluded → relay through agent0 escrow never audited
 12. trajectory_mint multi-agent: top-level amount field silently ignored
"""

from __future__ import annotations

from scripts.check_total_earned_consistency import (
    _extract_objects,
    check_consistency,
    compute_total_earned,
)


# ---------------------------------------------------------------------------
# Test 1 — [GAP] History-only agent absent from stored → WARNING, not FAIL
# ---------------------------------------------------------------------------


def test_history_only_agent_absent_from_stored_emits_warning_not_fail() -> None:
    """[CONFIRMED GAP] An agent with non-zero history earnings but no entry in
    stored_agents produces a warning, not a divergence.

    check_consistency() iterates over stored_agents to detect divergences.
    Agents that appear only in computed history (absent from stored) are placed
    into warnings, not divergences.  Status is ``PASS`` whenever
    len(divergences) == 0, regardless of warning count.

    Real violation: Alice@claude has 120 WEA earned in history but no entry
    in balances.json at all.  Her effective stored total_earned is 0 — a real
    discrepancy of 120 — but the checker only emits a warning and returns PASS.

    Attack scenario: remove an agent's balances.json entry to hide their
    accumulated earnings.  The checker will not flag this as a FAIL.
    """
    # GAP: history-only agents produce warnings, not divergences
    events = [
        {"type": "payment", "agent": "Alice@claude", "amount": 120},
    ]
    stored_agents: dict = {}

    computed = compute_total_earned(events)

    assert computed.get("Alice@claude", 0) == 120

    status, divergences, warnings, _ = check_consistency(stored_agents, computed)

    assert divergences == [], "No divergences — history-only agents are only warned about."
    assert status == "PASS", (
        "Checker returns PASS even though Alice has 120 WEA in history and 0 "
        "in stored_agents.  The missing-agent check emits a warning, not a FAIL."
    )
    assert len(warnings) == 1
    assert warnings[0]["agent"] == "Alice@claude"


# ---------------------------------------------------------------------------
# Test 2 — [GAP] Malformed JSON prefix drops all events on that line
# ---------------------------------------------------------------------------


def test_malformed_json_prefix_drops_all_events_on_line() -> None:
    """[CONFIRMED GAP] A line whose first bytes are invalid JSON causes
    _extract_objects to immediately break, silently discarding every event
    encoded on that physical line.

    _extract_objects() skips leading ASCII whitespace, then calls
    decoder.raw_decode(line, idx).  On JSONDecodeError it ``break``s out of
    the loop — no further objects on the line are attempted.  A line that
    starts with an invalid character (e.g. a stray X) causes an immediate
    break, even if one or more valid JSON objects follow.

    Real violation: Bob@claude's payment event is on a line prefixed with
    garbage bytes.  The script reads 0 for Bob's earnings.  If Bob's stored
    total_earned was set by the same (broken) script run, or if the operator
    also missed it, stored shows 0 too — checker says PASS.  Bob's real 200 WEA
    is invisible.

    Attack scenario: inject a stray non-JSON character at the start of a history
    line that contains a large payment event.  The corrupted line is silently
    skipped by the parser, and the corresponding stored value is never updated —
    giving the attacker a false PASS when the true earned total is non-zero.
    """
    # GAP: malformed JSON prefix on a line causes break; rest of line dropped
    corrupted_line = 'XGARBAGE{"type": "payment", "agent": "Bob@claude", "amount": 200}'

    objects = _extract_objects(corrupted_line)

    # The entire line is dropped because the prefix is invalid JSON
    assert objects == [], (
        "_extract_objects breaks on the first decode error; the valid payment "
        "event that follows the garbage prefix is never reached."
    )

    # Show the false PASS: compute earned from the corrupted parse result (nothing).
    # Stored was legitimately set to 200 before corruption — now diverges silently
    # IF operator re-runs the checker against the corrupted file.
    # More critically: if stored was set by the same script run over the corrupted
    # file, both stored and computed = 0 → false PASS.
    stored_agents_correct = {
        "Bob@claude": {"balance": 200, "total_earned": 200},  # correct
    }
    computed_from_corruption = compute_total_earned(objects)  # no events

    # False PASS scenario: stored also 0 (set from same broken parse run)
    stored_agents_broken = {
        "Bob@claude": {"balance": 0, "total_earned": 0},
    }
    status, divergences, _, _ = check_consistency(
        stored_agents_broken, computed_from_corruption
    )

    assert status == "PASS", (
        "Checker returns PASS when both computed (from corrupted line) and "
        "stored (set from same broken run) show 0.  Bob's real 200 WEA is gone."
    )
    assert divergences == []

    # Confirm: a correct stored value DOES cause FAIL — the gap only appears
    # when stored was also sourced from the broken parse (or operator missed it).
    status_correct, divs_correct, _, _ = check_consistency(
        stored_agents_correct, computed_from_corruption
    )
    assert status_correct == "FAIL", (
        "Checker correctly FAILs when stored shows the real 200 WEA but "
        "computed sees 0 (corrupted line).  The GAP requires stored to also "
        "be wrong — e.g., set from the same broken script run."
    )
    assert len(divs_correct) == 1


# ---------------------------------------------------------------------------
# Test 3 — Unknown event type silently ignored → false PASS
# ---------------------------------------------------------------------------


def test_unknown_event_type_silently_ignored_false_pass() -> None:
    """Bypass vector: an unrecognised event type is silently discarded.

    compute_total_earned() only handles trajectory_mint, payment, accept, and
    escrow_return.  Any other type (e.g. 'bonus') is ignored without warning.
    If an operator writes a 'bonus' event to history but ALSO fails to update
    total_earned (mirroring the script's blind spot), both sides stay at the
    pre-bonus value → PASS.

    The existence of unrecognised event types in history is never flagged.
    """
    events = [
        {"type": "payment", "agent": "Carol@claude", "amount": 200},
        # 'bonus' is not a recognised type — silently dropped
        {"type": "bonus", "agent": "Dave@claude", "amount": 75},
    ]
    stored_agents = {
        "Carol@claude": {"balance": 200, "total_earned": 200},
        "Dave@claude":  {"balance": 0,   "total_earned": 0},
    }

    computed = compute_total_earned(events)

    assert computed.get("Dave@claude", 0) == 0, (
        "'bonus' type is not handled; Dave's computed earned = 0."
    )

    status, divergences, _, _ = check_consistency(stored_agents, computed)

    assert status == "PASS", (
        "Checker says PASS even though a 'bonus' event for Dave exists in history."
    )
    assert divergences == []


# ---------------------------------------------------------------------------
# Test 4 — Symmetric corruption: inflated history + inflated stored → PASS
# ---------------------------------------------------------------------------


def test_symmetric_corruption_inflated_history_and_stored_false_pass() -> None:
    """Bypass vector: paired corruption of history and stored metadata.

    The checker computes earned from history, then compares against stored.
    If an attacker inserts a fake payment event into history AND inflates stored
    total_earned by the same amount, both sides report the same (wrong) value
    and no divergence is raised.

    This is the fundamental limitation of an arithmetic-consistency check: it
    only verifies that two records agree with each other, not that either is
    independently correct.  Coordinated manipulation of both sources is
    undetectable.
    """
    events = [
        {"type": "payment", "agent": "Eve@claude", "amount": 100},
        # Fraudulent extra payment: not a real task reward
        {"type": "payment", "agent": "Eve@claude", "amount": 999},
    ]
    stored_agents = {
        # Stored also reflects the fraudulent +999 — consistent with history
        "Eve@claude": {"balance": 1099, "total_earned": 1099},
    }

    computed = compute_total_earned(events)

    assert computed.get("Eve@claude", 0) == 1099

    status, divergences, _, _ = check_consistency(stored_agents, computed)

    assert status == "PASS", (
        "Symmetric inflation of history and stored metadata is undetectable."
    )
    assert divergences == []


# ---------------------------------------------------------------------------
# Test 5 — trajectory_mint negative amount not guarded (unlike payment/accept)
# ---------------------------------------------------------------------------


def test_trajectory_mint_negative_amount_not_guarded() -> None:
    """Bypass vector: a single-agent trajectory_mint with a negative amount
    reduces the agent's computed earned without any positivity check.

    payment/accept events have an explicit ``if a and amount > 0`` guard.
    trajectory_mint (single-agent format) has no such guard — it applies
    ``earned[a] += amount`` unconditionally.  A negative trajectory_mint
    decreases computed earned below what the agent actually received.

    If operator's stored total_earned ALSO fails to count the negative mint
    (i.e., both treat a 200 WEA payment minus 50 WEA negative mint as 150),
    both sides agree → PASS.  The inconsistency in how negative mints are
    handled is invisible.

    The asymmetry (guard on payment/accept, no guard on trajectory_mint)
    means the spec is ambiguous for negative mints — and the script's choice
    is undocumented.
    """
    events = [
        {"type": "payment", "agent": "Frank@claude", "amount": 200},
        # Negative trajectory_mint: not guarded — subtracts from earned
        {"type": "trajectory_mint", "agent": "Frank@claude", "amount": -50},
    ]
    stored_agents = {
        # Operator applied the same logic: 200 - 50 = 150
        "Frank@claude": {"balance": 150, "total_earned": 150},
    }

    computed = compute_total_earned(events)

    # trajectory_mint -50 is applied: 200 + (-50) = 150
    assert computed.get("Frank@claude", 0) == 150, (
        "Negative trajectory_mint is not guarded — subtracts 50 from earned."
    )

    status, divergences, _, _ = check_consistency(stored_agents, computed)

    assert status == "PASS", (
        "Checker says PASS.  Both sides agree on 150 because neither guards "
        "against negative trajectory_mint amounts."
    )
    assert divergences == []


# ---------------------------------------------------------------------------
# Test 6 — escrow_return fallback to agent field credits wrong entity
# ---------------------------------------------------------------------------


def test_escrow_return_agent_fallback_credits_wrong_entity_false_pass() -> None:
    """Bypass vector: an escrow_return without a 'recipient' field falls back to
    the 'agent' field, which may be the wrong entity.

    The recipient resolution is: recip = e.get("recipient") or e.get("agent", "")

    Unlike check_balances_earned_consistency.py (which also tries 'author'),
    this script skips the 'author' fallback.  If the event has an 'agent' field
    that refers to the task poster (not the intended payee), the wrong person
    is credited.  If stored total_earned for the wrong agent matches computed,
    the checker says PASS.

    Real violation: Grace@claude was supposed to receive the returned escrow,
    but the event was written with 'agent': 'Hank@claude' (the task poster) and
    no 'recipient' field.  The script credits Hank.  If stored_agents reflects
    the same mistake, no divergence is raised.
    """
    events = [
        {
            "type": "escrow_return",
            "agent": "Hank@claude",   # task poster, not intended recipient
            "amount": 80,
            # No 'recipient' field — falls back to agent = Hank
        },
    ]
    stored_agents = {
        # Operator also applied the same wrong fallback
        "Hank@claude":  {"balance": 80, "total_earned": 80},
        "Grace@claude": {"balance": 0,  "total_earned": 0},  # should be 80
    }

    computed = compute_total_earned(events)

    assert computed.get("Hank@claude", 0) == 80, "Hank credited via agent fallback."
    assert computed.get("Grace@claude", 0) == 0, "Grace gets nothing."

    status, divergences, _, _ = check_consistency(stored_agents, computed)

    assert status == "PASS", (
        "Checker says PASS.  Wrong-agent fallback is undetectable when both "
        "stored and computed credit the same wrong agent."
    )
    assert divergences == []


# ---------------------------------------------------------------------------
# Test 7 — per_agent shorter than agents silently omits last agent
# ---------------------------------------------------------------------------


def test_per_agent_shorter_than_agents_last_agent_silently_omitted() -> None:
    """Bypass vector: when per_agent list is shorter than agents, the loop
    silently skips trailing agents with no credit.

    The loop ``for i, a in enumerate(agents_list): if i < len(per_agent)``
    stops crediting once per_agent is exhausted.  The last agent receives 0.
    If stored total_earned for that agent is also 0 (operator processed the
    same truncated event), checker sees 0 == 0 → PASS.
    """
    events = [
        {
            "type": "trajectory_mint",
            "agents": ["Iris@claude", "Jack@codex", "Kate@claude"],
            "per_agent": [20, 30],  # Kate is silently omitted (list too short)
        }
    ]
    stored_agents = {
        "Iris@claude": {"balance": 20, "total_earned": 20},
        "Jack@codex":  {"balance": 30, "total_earned": 30},
        "Kate@claude": {"balance": 0,  "total_earned": 0},  # she should have gotten paid
    }

    computed = compute_total_earned(events)

    assert computed.get("Iris@claude", 0) == 20
    assert computed.get("Jack@codex", 0) == 30
    assert computed.get("Kate@claude", 0) == 0, (
        "Kate is omitted because per_agent list is shorter than agents list."
    )

    status, divergences, _, _ = check_consistency(stored_agents, computed)

    assert status == "PASS", (
        "Checker says PASS.  Kate's omitted payment is invisible — both "
        "computed and stored agree on 0 due to truncated per_agent list."
    )
    assert divergences == []


# ---------------------------------------------------------------------------
# Test 8 — Empty agent field in single-agent trajectory_mint drops credit
# ---------------------------------------------------------------------------


def test_trajectory_mint_single_agent_empty_field_drops_credit() -> None:
    """Bypass vector: a single-agent trajectory_mint with agent='' is a no-op.

    The single-agent branch checks ``if a:`` before crediting.  An empty
    string is falsy — the credit is silently dropped.  If stored total_earned
    for the intended recipient is also 0 (because the event was never
    processed), checker sees 0 == 0 → PASS.
    """
    events = [
        {
            "type": "trajectory_mint",
            "agent": "",   # falsy — credit is dropped
            "amount": 55,
        }
    ]
    stored_agents = {
        "Leo@claude": {"balance": 0, "total_earned": 0},
    }

    computed = compute_total_earned(events)

    assert computed.get("Leo@claude", 0) == 0, (
        "Empty agent field in single-agent trajectory_mint drops the credit."
    )
    # No event credits Leo, so no computed entry exists
    assert "Leo@claude" not in computed

    status, divergences, _, _ = check_consistency(stored_agents, computed)

    assert status == "PASS", (
        "Checker says PASS.  The 55 WEA trajectory_mint with agent='' is "
        "invisible — neither computed nor stored reflects it."
    )
    assert divergences == []


# ---------------------------------------------------------------------------
# Test 9 — escrow_return uncorroborated by any escrow_create still counts
# ---------------------------------------------------------------------------


def test_escrow_return_without_escrow_create_still_counted() -> None:
    """Bypass vector: unlike check_balances_earned_consistency.py, this script
    has NO escrow_create filter.  Every escrow_return unconditionally adds to
    earned, whether or not a matching escrow_create exists.

    check_balances_earned_consistency.py first collects escrow_create issues
    and only counts escrow_returns for those issues.  This script skips that
    filter entirely — all escrow_return events count as income.

    A fabricated escrow_return (with no corresponding escrow_create in history)
    is credited if stored total_earned also reflects the fabricated credit.
    The script cannot distinguish legitimate returns from fabricated ones.
    """
    events = [
        # Pure fabrication: no escrow_create for issue 77 anywhere in history
        {"type": "escrow_return", "recipient": "Mia@claude", "amount": 400},
    ]
    stored_agents = {
        "Mia@claude": {"balance": 400, "total_earned": 400},
    }

    computed = compute_total_earned(events)

    # The escrow_return is counted — no filtering by escrow_create
    assert computed.get("Mia@claude", 0) == 400, (
        "Uncorroborated escrow_return still counts because there is no "
        "escrow_create filter in this script."
    )

    status, divergences, _, _ = check_consistency(stored_agents, computed)

    assert status == "PASS", (
        "Checker says PASS.  A fabricated escrow_return (no matching "
        "escrow_create) injects 400 WEA into Mia's earned total undetected."
    )
    assert divergences == []


# ---------------------------------------------------------------------------
# Test 10 — escrow_return with negative amount subtracts from earned
# ---------------------------------------------------------------------------


def test_escrow_return_negative_amount_subtracts_from_earned() -> None:
    """Bypass vector: escrow_return events have no amount > 0 guard.

    payment and accept events check ``if a and amount > 0`` before crediting.
    escrow_return does not — it applies ``earned[recip] += amount``
    unconditionally.  A negative escrow_return reduces the recipient's computed
    earned total.

    If the operator's stored total_earned also reflects the reduction (i.e.,
    both see a payment of 500 minus a return of -100 = net 400), both sides
    agree → PASS.  The asymmetry in how negative amounts are handled across
    event types is undocumented and inconsistent.
    """
    events = [
        {"type": "payment", "recipient": "Nina@claude", "agent": "Nina@claude", "amount": 500},
        # Negative escrow_return — not guarded; subtracts from earned
        {"type": "escrow_return", "recipient": "Nina@claude", "amount": -100},
    ]
    stored_agents = {
        # Operator also applied the subtraction: 500 + (-100) = 400
        "Nina@claude": {"balance": 400, "total_earned": 400},
    }

    computed = compute_total_earned(events)

    # -100 escrow_return is applied: 500 + (-100) = 400
    assert computed.get("Nina@claude", 0) == 400, (
        "Negative escrow_return (-100) is not guarded — subtracts from earned."
    )

    status, divergences, _, _ = check_consistency(stored_agents, computed)

    assert status == "PASS", (
        "Checker says PASS.  Both sides agree on 400 because neither guards "
        "against negative escrow_return amounts."
    )
    assert divergences == []


# ---------------------------------------------------------------------------
# Test 11 — agent0@system excluded → uninspected relay through agent0
# ---------------------------------------------------------------------------


def test_agent0_exclusion_allows_uninspected_escrow_relay() -> None:
    """Bypass vector: agent0@system is excluded from divergence reporting,
    making it an unmonitored relay for credit injection.

    The checker skips agent0 by design (_SKIP_AGENTS).  Any escrow_return
    routed through agent0's funds is never cross-checked.  A beneficiary's
    credit is only validated against stored total_earned on the beneficiary's
    side — agent0's corresponding debit is never audited.

    Scenario: agent0 returns 9999 WEA to Oscar@claude.  Oscar's credit matches
    stored → PASS.  agent0's total_earned stored value is stale/wrong, but the
    exclusion rule means it is never flagged.
    """
    events = [
        # Escrow_return from agent0's funds to Oscar — no create validation
        {
            "type": "escrow_return",
            "recipient": "Oscar@claude",
            "amount": 9999,
        },
    ]
    stored_agents = {
        "agent0@system": {
            "balance": 10000,
            "total_earned": 0,  # wrong — agent0 spent WEA via this return
        },
        "Oscar@claude": {
            "balance": 9999,
            "total_earned": 9999,
        },
    }

    computed = compute_total_earned(events)

    assert computed.get("Oscar@claude", 0) == 9999
    # agent0 not in computed (no earned events for agent0)

    status, divergences, _, _ = check_consistency(stored_agents, computed)

    # agent0's stored vs computed divergence is never checked
    agent0_divs = [d for d in divergences if d["agent"] == "agent0@system"]
    assert agent0_divs == [], "agent0 is excluded from divergence checks by design."

    # Oscar's credit matches stored → no divergence for Oscar
    oscar_divs = [d for d in divergences if d["agent"] == "Oscar@claude"]
    assert oscar_divs == []

    assert status == "PASS", (
        "Checker says PASS.  agent0's exclusion lets it act as an unmonitored "
        "relay — a 9999 WEA return with no source audit passes undetected."
    )


# ---------------------------------------------------------------------------
# Test 12 — trajectory_mint multi-agent ignores top-level amount field
# ---------------------------------------------------------------------------


def test_trajectory_mint_multi_agent_ignores_top_level_amount() -> None:
    """Bypass vector: in multi-agent format, the top-level 'amount' field is
    ignored entirely — only per_agent values are used.

    When an 'agents' list is present, the script uses ``per_agent[i]`` for each
    slot.  The top-level 'amount' field (if any) is never read.  An event that
    reports a large top-level amount but tiny per_agent values will compute a
    much smaller earned total than the top-level amount suggests.

    If stored total_earned reflects the per_agent values (correct), both sides
    agree → PASS.  But an operator who reads only the top-level 'amount' when
    building stored values would set a much larger total → FAIL.  The test
    documents which reading the script uses (per_agent wins).

    This is also a false-PASS risk: if an operator inflates stored total_earned
    based on top-level amount and history has artificially small per_agent
    values, the checker will detect the divergence correctly.  But if the
    operator also reads per_agent, both agree on a tiny sum → PASS even if the
    intended payment was the large amount.
    """
    events = [
        {
            "type": "trajectory_mint",
            "agents": ["Pat@claude", "Quinn@codex"],
            "per_agent": [5, 5],      # very small actual credits
            "amount": 10000,           # large top-level amount — ignored
        }
    ]
    stored_agents = {
        # Correct stored values based on per_agent
        "Pat@claude":   {"balance": 5, "total_earned": 5},
        "Quinn@codex":  {"balance": 5, "total_earned": 5},
    }

    computed = compute_total_earned(events)

    assert computed.get("Pat@claude", 0) == 5, (
        "Multi-agent trajectory_mint uses per_agent values, not top-level amount."
    )
    assert computed.get("Quinn@codex", 0) == 5

    status, divergences, _, _ = check_consistency(stored_agents, computed)

    assert status == "PASS", (
        "Checker says PASS when stored values match per_agent.  The top-level "
        "amount=10000 is never read — only per_agent determines earned credit."
    )
    assert divergences == []
