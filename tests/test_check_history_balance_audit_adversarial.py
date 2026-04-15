"""Adversarial tests for scripts/check_history_balance_audit.py

Each test targets a specific bypass vector — ways the checker might silently
miss a real divergence or produce a false PASS.

All tests are self-contained: in-memory event lists and balances dicts only.
No real ledger files are read or written.

Bypass vectors covered:
  1. Unknown event type silently ignored → no divergence on unchecked credit
  2. Duplicate payment events → false PASS when stored also double-credits
  3. Net-zero history-only agent → all transactions skipped by audit
  4. Negative payment silently ignored → false PASS when stored also ignores it
  5. Case mismatch → inflates to TWO divergences instead of ONE real issue
  6. trajectory_mint to wrong-cased agent → stored agent unfairly flagged
  7. escrow_return without prior escrow_create → phantom credit passes audit
  8. per_agent shorter than agents → silent truncation passes if stored matches
  9. Two offsetting errors cancel out → false PASS despite two invalid events
 10. agent0 relay → non-zero credit passes with no source audit
"""

from __future__ import annotations

import pytest

from scripts.check_history_balance_audit import audit, compute_balances


# ---------------------------------------------------------------------------
# Test 1 — Unknown event type silently ignored
# ---------------------------------------------------------------------------


def test_unknown_event_type_silently_ignored_false_pass() -> None:
    """Bypass vector: unknown event type credited in history, silently discarded.

    The checker's event dispatch only handles known types. An event with type
    "airdrop" (or any unrecognised type) is completely ignored. If the operator
    ALSO chose not to apply this event to stored balances, both computed and
    stored end up at 0 → checker says PASS even though history contains an
    unapplied credit event. The audit never flags the existence of the unknown
    event — a real ledger operation could hide behind a novel type string.
    """
    events = [
        # Recognised event: Alice earns 100 WEA
        {"type": "payment", "agent": "Alice@claude", "amount": 100},
        # Unknown event: someone adds an "airdrop" of 50 to Bob — silently skipped
        {"type": "airdrop", "agent": "Bob@codex", "amount": 50},
    ]
    stored = {
        "Alice@claude": {"balance": 100},  # correct for the payment
        "Bob@codex": {"balance": 0},        # operator also ignored the airdrop
    }

    computed = compute_balances(events)

    # GAP: checker produces 0 for Bob because "airdrop" is not handled.
    assert computed.get("Bob@codex", 0) == 0, (
        "Unknown event types are silently dropped — 'airdrop' of 50 is invisible."
    )

    status, divergences, _ = audit(stored, computed)
    # False PASS: both computed=0 and stored=0 for Bob → no divergence reported.
    assert status == "PASS", (
        "Checker says PASS even though history contains an unprocessed 'airdrop' "
        "event. The unapplied credit is never flagged."
    )
    assert divergences == []


# ---------------------------------------------------------------------------
# Test 2 — Duplicate payment events → false PASS when stored double-credits
# ---------------------------------------------------------------------------


def test_duplicate_payment_false_pass_when_stored_double_credits() -> None:
    """Bypass vector: same payment event replayed twice, both copies processed.

    compute_balances() accumulates every event it encounters. If the same
    payment event appears twice in history (e.g., written to two separate
    .jsonl files), the agent is credited twice. When the stored balance ALSO
    reflects the double-credit (because the operator applied both events),
    the checker sees computed == stored → PASS. The real balance should be
    half of what both report. The checker has no deduplication mechanism.
    """
    payment_event = {"type": "payment", "agent": "Carol@claude", "amount": 50}

    # Same event appearing in history twice (simulates it being in two files)
    events = [payment_event, payment_event]

    stored = {
        "Carol@claude": {"balance": 100},  # operator also applied both copies
    }

    computed = compute_balances(events)

    # The checker double-counts: 50 + 50 = 100
    assert computed["Carol@claude"] == 100, (
        "Duplicate payment events are both processed, producing 100 instead of 50."
    )

    status, divergences, _ = audit(stored, computed)
    # False PASS: computed=100 matches stored=100, so no divergence.
    assert status == "PASS", (
        "Checker says PASS when stored balance also reflects the duplicate payment. "
        "The double-credit is undetectable if both sides are equally wrong."
    )
    assert divergences == []


# ---------------------------------------------------------------------------
# Test 3 — Net-zero history-only agent bypasses all audit checks
# ---------------------------------------------------------------------------


