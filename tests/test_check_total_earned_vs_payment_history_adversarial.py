"""Adversarial tests for scripts/check_total_earned_vs_payment_history.py.

Each test names the specific bypass scenario and documents whether it is a
genuine BYPASS (the script accepts incorrect data silently) or DEFENDED (the
script correctly detects and flags the anomaly).

Real bug found during testing:
- ``test_phantom_mint_history_only_agent_is_warning_not_fail``: an agent that
  appears only in trajectory_mint history but is absent from balances.json
  generates only a WARNING, not a FAIL.  A corrupt or injected mint event for
  a non-existent agent is silently tolerated.  BYPASS.
"""

from __future__ import annotations

from scripts.check_total_earned_vs_payment_history import (
    check_consistency,
    compute_total_earned,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stored(total_earned: int = 0) -> dict[str, int]:
    return {"balance": total_earned, "total_earned": total_earned, "total_spent": 0}


# ---------------------------------------------------------------------------
# Boundary cases
# ---------------------------------------------------------------------------


def test_empty_events_stored_nonzero_shows_divergence() -> None:
    """DEFENDED: empty history with nonzero stored total_earned → divergence emitted.

    Bypass scenario: attacker wipes history hoping stored values pass unchecked.
    """
    events: list[dict] = []
    stored_agents = {"alice@claude": _stored(total_earned=50)}

    computed = compute_total_earned(events)
    status, divergences, warnings, _ = check_consistency(stored_agents, computed)

    assert status == "FAIL"
    assert len(divergences) == 1
    assert divergences[0]["agent"] == "alice@claude"
    assert divergences[0]["delta"] == -50  # computed − stored


def test_empty_events_stored_zero_passes() -> None:
    """DEFENDED: empty history with all-zero stored totals → clean PASS.

    Boundary: the zero-state is stable and correct.
    """
    events: list[dict] = []
    stored_agents = {"alice@claude": _stored(total_earned=0)}

    computed = compute_total_earned(events)
    status, divergences, warnings, _ = check_consistency(stored_agents, computed)

    assert status == "PASS"
    assert divergences == []


def test_zero_amount_accept_excluded() -> None:
    """DEFENDED: accept event with amount=0 is not counted toward earned.

    Boundary: zero amounts must not inflate totals; script guards with ``> 0``.
    """
    events = [{"type": "accept", "agent": "alice@claude", "amount": 0}]
    stored_agents = {"alice@claude": _stored(total_earned=0)}

    computed = compute_total_earned(events)
    assert computed.get("alice@claude", 0) == 0

    status, divergences, _, _ = check_consistency(stored_agents, computed)
    assert status == "PASS"


def test_negative_amount_accept_excluded() -> None:
    """DEFENDED: negative amount in accept event is silently excluded.

    Boundary: a crafted event with amount=-100 must not subtract from earned.
    """
    events = [{"type": "accept", "agent": "alice@claude", "amount": -100}]
    stored_agents = {"alice@claude": _stored(total_earned=0)}

    computed = compute_total_earned(events)
    assert computed.get("alice@claude", 0) == 0

    status, divergences, _, _ = check_consistency(stored_agents, computed)
    assert status == "PASS"


def test_zero_amount_trajectory_mint_excluded() -> None:
    """DEFENDED: trajectory_mint with per_agent=[0] does not credit the agent.

    Boundary: zero-amount mints are a no-op; script must not count them.
    """
    events = [
        {
            "type": "trajectory_mint",
            "agents": ["alice@claude"],
            "per_agent": [0],
        }
    ]
    stored_agents = {"alice@claude": _stored(total_earned=0)}

    computed = compute_total_earned(events)
    assert computed.get("alice@claude", 0) == 0

    status, divergences, _, _ = check_consistency(stored_agents, computed)
    assert status == "PASS"


# ---------------------------------------------------------------------------
# Format confusion (trajectory_mint has three historical formats)
# ---------------------------------------------------------------------------


def test_format_confusion_agents_list_takes_priority_over_agent_field() -> None:
    """DEFENDED: when both ``agents`` list and ``agent`` field are present, multi-agent
    format wins and ``agent`` field is ignored entirely.

    Confusion scenario: an event is formatted as multi-agent but also carries an
    ``agent`` field (e.g. from a copy-paste error or format migration).  The
    ``amount`` in ``agent`` field path does NOT double-credit.
    """
    events = [
        {
            "type": "trajectory_mint",
            "agents": ["alice@claude"],
            "per_agent": [30],
            "agent": "bob@claude",  # must be ignored
            "amount": 99,           # must be ignored (multi-agent path wins)
        }
    ]
    stored_agents = {
        "alice@claude": _stored(total_earned=30),
        "bob@claude": _stored(total_earned=0),
    }

    computed = compute_total_earned(events)
    assert computed.get("alice@claude", 0) == 30
    assert computed.get("bob@claude", 0) == 0

    status, divergences, _, _ = check_consistency(stored_agents, computed)
    assert status == "PASS"


def test_format_confusion_agents_list_takes_priority_over_to_field() -> None:
    """DEFENDED: when both ``agents`` list and ``to`` field are present, multi-agent
    format wins and ``to`` field is silently ignored.

    Confusion scenario: an older event carries a ``to`` field alongside a new-style
    ``agents`` list, potentially causing double-crediting if both paths ran.
    """
    events = [
        {
            "type": "trajectory_mint",
            "agents": ["alice@claude"],
            "per_agent": [20],
            "to": "carol@claude",   # must be ignored
            "amount": 20,
        }
    ]
    stored_agents = {
        "alice@claude": _stored(total_earned=20),
        "carol@claude": _stored(total_earned=0),
    }

    computed = compute_total_earned(events)
    assert computed.get("alice@claude", 0) == 20
    assert computed.get("carol@claude", 0) == 0

    status, divergences, _, _ = check_consistency(stored_agents, computed)
    assert status == "PASS"


def test_format_confusion_empty_agents_list_falls_to_single_agent() -> None:
    """DEFENDED: ``agents: []`` (empty list) is falsy → single-agent path runs via
    ``agent`` field.

    Confusion scenario: an event with an explicit but empty ``agents`` list should
    NOT suppress the single-agent fallback.  The script correctly falls through.
    """
    events = [
        {
            "type": "trajectory_mint",
            "agents": [],           # empty list → falsy → falls to single-agent path
            "per_agent": [50],      # ignored in single-agent path
            "agent": "alice@claude",
            "amount": 40,
        }
    ]
    stored_agents = {"alice@claude": _stored(total_earned=40)}

    computed = compute_total_earned(events)
    assert computed.get("alice@claude", 0) == 40

    status, divergences, _, _ = check_consistency(stored_agents, computed)
    assert status == "PASS"


def test_format_confusion_to_field_used_when_no_agents_or_agent() -> None:
    """DEFENDED: oldest format uses ``to`` field; script credits it correctly.

    Confusion scenario: script must not miss older heartbeat-era events that
    use ``to`` instead of ``agent``.
    """
    events = [
        {
            "type": "trajectory_mint",
            "to": "alice@claude",
            "amount": 35,
        }
    ]
    stored_agents = {"alice@claude": _stored(total_earned=35)}

    computed = compute_total_earned(events)
    assert computed.get("alice@claude", 0) == 35

    status, divergences, _, _ = check_consistency(stored_agents, computed)
    assert status == "PASS"


def test_format_confusion_float_amount_truncated_may_mismatch() -> None:
    """BYPASS (partial): ``amount`` stored as float is truncated by ``int()`` cast.

    If a history event records ``amount: 10.9`` and balances.json stores
    ``total_earned: 11`` (rounded), the computed value will be 10 (truncated),
    producing a false divergence of delta=-1.  The script does not round-trip
    faithfully for non-integer amounts.

    Real bug: float → int truncation silently changes the computed value.
    """
    events = [{"type": "payment", "agent": "alice@claude", "amount": 10.9}]

    computed = compute_total_earned(events)
    # int(10.9) == 10, not 11
    assert computed.get("alice@claude", 0) == 10

    stored_agents = {"alice@claude": _stored(total_earned=11)}
    status, divergences, _, _ = check_consistency(stored_agents, computed)

    # Stored says 11, computed says 10 → divergence
    assert status == "FAIL"
    assert divergences[0]["delta"] == -1  # computed − stored = 10 − 11


def test_format_confusion_string_amount_parsed_correctly() -> None:
    """DEFENDED: ``amount`` as a JSON string (e.g. ``"50"``) is converted by ``int()``.

    Format confusion: some event producers may emit amounts as strings.
    ``int("50")`` == 50 so the script handles this silently.
    """
    events = [{"type": "payment", "agent": "alice@claude", "amount": "50"}]
    stored_agents = {"alice@claude": _stored(total_earned=50)}

    computed = compute_total_earned(events)
    assert computed.get("alice@claude", 0) == 50

    status, divergences, _, _ = check_consistency(stored_agents, computed)
    assert status == "PASS"


# ---------------------------------------------------------------------------
# Agent aliasing
# ---------------------------------------------------------------------------


def test_agent_aliasing_case_sensitive_different_keys() -> None:
    """DEFENDED: agent IDs are case-sensitive; ``Alice@claude`` ≠ ``alice@claude``.

    Aliasing scenario: same agent signs events with mixed case.  The script
    treats them as different agents — the casing mismatch causes a divergence
    for the stored agent and a warning for the history-only variant.
    """
    events = [
        {"type": "payment", "agent": "Alice@claude", "amount": 50},  # uppercase A
    ]
    stored_agents = {
        "alice@claude": _stored(total_earned=50),  # lowercase a
    }

    computed = compute_total_earned(events)
    assert computed.get("Alice@claude", 0) == 50
    assert computed.get("alice@claude", 0) == 0

    status, divergences, warnings, _ = check_consistency(stored_agents, computed)
    # "alice@claude" stored=50, computed=0 → divergence
    assert status == "FAIL"
    assert any(d["agent"] == "alice@claude" for d in divergences)
    # "Alice@claude" in history only → warning
    assert any(w["agent"] == "Alice@claude" for w in warnings)


def test_agent_aliasing_trailing_space_treated_as_different_agent() -> None:
    """DEFENDED: ``"alice@claude "`` (trailing space) ≠ ``"alice@claude"``.

    Aliasing scenario: whitespace in agent IDs from malformed events creates a
    different dict key, causing a divergence for the clean-name stored agent.
    """
    events = [
        {"type": "accept", "agent": "alice@claude ", "amount": 30},  # trailing space
    ]
    stored_agents = {"alice@claude": _stored(total_earned=30)}

    computed = compute_total_earned(events)
    assert computed.get("alice@claude ", 0) == 30  # space variant credited
    assert computed.get("alice@claude", 0) == 0     # clean name gets nothing

    status, divergences, _, _ = check_consistency(stored_agents, computed)
    assert status == "FAIL"


# ---------------------------------------------------------------------------
# Phantom mints
# ---------------------------------------------------------------------------


def test_phantom_mint_history_only_agent_is_warning_not_fail() -> None:
    """BYPASS: agent present only in trajectory_mint history (not in balances.json)
    generates a WARNING, not a FAIL.

    Real bug (documented): an adversary who injects a mint event for an agent
    not in balances.json causes no divergence.  The check_consistency function
    classifies absent-but-computed agents as warnings and returns PASS.
    This means phantom earnings for off-ledger agents are silently tolerated.
    """
    events = [
        {
            "type": "trajectory_mint",
            "agents": ["phantom@attacker"],
            "per_agent": [999],
        }
    ]
    stored_agents: dict = {}  # phantom agent is NOT in stored ledger

    computed = compute_total_earned(events)
    assert computed.get("phantom@attacker", 0) == 999

    status, divergences, warnings, _ = check_consistency(stored_agents, computed)

    # BYPASS: status is PASS even though 999 WEA was credited in history
    assert status == "PASS"
    assert divergences == []
    assert any(w["agent"] == "phantom@attacker" for w in warnings)


def test_phantom_mint_no_recipient_field_silently_skipped() -> None:
    """DEFENDED: trajectory_mint with no ``agents``, ``agent``, or ``to`` field
    credits nobody and does not crash.

    Phantom scenario: a malformed or truncated event is silently dropped.
    """
    events = [
        {
            "type": "trajectory_mint",
            "amount": 100,
            # no agents, no agent, no to
        }
    ]
    stored_agents = {"alice@claude": _stored(total_earned=0)}

    computed = compute_total_earned(events)
    assert computed == {}

    status, divergences, _, _ = check_consistency(stored_agents, computed)
    assert status == "PASS"


# ---------------------------------------------------------------------------
# Partial history / undercounting
# ---------------------------------------------------------------------------


def test_partial_history_per_agent_shorter_than_agents_undercredits() -> None:
    """DEFENDED: when ``per_agent`` list is shorter than ``agents`` list, tail
    agents receive no credit → stored vs computed divergence is caught.

    Undercounting scenario: a bug or truncation in the mint event leaves some
    agents without credit.  The script correctly reports the shortfall.
    """
    events = [
        {
            "type": "trajectory_mint",
            "agents": ["alice@claude", "bob@claude", "carol@claude"],
            "per_agent": [20, 20],  # only 2 entries for 3 agents → carol gets 0
        }
    ]
    stored_agents = {
        "alice@claude": _stored(total_earned=20),
        "bob@claude": _stored(total_earned=20),
        "carol@claude": _stored(total_earned=20),  # stored says 20, but history gives 0
    }

    computed = compute_total_earned(events)
    assert computed.get("carol@claude", 0) == 0  # tail agent missed

    status, divergences, _, _ = check_consistency(stored_agents, computed)
    assert status == "FAIL"
    assert any(d["agent"] == "carol@claude" for d in divergences)


def test_partial_history_empty_per_agent_credits_nobody() -> None:
    """DEFENDED: ``per_agent: []`` with a non-empty ``agents`` list credits no one.

    Undercounting scenario: the length guard ``i < len(per_agent)`` silently
    drops all agents when per_agent is empty.  Divergence is correctly reported.
    """
    events = [
        {
            "type": "trajectory_mint",
            "agents": ["alice@claude"],
            "per_agent": [],  # empty → nobody credited
        }
    ]
    stored_agents = {"alice@claude": _stored(total_earned=25)}

    computed = compute_total_earned(events)
    assert computed.get("alice@claude", 0) == 0

    status, divergences, _, _ = check_consistency(stored_agents, computed)
    assert status == "FAIL"
    assert divergences[0]["agent"] == "alice@claude"


# ---------------------------------------------------------------------------
# Double-counting risk
# ---------------------------------------------------------------------------


def test_double_counting_same_agent_twice_in_agents_list() -> None:
    """DEFENDED: same agent appearing twice in ``agents`` list accumulates both
    per_agent entries, potentially double-counting if the stored value only
    reflects a single credit.

    Double-counting scenario: ``agents: [alice, alice]``, ``per_agent: [25, 25]``
    → computed = 50.  If stored total_earned = 25, the script correctly flags
    the divergence (it doesn't deduplicate the agents list).
    """
    events = [
        {
            "type": "trajectory_mint",
            "agents": ["alice@claude", "alice@claude"],
            "per_agent": [25, 25],
        }
    ]
    # Stored only reflects one credit (the intended single slot)
    stored_agents = {"alice@claude": _stored(total_earned=25)}

    computed = compute_total_earned(events)
    assert computed.get("alice@claude", 0) == 50  # both entries summed

    status, divergences, _, _ = check_consistency(stored_agents, computed)
    assert status == "FAIL"
    assert divergences[0]["delta"] == 25  # computed − stored = 50 − 25


def test_double_counting_accept_and_payment_both_counted() -> None:
    """DEFENDED: if the same reward appears as both an ``accept`` and a ``payment``
    event, both are summed in computed.  Divergence is flagged if stored only
    reflects one.

    Double-counting scenario: duplicate event types for the same payout.
    """
    events = [
        {"type": "accept", "agent": "alice@claude", "amount": 30},
        {"type": "payment", "agent": "alice@claude", "amount": 30},
    ]
    stored_agents = {"alice@claude": _stored(total_earned=30)}

    computed = compute_total_earned(events)
    assert computed.get("alice@claude", 0) == 60

    status, divergences, _, _ = check_consistency(stored_agents, computed)
    assert status == "FAIL"
    assert divergences[0]["delta"] == 30  # 60 − 30


# ---------------------------------------------------------------------------
# Exclusion and edge cases
# ---------------------------------------------------------------------------


def test_agent0_excluded_from_divergence_even_if_mismatch() -> None:
    """BYPASS (by design): ``agent0@system`` is unconditionally excluded from
    divergence reporting, even when stored and computed totals differ.

    Exclusion scenario: a corrupt or incorrect total_earned for agent0 in
    balances.json will never be flagged.  This is documented intentional
    behaviour to handle legacy accounting, but it is a blind spot.
    """
    events = [
        {"type": "payment", "agent": "agent0@system", "amount": 999},
    ]
    stored_agents = {
        "agent0@system": {
            "balance": 0,
            "total_earned": 0,  # deliberately wrong
            "total_spent": 0,
        }
    }

    computed = compute_total_earned(events)
    # agent0 IS counted in history computation
    assert computed.get("agent0@system", 0) == 999

    status, divergences, warnings, _ = check_consistency(stored_agents, computed)
    # BYPASS: no divergence emitted for agent0
    assert status == "PASS"
    assert divergences == []


def test_empty_string_agent_in_agents_list_generates_warning() -> None:
    """BYPASS (edge case): ``agents: [""]`` with a positive per_agent amount
    credits the empty-string agent key.  The empty string is not in _SKIP_AGENTS
    and not in stored_agents, so it generates a WARNING (not a divergence).

    This is a quirk where a malformed event produces observable but non-fatal
    ledger noise.  The script does not strip or validate agent IDs.
    """
    events = [
        {
            "type": "trajectory_mint",
            "agents": [""],         # empty string agent
            "per_agent": [50],
        }
    ]
    stored_agents: dict = {}

    computed = compute_total_earned(events)
    assert computed.get("", 0) == 50  # empty string credited

    status, divergences, warnings, _ = check_consistency(stored_agents, computed)
    # PASS with a warning for the "" agent
    assert status == "PASS"
    assert any(w["agent"] == "" for w in warnings)


def test_non_dict_stored_agent_entry_silently_skipped() -> None:
    """DEFENDED: if a stored_agents entry is not a dict (e.g. a plain integer),
    it is silently skipped without raising an exception.

    Corruption scenario: a manually edited balances.json with a non-dict agent
    value does not crash the script.
    """
    stored_agents: dict = {
        "alice@claude": _stored(total_earned=50),
        "corrupt@agent": 42,  # not a dict — should be silently skipped
    }
    events = [{"type": "payment", "agent": "alice@claude", "amount": 50}]

    computed = compute_total_earned(events)
    # Should not raise
    status, divergences, warnings, _ = check_consistency(stored_agents, computed)
    assert status == "PASS"
    # corrupt@agent not in divergences
    assert not any(d["agent"] == "corrupt@agent" for d in divergences)


def test_stored_agent_missing_total_earned_field_defaults_to_zero() -> None:
    """DEFENDED: stored agent entry with no ``total_earned`` field defaults to 0.

    Partial-record scenario: a newly added agent without total_earned is treated
    as 0.  If they have history events, a divergence is correctly reported.
    """
    events = [{"type": "payment", "agent": "alice@claude", "amount": 25}]
    stored_agents = {
        "alice@claude": {"balance": 25, "total_spent": 0}  # no total_earned key
    }

    computed = compute_total_earned(events)
    assert computed.get("alice@claude", 0) == 25

    status, divergences, _, _ = check_consistency(stored_agents, computed)
    assert status == "FAIL"
    assert divergences[0]["delta"] == 25  # computed 25 − stored 0


def test_multiple_history_files_accumulate_across_files() -> None:
    """DEFENDED: earnings from multiple events across a single in-memory batch
    accumulate correctly (simulates multiple .jsonl files worth of events).

    Partial history scenario: if a subset of events is fed, totals are undercount.
    The script processes all provided events faithfully.
    """
    events = [
        {"type": "payment", "agent": "alice@claude", "amount": 10},
        {"type": "accept", "agent": "alice@claude", "amount": 20},
        {
            "type": "trajectory_mint",
            "agents": ["alice@claude"],
            "per_agent": [15],
        },
    ]
    stored_agents = {"alice@claude": _stored(total_earned=45)}

    computed = compute_total_earned(events)
    assert computed.get("alice@claude", 0) == 45

    status, divergences, _, _ = check_consistency(stored_agents, computed)
    assert status == "PASS"


def test_unknown_event_type_silently_ignored() -> None:
    """DEFENDED: events with types other than accept/payment/trajectory_mint are
    silently ignored and do not affect computed totals.

    Bypass scenario: injecting a ``bonus`` or ``airdrop`` event type would not
    credit any agent — the script's whitelist approach is correct.
    """
    events = [
        {"type": "bonus", "agent": "alice@claude", "amount": 500},
        {"type": "airdrop", "agent": "alice@claude", "amount": 999},
        {"type": "payment", "agent": "alice@claude", "amount": 10},
    ]
    stored_agents = {"alice@claude": _stored(total_earned=10)}

    computed = compute_total_earned(events)
    assert computed.get("alice@claude", 0) == 10

    status, divergences, _, _ = check_consistency(stored_agents, computed)
    assert status == "PASS"
