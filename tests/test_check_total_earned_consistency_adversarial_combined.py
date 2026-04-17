"""Combined adversarial tests for scripts/check_total_earned_consistency.py.

This suite consolidates the prior ``*_redteam`` and ``*_adversarial`` files
into a single deduplicated set of attack cases against the total-earned
checker. The original unit tests in ``tests/test_check_total_earned_consistency.py``
remain untouched.

All tests are fully in-memory; no real ledger files are accessed.
"""

from __future__ import annotations

from scripts.check_total_earned_consistency import (
    _extract_objects,
    check_consistency,
    compute_total_earned,
)


def test_history_only_agent_absent_from_stored_emits_warning_not_fail() -> None:
    # GAP: agents present only in history produce warnings, not divergences.
    events = [
        {"type": "payment", "agent": "alice@claude", "amount": 120},
    ]
    stored_agents: dict = {}

    computed = compute_total_earned(events)

    assert computed.get("alice@claude", 0) == 120

    status, divergences, warnings, _ = check_consistency(stored_agents, computed)

    assert status == "PASS"
    assert divergences == []
    assert len(warnings) == 1
    assert warnings[0]["agent"] == "alice@claude"


def test_malformed_json_prefix_drops_valid_events_on_line() -> None:
    # GAP: invalid bytes at the start of a line cause _extract_objects() to
    # stop parsing and silently discard valid objects later on that line.
    corrupted_line = (
        'XGARBAGE{"type": "payment", "agent": "bob@claude", "amount": 200}'
    )

    objects = _extract_objects(corrupted_line)

    assert objects == []

    stored_agents = {
        "bob@claude": {"balance": 0, "total_earned": 0},
    }
    computed = compute_total_earned(objects)

    status, divergences, warnings, _ = check_consistency(stored_agents, computed)

    assert status == "PASS"
    assert divergences == []
    assert warnings == []


def test_noncanonical_event_type_is_ignored_false_pass() -> None:
    # BYPASS: a payment-like event with a noncanonical type string is silently
    # ignored, so matching stored metadata also passes.
    events = [
        {"type": "payment ", "agent": "carol@claude", "amount": 75},
    ]
    stored_agents = {
        "carol@claude": {"balance": 0, "total_earned": 0},
    }

    computed = compute_total_earned(events)
    status, divergences, warnings, _ = check_consistency(stored_agents, computed)

    assert computed.get("carol@claude", 0) == 0
    assert status == "PASS"
    assert divergences == []
    assert warnings == []


def test_duplicate_events_are_counted_twice_without_deduplication() -> None:
    # BYPASS: replay does not deduplicate duplicate ledger events, so a cloned
    # event with the same id can inflate both history and stored totals.
    events = [
        {"type": "payment", "agent": "dana@claude", "amount": 1000, "id": "tx1"},
        {"type": "payment", "agent": "dana@claude", "amount": 1000, "id": "tx1"},
    ]
    stored_agents = {
        "dana@claude": {"balance": 2000, "total_earned": 2000},
    }

    computed = compute_total_earned(events)
    status, divergences, warnings, _ = check_consistency(stored_agents, computed)

    assert computed.get("dana@claude", 0) == 2000
    assert status == "PASS"
    assert divergences == []
    assert warnings == []


def test_symmetric_corruption_inflated_history_and_stored_false_pass() -> None:
    # GAP: coordinated corruption of history and stored metadata is invisible
    # to an arithmetic consistency check.
    events = [
        {"type": "payment", "agent": "eve@claude", "amount": 100},
        {"type": "payment", "agent": "eve@claude", "amount": 999},
    ]
    stored_agents = {
        "eve@claude": {"balance": 1099, "total_earned": 1099},
    }

    computed = compute_total_earned(events)
    status, divergences, warnings, _ = check_consistency(stored_agents, computed)

    assert computed.get("eve@claude", 0) == 1099
    assert status == "PASS"
    assert divergences == []
    assert warnings == []


def test_non_dict_stored_agent_entry_bypasses_divergence_and_warning_checks() -> None:
    # BYPASS: a non-dict entry in stored_agents is skipped by divergence checks,
    # and its presence suppresses the history-only warning path.
    events = [
        {"type": "payment", "agent": "frank@claude", "amount": 1000},
    ]
    stored_agents = {
        "frank@claude": 1000,
    }

    computed = compute_total_earned(events)
    status, divergences, warnings, _ = check_consistency(stored_agents, computed)

    assert computed.get("frank@claude", 0) == 1000
    assert status == "PASS"
    assert divergences == []
    assert warnings == []


def test_trajectory_mint_negative_amount_not_guarded() -> None:
    # BYPASS: single-agent trajectory_mint applies negative amounts directly,
    # unlike payment/accept which require amount > 0.
    events = [
        {"type": "payment", "agent": "gina@claude", "amount": 200},
        {"type": "trajectory_mint", "agent": "gina@claude", "amount": -50},
    ]
    stored_agents = {
        "gina@claude": {"balance": 150, "total_earned": 150},
    }

    computed = compute_total_earned(events)
    status, divergences, warnings, _ = check_consistency(stored_agents, computed)

    assert computed.get("gina@claude", 0) == 150
    assert status == "PASS"
    assert divergences == []
    assert warnings == []