def test_net_zero_history_only_agent_skipped_entirely() -> None:
    """Bypass vector: history-only agent whose events net to zero is never checked.

    The audit function skips history-only agents where computed balance == 0
    (the condition is `if hist != 0`). An agent with a +100 payment followed by
    a -100 reversal nets to zero and is never mentioned in the audit output.
    Two real ledger transactions (totalling 200 WEA in absolute value) are
    completely invisible. A fraudulent payment + fraudulent reversal pair cannot
    be detected by this audit.
    """
    events = [
        {"type": "payment", "agent": "Dave@claude", "amount": 100},
        # Reversal of -100 nets Dave back to 0
        {"type": "reversal", "agent": "Dave@claude", "amount": -100},
    ]
    # Dave is NOT in stored_agents — he's a history-only agent
    stored: dict = {}

    computed = compute_balances(events)

    # Net balance is 0: payment +100, reversal -100
    assert computed.get("Dave@claude", 0) == 0, (
        "Net balance after payment and reversal should be zero."
    )

    status, divergences, _ = audit(stored, computed)
    # The checker skips Dave entirely because hist == 0
    assert status == "PASS", (
        "Checker says PASS and never reports Dave, even though two real "
        "transactions (worth 200 WEA total) occurred in history."
    )
    assert divergences == []


# ---------------------------------------------------------------------------
# Test 4 — Negative payment silently ignored → false PASS
# ---------------------------------------------------------------------------


def test_negative_payment_silently_ignored_false_pass() -> None:
    """Bypass vector: negative-amount payment in history is silently discarded.

    compute_balances() only processes payment events where amount > 0. A
    negative payment (e.g., a clawback or fraudulent refund) is completely
    ignored. If the operator's stored balance ALSO ignores the negative payment
    (stores the pre-refund value), computed and stored both show the same
    inflated balance → PASS. The negative payment is invisible to the audit —
    it cannot be used to detect a rogue refund attempt hidden in history.
    """
    events = [
        {"type": "payment", "agent": "Eve@claude", "amount": 200},
        # Negative payment: represents an attempted clawback — ignored by checker
        {"type": "payment", "agent": "Eve@claude", "amount": -75},
    ]
    stored = {
        # Operator also ignored the negative payment → stored reflects only +200
        "Eve@claude": {"balance": 200},
    }

    computed = compute_balances(events)

    # GAP: negative payment is discarded → computed shows 200, not 125
    assert computed["Eve@claude"] == 200, (
        "Negative payment (-75) is silently ignored; computed balance remains 200."
    )

    status, divergences, _ = audit(stored, computed)
    # False PASS: both sides show 200 because both ignored the negative event.
    assert status == "PASS", (
        "Checker says PASS despite a negative payment in history. "
        "A fraudulent clawback or refund attempt is undetectable."
    )
    assert divergences == []


# ---------------------------------------------------------------------------
# Test 5 — Case mismatch inflates to two divergences instead of one issue
# ---------------------------------------------------------------------------


def test_case_mismatch_inflates_divergence_count() -> None:
    """Bypass vector: agent name capitalisation mismatch creates two divergences.

    The checker uses exact string matching for agent IDs. If a history event
    uses "frank@claude" (lowercase) while balances.json stores "Frank@claude"
    (uppercase), the checker treats them as two distinct agents. This produces
    TWO divergences — one saying the stored agent is over-reported (stored=100,
    hist=0) and another saying a history-only ghost agent has 100 WEA. An
    operator debugging this output might dismiss it as a naming bug rather than
    a real discrepancy, or might add a zero-balance entry for the wrong-cased
    name to "fix" the audit, masking the real mis-payment.
    """
    events = [
        # History uses lowercase 'frank@claude'
        {"type": "payment", "agent": "frank@claude", "amount": 100},
    ]
    stored = {
        # balances.json uses proper-case 'Frank@claude'
        "Frank@claude": {"balance": 100},
    }

    computed = compute_balances(events)

    # Two different keys in computed
    assert computed.get("frank@claude", 0) == 100
    assert computed.get("Frank@claude", 0) == 0

    status, divergences, _ = audit(stored, computed)
    # Two divergences reported, not one: one for Frank (stored>hist) and one
    # for frank (hist-only, not in stored)
    assert status == "FAIL"
    agent_ids = {d["agent"] for d in divergences}
    assert "Frank@claude" in agent_ids, (
        "Stored agent 'Frank@claude' appears as divergence: hist=0, stored=100."
    )
    assert "frank@claude" in agent_ids, (
        "History-only 'frank@claude' appears as divergence: hist=100, stored=0."
    )
    assert len(divergences) == 2, (
        "Case mismatch produces two divergences; the checker cannot recognise "
        "that they refer to the same underlying agent."
    )


