"""Adversarial tests for scripts/check_per_agent_balance_floor.py

Each test targets a specific bypass vector — cases where the checker either:
  - Silently misses a real violation (GAP), or
  - Reports a violation that does not exist (FALSE POSITIVE).

All tests use in-memory event lists passed directly to replay() except Test 5,
which must exercise the file-loading path to test malformed JSON handling.

The eight required adversarial scenarios are defined below with docstrings that
state the bypass target and whether the checker currently FINDS or has a GAP.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.check_per_agent_balance_floor import _load_events, replay


# ---------------------------------------------------------------------------
# Test 1 — Unknown event type: balance understated, real violation missed
# ---------------------------------------------------------------------------


def test_unknown_event_type_silently_skipped_real_violation_missed() -> None:
    """Bypass target: unknown event type used as an off-ledger debit.

    The checker's else-branch silently discards any event whose type is not in
    its explicit allowlist. A future or custom event type that performs a real
    debit in the ledger (e.g. "custom_withdrawal") is completely invisible.

    Sequence:
      1. Alice earns 100 WEA via "payment".
      2. A "custom_withdrawal" of 150 WEA depletes her real balance to -50.
      3. Alice then escrows 10 WEA: checker sees 100 - 10 = 90 → PASS.
         Real balance: 100 - 150 - 10 = -60 → violation at step 2.

    Result: CHECKER HAS A GAP — reports PASS while a real floor violation
    occurred at the custom_withdrawal step.
    """
    events = [
        {
            "type": "payment",
            "agent": "alice@test",
            "amount": 100,
            "timestamp": "2026-01-01T00:00:00Z",
        },
        {
            # Unknown type: processed by the real ledger but invisible to checker.
            "type": "custom_withdrawal",
            "agent": "alice@test",
            "amount": 150,
            "timestamp": "2026-01-01T01:00:00Z",
        },
        {
            "type": "escrow_create",
            "agent": "alice@test",
            "amount": 10,
            "timestamp": "2026-01-01T02:00:00Z",
        },
    ]

    result = replay(events)

    # GAP: checker sees 100 - 10 = 90, reports PASS.
    # Real balance at step 2 was -50 (violation), but checker never knew.
    assert result["status"] == "PASS", (
        "Unknown event types are silently skipped — a real balance-floor "
        "violation caused by a custom_withdrawal is completely invisible."
    )
    assert result["violations"] == []


# ---------------------------------------------------------------------------
# Test 2 — Agent name case mismatch: false positive
# ---------------------------------------------------------------------------


def test_agent_name_case_mismatch_causes_false_positive() -> None:
    """Bypass target: credit under one case, debit under another.

    The checker stores balances by exact string key with no case normalization.
    A payment that credits "Alice@claude" and an escrow_create that debits
    "alice@claude" create TWO separate balance entries. The debit entry starts
    at 0 and immediately goes negative, triggering a false VIOLATION even though
    the single real agent's combined balance (100 - 50 = 50) is positive.

    Result: CHECKER HAS A FALSE POSITIVE — reports FAIL for "alice@claude"
    even though the agent (ignoring case) was never negative.
    """
    events = [
        {
            "type": "payment",
            "agent": "Alice@claude",   # capital A
            "amount": 100,
            "timestamp": "2026-01-01T00:00:00Z",
        },
        {
            "type": "escrow_create",
            "agent": "alice@claude",   # lowercase — same agent, different case
            "amount": 50,
            "timestamp": "2026-01-01T01:00:00Z",
        },
    ]

    result = replay(events)

    # FALSE POSITIVE: checker tracks "Alice@claude" (+100) and "alice@claude" (-50)
    # as independent agents. "alice@claude" never received the payment, so it goes
    # negative immediately.
    assert result["status"] == "FAIL"
    violating = {v["agent"] for v in result["violations"]}
    assert "alice@claude" in violating
    # The credited account is untouched (no violation there).
    assert "Alice@claude" not in violating


# ---------------------------------------------------------------------------
# Test 3 — escrow_create with amount=0: boundary, no false positive
# ---------------------------------------------------------------------------


def test_escrow_create_with_zero_amount_does_not_go_negative() -> None:
    """Bypass target: zero-amount debit at the balance floor boundary.

    An escrow_create with amount=0 subtracts 0 from the agent's balance.
    Starting at 0, the balance remains 0 — not negative. The checker must not
    treat this edge case as a floor violation.

    Result: CHECKER FINDS (correctly) — reports PASS. No false positive at the
    exact boundary of 0.
    """
    events = [
        {
            "type": "escrow_create",
            "agent": "alice@test",
            "amount": 0,
            "timestamp": "2026-01-01T00:00:00Z",
        },
    ]

    result = replay(events)

    assert result["status"] == "PASS"
    assert result["violations"] == []


# ---------------------------------------------------------------------------
# Test 4 — Payment to agent absent from initial balances: new agent mid-history
# ---------------------------------------------------------------------------


def test_payment_to_new_agent_not_in_initial_balances() -> None:
    """Bypass target: agent appears in history but was never bootstrapped.

    The checker initialises only agent0@system with a starting balance. All
    other agents are implicitly initialised to 0 via balances.get(a, 0).
    A brand-new agent receiving a payment mid-history should start at 0 and
    be correctly credited — no false positive.

    Result: CHECKER FINDS (correctly) — reports PASS. New agents are
    implicitly zero-initialized and can receive credits without violation.
    """
    events = [
        {
            "type": "payment",
            "agent": "brand_new@test",   # never seen before in history
            "amount": 75,
            "timestamp": "2026-01-01T00:00:00Z",
        },
        {
            "type": "escrow_create",
            "agent": "brand_new@test",
            "amount": 50,
            "timestamp": "2026-01-01T01:00:00Z",
        },
    ]

    result = replay(events)

    # brand_new starts at implicit 0, earns 75, spends 50 → balance 25. PASS.
    assert result["status"] == "PASS"
    assert result["violations"] == []


# ---------------------------------------------------------------------------
# Test 5 — Malformed JSON line in history file: graceful handling, no crash
# ---------------------------------------------------------------------------


def test_malformed_json_line_in_history_does_not_crash(tmp_path: Path) -> None:
    """Bypass target: injected non-JSON bytes in a .jsonl file.

    A history file containing a malformed line (not valid JSON) followed by
    a valid payment event must not crash the checker. The malformed line is
    silently skipped (json.JSONDecodeError caught in _load_events); the valid
    event is still processed.

    Result: CHECKER FINDS (correctly) — handles gracefully, processes the
    valid event, reports PASS. No unhandled exception.
    """
    history_dir = tmp_path / "ledger" / "history"
    history_dir.mkdir(parents=True)

    history_file = history_dir / "2026-01-01.jsonl"
    valid_event = json.dumps(
        {
            "type": "payment",
            "agent": "alice@test",
            "amount": 50,
            "timestamp": "2026-01-01T00:00:00Z",
        }
    )
    # Malformed line inserted before the valid event.
    history_file.write_text(
        "THIS IS NOT JSON\n" + valid_event + "\n",
        encoding="utf-8",
    )

    events = _load_events(history_dir)

    # Malformed line is skipped; only the valid event is loaded.
    assert len(events) == 1
    assert events[0]["type"] == "payment"

    result = replay(events)
    assert result["status"] == "PASS"
    assert result["violations"] == []


# ---------------------------------------------------------------------------
# Test 6 — Negative amount in payment event: false positive (credit as debit)
# ---------------------------------------------------------------------------


def test_negative_amount_payment_causes_false_positive() -> None:
    """Bypass target: a negative amount stored in a "payment" event.

    The checker unconditionally adds `amount` to the agent's balance for payment
    events: `balances[a] += amount`. A negative amount therefore debits the
    agent instead of crediting them.

    Scenario: Alice has a balance of 100, receives what should be a refund
    encoded as payment amount=-60. Real effect: her balance rises to 160.
    Checker effect: 100 + (-60) = 40 → still positive here, no violation.

    More direct scenario: alice starts at 0, a payment of -1 immediately
    drives her balance to -1 → FALSE POSITIVE violation.

    Result: CHECKER HAS A FALSE POSITIVE — interprets a negative-amount
    payment as a debit and reports a violation for the receiving agent.
    """
    events = [
        {
            # Negative amount in a payment (e.g. refund back to payer).
            # Checker does 0 + (-1) = -1 → violation.
            "type": "payment",
            "agent": "alice@test",
            "amount": -1,
            "timestamp": "2026-01-01T00:00:00Z",
        },
    ]

    result = replay(events)

    # FALSE POSITIVE: a negative-amount payment should credit (or at minimum not
    # be treated identically to a debit), but the checker drives the balance below
    # zero and reports FAIL.
    assert result["status"] == "FAIL"
    assert len(result["violations"]) == 1
    v = result["violations"][0]
    assert v["agent"] == "alice@test"
    assert v["balance_at_event"] == -1


# ---------------------------------------------------------------------------
# Test 7 — escrow_return before matching escrow_create: protocol violation missed
# ---------------------------------------------------------------------------


def test_escrow_return_before_escrow_create_protocol_violation_missed() -> None:
    """Bypass target: escrow_return referencing a non-existent escrow.

    The checker applies escrow_return as a pure credit with deduplication but
    without verifying that a matching escrow_create ever occurred. An
    escrow_return for an issue that was never escrowed inflates the agent's
    balance without a corresponding debit being tracked.

    Sequence:
      1. escrow_return of 50 for issue 99 — no prior escrow_create for issue 99.
      2. Alice's balance rises from 0 to 50 (no floor violation).
      3. Checker reports PASS — missing a protocol violation (return without create).

    Result: CHECKER HAS A GAP — a phantom escrow_return that inflates balances
    without a prior lock is silently accepted and not flagged.
    """
    events = [
        {
            "type": "escrow_return",
            "agent": "alice@test",
            "amount": 50,
            "issue": 99,
            "timestamp": "2026-01-01T00:00:00Z",
        },
        # No preceding escrow_create for issue 99.
    ]

    result = replay(events)

    # GAP: no matching escrow_create exists, yet the return is silently accepted.
    # Alice's balance is now 50 despite never having escrowed any WEA for issue 99.
    assert result["status"] == "PASS"
    assert result["violations"] == []


# ---------------------------------------------------------------------------
# Test 8 — Missing agent field in payment event: silent drop, orphan credit
# ---------------------------------------------------------------------------


def test_missing_agent_field_in_payment_silently_dropped() -> None:
    """Bypass target: payment event with neither "agent" nor "author" field.

    The checker resolves the recipient as `agent or author`. When both are
    absent (or empty), the resolved name is the empty string "". The condition
    `if a:` is then False, so the entire event is silently skipped — no credit
    is recorded, events_replayed is not incremented, and no error is raised.

    Consequence: if a subsequent escrow_create debits the agent who was intended
    to receive the payment, the checker sees them go negative (VIOLATION) even
    though the payment should have funded the escrow.

    Result: CHECKER HAS A GAP — the orphaned payment disappears without
    diagnostics. The downstream violation is detected (correct symptom), but
    the root cause (unattributed payment) is completely invisible.
    """
    events = [
        {
            # Payment intended for alice but agent field is absent.
            "type": "payment",
            "amount": 100,
            "issue": 42,
            "timestamp": "2026-01-01T00:00:00Z",
            # Deliberately omitting "agent" and "author".
        },
        {
            # Alice tries to spend, expecting the above payment to have credited her.
            "type": "escrow_create",
            "agent": "alice@test",
            "amount": 50,
            "timestamp": "2026-01-01T01:00:00Z",
        },
    ]

    result = replay(events)

    # The checker detects that alice went negative (downstream symptom).
    assert result["status"] == "FAIL"
    violating = {v["agent"] for v in result["violations"]}
    assert "alice@test" in violating

    # GAP: the orphaned payment event is silently discarded with no diagnostic.
    # events_replayed does not count it, so the summary understates activity.
    # The checker only sees the escrow violation — not that a payment was lost.
    assert "Replayed 1 balance events" in result["summary"], (
        "Only 1 event counted (the escrow_create); the orphaned payment "
        "was silently dropped and is not visible in the summary."
    )