def test_trajectory_mint_agents_string_splats_per_character() -> None:
    # BYPASS: a string in the multi-agent agents field is iterated character by
    # character, so the intended agent never receives the credit.
    events = [
        {"type": "trajectory_mint", "agents": "hacker@platform", "per_agent": [1000]},
    ]
    stored_agents = {
        "hacker@platform": {"balance": 0, "total_earned": 0},
    }

    computed = compute_total_earned(events)
    status, divergences, warnings, _ = check_consistency(stored_agents, computed)

    assert computed.get("hacker@platform", 0) == 0
    assert status == "PASS"
    assert divergences == []
    assert len(warnings) == 1
    assert warnings[0]["agent"] == "h"


def test_per_agent_shorter_than_agents_last_agent_silently_omitted() -> None:
    # BYPASS: trailing agents receive nothing when per_agent is shorter than the
    # agents list, and matching stored totals make that omission pass.
    events = [
        {
            "type": "trajectory_mint",
            "agents": ["iris@claude", "jack@codex", "kate@claude"],
            "per_agent": [20, 30],
        }
    ]
    stored_agents = {
        "iris@claude": {"balance": 20, "total_earned": 20},
        "jack@codex": {"balance": 30, "total_earned": 30},
        "kate@claude": {"balance": 0, "total_earned": 0},
    }

    computed = compute_total_earned(events)
    status, divergences, warnings, _ = check_consistency(stored_agents, computed)

    assert computed.get("iris@claude", 0) == 20
    assert computed.get("jack@codex", 0) == 30
    assert computed.get("kate@claude", 0) == 0
    assert status == "PASS"
    assert divergences == []
    assert warnings == []


def test_trajectory_mint_single_agent_empty_field_drops_credit() -> None:
    # BYPASS: a falsy single-agent field causes a trajectory mint to become a
    # no-op without any warning.
    events = [
        {"type": "trajectory_mint", "agent": "", "amount": 55},
    ]
    stored_agents = {
        "leo@claude": {"balance": 0, "total_earned": 0},
    }

    computed = compute_total_earned(events)
    status, divergences, warnings, _ = check_consistency(stored_agents, computed)

    assert "leo@claude" not in computed
    assert status == "PASS"
    assert divergences == []
    assert warnings == []


def test_escrow_return_agent_fallback_credits_wrong_entity_false_pass() -> None:
    # BYPASS: escrow_return falls back from recipient to agent, which can credit
    # the wrong person when the event payload is malformed.
    events = [
        {"type": "escrow_return", "agent": "hank@claude", "amount": 80},
    ]
    stored_agents = {
        "hank@claude": {"balance": 80, "total_earned": 80},
        "grace@claude": {"balance": 0, "total_earned": 0},
    }

    computed = compute_total_earned(events)
    status, divergences, warnings, _ = check_consistency(stored_agents, computed)

    assert computed.get("hank@claude", 0) == 80
    assert computed.get("grace@claude", 0) == 0
    assert status == "PASS"
    assert divergences == []
    assert warnings == []


def test_escrow_return_without_escrow_create_still_counted() -> None:
    # BYPASS: every escrow_return counts as income in this checker, even when
    # there is no corroborating escrow_create anywhere in history.
    events = [
        {"type": "escrow_return", "recipient": "mia@claude", "amount": 400},
    ]
    stored_agents = {
        "mia@claude": {"balance": 400, "total_earned": 400},
    }

    computed = compute_total_earned(events)
    status, divergences, warnings, _ = check_consistency(stored_agents, computed)

    assert computed.get("mia@claude", 0) == 400
    assert status == "PASS"
    assert divergences == []
    assert warnings == []


def test_escrow_return_negative_amount_subtracts_from_earned() -> None:
    # BYPASS: escrow_return has no amount > 0 guard, so negative values reduce
    # computed total_earned.
    events = [
        {"type": "payment", "agent": "nina@claude", "amount": 500},
        {"type": "escrow_return", "recipient": "nina@claude", "amount": -100},
    ]
    stored_agents = {
        "nina@claude": {"balance": 400, "total_earned": 400},
    }

    computed = compute_total_earned(events)
    status, divergences, warnings, _ = check_consistency(stored_agents, computed)

    assert computed.get("nina@claude", 0) == 400
    assert status == "PASS"
    assert divergences == []
    assert warnings == []


def test_agent0_exclusion_allows_uninspected_escrow_relay() -> None:
    # GAP: agent0@system is intentionally excluded from divergence reporting, so
    # relay-style accounting mismatches through agent0 are not surfaced.
    events = [
        {"type": "escrow_return", "recipient": "oscar@claude", "amount": 9999},
    ]
    stored_agents = {
        "agent0@system": {"balance": 10000, "total_earned": 0},
        "oscar@claude": {"balance": 9999, "total_earned": 9999},
    }

    computed = compute_total_earned(events)
    status, divergences, warnings, _ = check_consistency(stored_agents, computed)

    assert computed.get("oscar@claude", 0) == 9999
    assert all(d["agent"] != "agent0@system" for d in divergences)
    assert status == "PASS"
    assert warnings == []


def test_trajectory_mint_multi_agent_ignores_top_level_amount() -> None:
    # GAP: when agents[] is present, the top-level amount field is ignored and
    # only per_agent values determine earned credit.
    events = [
        {
            "type": "trajectory_mint",
            "agents": ["pat@claude", "quinn@codex"],
            "per_agent": [5, 5],
            "amount": 10000,
        }
    ]
    stored_agents = {
        "pat@claude": {"balance": 5, "total_earned": 5},
        "quinn@codex": {"balance": 5, "total_earned": 5},
    }

    computed = compute_total_earned(events)
    status, divergences, warnings, _ = check_consistency(stored_agents, computed)

    assert computed.get("pat@claude", 0) == 5
    assert computed.get("quinn@codex", 0) == 5
    assert status == "PASS"
    assert divergences == []
    assert warnings == []