# ---------------------------------------------------------------------------
# Test 6 — trajectory_mint to wrong-cased agent → real agent incorrectly flagged
# ---------------------------------------------------------------------------


def test_trajectory_mint_wrong_case_flags_real_agent_as_diverged() -> None:
    """Bypass vector: trajectory_mint credits wrong-cased ID; stored agent diverges.

    When a trajectory_mint credits "claude-6@CLAUDE" (unexpected case) instead
    of the canonical "Claude-6@claude", the mint proceeds without error. The
    stored balance for "Claude-6@claude" gets flagged as over-stated (stored=32,
    hist=0) even though the operator correctly reflected the intended payment.
    The wrong-cased recipient ("claude-6@CLAUDE") is reported as a history-only
    agent with 32 WEA. The real effect: the canonical agent is falsely flagged
    as having an unexplained stored balance, while the wrong-cased entry looks
    like a phantom agent rather than a mis-keyed payment.
    """
    events = [
        {
            "type": "trajectory_mint",
            # Wrong case — does not match stored key
            "agents": ["claude-6@CLAUDE"],
            "per_agent": [32],
        }
    ]
    stored = {
        # Canonical stored key
        "Claude-6@claude": {"balance": 32},
    }

    computed = compute_balances(events)

    assert computed.get("claude-6@CLAUDE", 0) == 32
    assert computed.get("Claude-6@claude", 0) == 0

    status, divergences, _ = audit(stored, computed)
    assert status == "FAIL"

    # Canonical agent flagged as having unexplained stored balance
    canonical_divs = [d for d in divergences if d["agent"] == "Claude-6@claude"]
    assert len(canonical_divs) == 1
    assert canonical_divs[0]["stored_balance"] == 32
    assert canonical_divs[0]["history_balance"] == 0

    # Wrong-cased agent appears as history-only
    wrong_divs = [d for d in divergences if d["agent"] == "claude-6@CLAUDE"]
    assert len(wrong_divs) == 1
    assert wrong_divs[0]["history_balance"] == 32


# ---------------------------------------------------------------------------
# Test 7 — escrow_return without prior escrow_create passes audit
# ---------------------------------------------------------------------------


def test_escrow_return_without_escrow_create_passes_audit() -> None:
    """Bypass vector: escrow_return credits agent even with no prior escrow_create.

    compute_balances() applies escrow_return unconditionally — it does not
    verify that a matching escrow_create exists. A phantom escrow_return (one
    with no corresponding escrow) generates a credit out of thin air. If the
    operator's stored balance reflects this phantom credit, computed == stored
    → PASS. The checker cannot distinguish a legitimate escrow return from a
    fabricated one because it only replays arithmetic, not lifecycle constraints.
    """
    events = [
        # No escrow_create has ever been recorded for issue #999
        {"type": "escrow_return", "recipient": "Grace@claude", "amount": 150},
    ]
    stored = {
        # Operator applied the phantom return to stored balance
        "Grace@claude": {"balance": 150},
    }

    computed = compute_balances(events)
    assert computed["Grace@claude"] == 150, (
        "escrow_return credited 150 WEA with no prior escrow_create."
    )

    status, divergences, _ = audit(stored, computed)
    # False PASS: phantom credit is accepted because arithmetic matches.
    assert status == "PASS", (
        "Checker says PASS on a phantom escrow_return. Lifecycle validity "
        "(create → return) is not enforced."
    )
    assert divergences == []


# ---------------------------------------------------------------------------
# Test 8 — per_agent shorter than agents → silent truncation passes if stored matches
# ---------------------------------------------------------------------------


def test_trajectory_mint_truncated_per_agent_silent_underpayment() -> None:
    """Bypass vector: per_agent list shorter than agents silently omits last agent.

    When agents=[A, B, C] but per_agent=[10, 20], agent C receives 0 because
    the loop exits at `i < len(per_agent)`. If the operator's stored balance
    for C is also 0 (they processed the same truncated event), the audit reports
    PASS — the under-payment is invisible. The intended payment to C is neither
    in computed nor in stored, so the divergence that should exist between
    'intended 30 WEA' and 'received 0 WEA' is never surfaced.
    """
    events = [
        {
            "type": "trajectory_mint",
            "agents": ["Hank@claude", "Ivy@codex", "Jack@claude"],
            "per_agent": [10, 20],  # Jack is silently omitted (list too short)
        }
    ]
    stored = {
        "Hank@claude": {"balance": 10},
        "Ivy@codex":   {"balance": 20},
        "Jack@claude": {"balance": 0},   # operator also applied truncated mint
    }

    computed = compute_balances(events)

    assert computed.get("Hank@claude", 0) == 10
    assert computed.get("Ivy@codex", 0) == 20
    # Jack gets nothing due to truncation
    assert computed.get("Jack@claude", 0) == 0, (
        "Jack is omitted when per_agent is shorter than agents."
    )

    status, divergences, _ = audit(stored, computed)
    # False PASS: checker sees 0 == 0 for Jack and reports no divergence.
    assert status == "PASS", (
        "Checker says PASS even though Jack was supposed to receive payment. "
        "The truncation is consistent across history and stored, so it is "
        "entirely invisible to the arithmetic audit."
    )
    assert divergences == []


# ---------------------------------------------------------------------------
# Test 9 — Two offsetting errors cancel out → false PASS for same agent
# ---------------------------------------------------------------------------


def test_two_offsetting_errors_cancel_false_pass() -> None:
    """Bypass vector: a spurious credit and spurious debit for the same agent cancel.

    If history contains a fabricated +50 payment AND a fabricated -50
    escrow_create for the same agent (Kim@claude), the net effect is zero.
    The computed balance equals the value it would have without both events.
    If stored also reflects this net-zero manipulation, the checker says PASS
    despite two invalid events in the ledger. The checker cannot detect
    self-cancelling fraud because it only checks the final arithmetic sum.
    """
    events = [
        # Legitimate: Kim earned 100 WEA
        {"type": "payment", "agent": "Kim@claude", "amount": 100},
        # Spurious fabricated credit: +50 (should not exist)
        {"type": "payment", "agent": "Kim@claude", "amount": 50},
        # Spurious fabricated debit matching the fake credit: -50 (should not exist)
        {"type": "escrow_create", "author": "Kim@claude", "amount": 50},
    ]
    stored = {
        # Stored reflects 100 (net of 100 + 50 - 50 = 100)
        "Kim@claude": {"balance": 100},
    }

    computed = compute_balances(events)
    # Net: 100 + 50 - 50 = 100
    assert computed["Kim@claude"] == 100, (
        "Spurious +50 and -50 cancel; computed = 100, same as legitimate balance."
    )

    status, divergences, _ = audit(stored, computed)
    # False PASS: two invalid events cancel → checker cannot detect either one.
    assert status == "PASS", (
        "Checker says PASS despite two fabricated events. Self-cancelling "
        "fraud (a spurious credit + matching debit) is undetectable."
    )
    assert divergences == []


# ---------------------------------------------------------------------------
# Test 10 — agent0 relay: credits beneficiary with no source audit
# ---------------------------------------------------------------------------


def test_agent0_relay_injects_credit_without_source_audit() -> None:
    """Bypass vector: agent0 exclusion allows uninspected credit injection.

    agent0@system is excluded from divergence reporting by design. A history
    sequence of escrow_create from agent0 (debiting agent0, which is never
    audited) followed by escrow_return to a beneficiary credits that beneficiary.
    Even if the original escrow_create never existed in history and the return is
    entirely fabricated, the checker will only audit the beneficiary's side. If
    stored balance for the beneficiary reflects the credit, the checker says PASS.
    agent0's book never closes — any amount can be routed through it as a trusted
    relay without triggering a divergence.
    """
    events = [
        # No escrow_create for agent0 (no WEA was locked)
        # Phantom escrow_return to Leo: 500 WEA appears out of thin air
        {
            "type": "escrow_return",
            "recipient": "Leo@claude",
            "amount": 500,
        },
        # agent0's debit side (if it existed) would not be audited anyway
        {
            "type": "escrow_create",
            "author": "agent0@system",
            "amount": 500,
        },
    ]
    stored = {
        "agent0@system": {"balance": 9000},  # irrelevant; excluded from audit
        "Leo@claude":    {"balance": 500},    # reflects the phantom credit
    }

    computed = compute_balances(events)
    # Leo received 500 from the phantom return
    assert computed.get("Leo@claude", 0) == 500
    # agent0 shows -500 computed but is excluded from audit
    assert computed.get("agent0@system", 0) == -500

    status, divergences, _ = audit(stored, computed)
    # agent0 is excluded → its -500 vs stored 9000 divergence is never reported
    agent0_divs = [d for d in divergences if d["agent"] == "agent0@system"]
    assert agent0_divs == [], (
        "agent0@system is excluded from divergence checking by design."
    )

    # Leo's 500 matches stored → PASS for Leo
    leo_divs = [d for d in divergences if d["agent"] == "Leo@claude"]
    assert leo_divs == [], "Leo's phantom credit matches stored → no divergence."

    assert status == "PASS", (
        "Checker says PASS. Leo received 500 WEA with no audited source — "
        "the agent0 exclusion acts as an unmonitored relay."
    )
