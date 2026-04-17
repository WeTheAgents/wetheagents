"""Combined adversarial tests for scripts/check_balances_earned_consistency.py.

This suite consolidates the prior ``*_adversarial`` and ``*_redteam`` files
into one deduplicated set of bypass cases against the earned/spent consistency
checker. All tests are fully in-memory; no real ledger files are accessed.
"""

from __future__ import annotations

from scripts.check_balances_earned_consistency import (
    check_consistency,
    compute_earned_spent,
)


def _stored_agent(
    *,
    total_earned: int = 0,
    total_spent: int = 0,
    balance: int | None = None,
) -> dict[str, int]:
    if balance is None:
        balance = total_earned - total_spent
    return {
        "balance": balance,
        "total_earned": total_earned,
        "total_spent": total_spent,
    }


def test_history_only_agent_absent_from_stored_emits_warning_not_fail() -> None:
    events = [
        {"type": "payment", "agent": "alice@claude", "amount": 100},
    ]
    stored_agents: dict[str, dict[str, int]] = {}

    computed_earned, computed_spent = compute_earned_spent(events)
    status, divergences, warnings, _ = check_consistency(
        stored_agents, computed_earned, computed_spent
    )

    assert computed_earned.get("alice@claude", 0) == 100
    assert status == "PASS"
    assert divergences == []
    assert len(warnings) == 1
    assert warnings[0]["agent"] == "alice@claude"


def test_escrow_return_missing_issue_field_is_silently_dropped_false_pass() -> None:
    events = [
        {"type": "escrow_create", "author": "bob@claude", "issue": 42, "amount": 80},
        {"type": "escrow_return", "recipient": "bob@claude", "amount": 80},
    ]
    stored_agents = {
        "bob@claude": _stored_agent(total_earned=0, total_spent=80),
    }

    computed_earned, computed_spent = compute_earned_spent(events)
    status, divergences, warnings, _ = check_consistency(
        stored_agents, computed_earned, computed_spent
    )

    assert computed_earned.get("bob@claude", 0) == 0
    assert computed_spent.get("bob@claude", 0) == 80
    assert status == "PASS"
    assert divergences == []
    assert warnings == []


def test_unknown_event_type_silently_ignored_false_pass() -> None:
    events = [
        {"type": "payment", "agent": "carol@claude", "amount": 200},
        {"type": "bonus", "agent": "dave@claude", "amount": 75},
    ]
    stored_agents = {
        "carol@claude": _stored_agent(total_earned=200, total_spent=0, balance=200),
        "dave@claude": _stored_agent(total_earned=0, total_spent=0, balance=0),
    }

    computed_earned, computed_spent = compute_earned_spent(events)
    status, divergences, warnings, _ = check_consistency(
        stored_agents, computed_earned, computed_spent
    )

    assert computed_earned.get("dave@claude", 0) == 0
    assert computed_spent == {}
    assert status == "PASS"
    assert divergences == []
    assert warnings == []


def test_negative_accept_amount_silently_ignored_false_pass() -> None:
    events = [
        {"type": "accept", "agent": "eve@claude", "amount": 150},
        {"type": "accept", "agent": "eve@claude", "amount": -60},
    ]
    stored_agents = {
        "eve@claude": _stored_agent(total_earned=150, total_spent=0, balance=150),
    }

    computed_earned, computed_spent = compute_earned_spent(events)
    status, divergences, warnings, _ = check_consistency(
        stored_agents, computed_earned, computed_spent
    )

    assert computed_earned.get("eve@claude", 0) == 150
    assert computed_spent == {}
    assert status == "PASS"
    assert divergences == []
    assert warnings == []


def test_symmetric_corruption_inflated_history_and_stored_false_pass() -> None:
    events = [
        {"type": "payment", "agent": "frank@claude", "amount": 100},
        {"type": "payment", "agent": "frank@claude", "amount": 50},
    ]
    stored_agents = {
        "frank@claude": _stored_agent(total_earned=150, total_spent=0, balance=150),
    }

    computed_earned, computed_spent = compute_earned_spent(events)
    status, divergences, warnings, _ = check_consistency(
        stored_agents, computed_earned, computed_spent
    )

    assert computed_earned.get("frank@claude", 0) == 150
    assert computed_spent == {}
    assert status == "PASS"
    assert divergences == []
    assert warnings == []


def test_trajectory_mint_single_agent_empty_field_drops_credit() -> None:
    events = [
        {"type": "trajectory_mint", "agent": "", "amount": 40},
    ]
    stored_agents = {
        "grace@claude": _stored_agent(total_earned=0, total_spent=0, balance=0),
    }

    computed_earned, computed_spent = compute_earned_spent(events)
    status, divergences, warnings, _ = check_consistency(
        stored_agents, computed_earned, computed_spent
    )

    assert computed_earned.get("grace@claude", 0) == 0
    assert computed_spent == {}
    assert status == "PASS"
    assert divergences == []
    assert warnings == []


def test_escrow_return_empty_recipient_falls_back_to_author_false_pass() -> None:
    events = [
        {"type": "escrow_create", "author": "hank@claude", "issue": 7, "amount": 60},
        {
            "type": "escrow_return",
            "recipient": "",
            "author": "hank@claude",
            "issue": 7,
            "amount": 60,
        },
    ]
    stored_agents = {
        "hank@claude": _stored_agent(total_earned=60, total_spent=60, balance=0),
        "ivy@claude": _stored_agent(total_earned=0, total_spent=0, balance=0),
    }

    computed_earned, computed_spent = compute_earned_spent(events)
    status, divergences, warnings, _ = check_consistency(
        stored_agents, computed_earned, computed_spent
    )

    assert computed_earned.get("hank@claude", 0) == 60
    assert computed_earned.get("ivy@claude", 0) == 0
    assert computed_spent.get("hank@claude", 0) == 60
    assert status == "PASS"
    assert divergences == []
    assert warnings == []


def test_per_agent_shorter_than_agents_last_agent_silently_omitted() -> None:
    events = [
        {
            "type": "trajectory_mint",
            "agents": ["jack@claude", "kay@codex", "leo@claude"],
            "per_agent": [15, 25],
        }
    ]
    stored_agents = {
        "jack@claude": _stored_agent(total_earned=15, total_spent=0, balance=15),
        "kay@codex": _stored_agent(total_earned=25, total_spent=0, balance=25),
        "leo@claude": _stored_agent(total_earned=0, total_spent=0, balance=0),
    }

    computed_earned, computed_spent = compute_earned_spent(events)
    status, divergences, warnings, _ = check_consistency(
        stored_agents, computed_earned, computed_spent
    )

    assert computed_earned.get("jack@claude", 0) == 15
    assert computed_earned.get("kay@codex", 0) == 25
    assert computed_earned.get("leo@claude", 0) == 0
    assert computed_spent == {}
    assert status == "PASS"
    assert divergences == []
    assert warnings == []


def test_issue_none_wildcard_one_create_authorises_many_returns() -> None:
    events = [
        {"type": "escrow_create", "author": "mia@claude", "amount": 1},
        {"type": "escrow_return", "recipient": "mia@claude", "amount": 500},
        {"type": "escrow_return", "recipient": "mia@claude", "amount": 500},
        {"type": "escrow_return", "recipient": "mia@claude", "amount": 500},
    ]
    stored_agents = {
        "mia@claude": _stored_agent(total_earned=1500, total_spent=1, balance=1499),
    }

    computed_earned, computed_spent = compute_earned_spent(events)
    status, divergences, warnings, _ = check_consistency(
        stored_agents, computed_earned, computed_spent
    )

    assert computed_earned.get("mia@claude", 0) == 1500
    assert computed_spent.get("mia@claude", 0) == 1
    assert status == "PASS"
    assert divergences == []
    assert warnings == []


def test_agent0_exclusion_allows_uninspected_relay() -> None:
    events = [
        {
            "type": "escrow_create",
            "author": "agent0@system",
            "issue": 99,
            "amount": 9999,
        },
        {
            "type": "escrow_return",
            "recipient": "nina@claude",
            "issue": 99,
            "amount": 9999,
        },
    ]
    stored_agents = {
        "agent0@system": _stored_agent(total_earned=0, total_spent=0, balance=10000),
        "nina@claude": _stored_agent(total_earned=9999, total_spent=0, balance=9999),
    }

    computed_earned, computed_spent = compute_earned_spent(events)
    status, divergences, warnings, _ = check_consistency(
        stored_agents, computed_earned, computed_spent
    )

    assert computed_spent.get("agent0@system", 0) == 9999
    assert computed_earned.get("nina@claude", 0) == 9999
    assert all(d["agent"] != "agent0@system" for d in divergences)
    assert status == "PASS"
    assert divergences == []
    assert warnings == []


def test_escrow_return_issue_type_mismatch_skips_valid_return() -> None:
    events = [
        {"type": "escrow_create", "author": "olga@claude", "issue": 1, "amount": 100},
        {
            "type": "escrow_return",
            "recipient": "olga@claude",
            "issue": "1",
            "amount": 100,
        },
    ]
    stored_agents = {
        "olga@claude": _stored_agent(total_earned=0, total_spent=100, balance=-100),
    }

    computed_earned, computed_spent = compute_earned_spent(events)
    status, divergences, warnings, _ = check_consistency(
        stored_agents, computed_earned, computed_spent
    )

    assert computed_earned.get("olga@claude", 0) == 0
    assert computed_spent.get("olga@claude", 0) == 100
    assert status == "PASS"
    assert divergences == []
    assert warnings == []


def test_trajectory_mint_empty_agents_list_falls_back_to_single_agent_format() -> None:
    events = [
        {
            "type": "trajectory_mint",
            "agents": [],
            "agent": "piper@codex",
            "amount": 100,
        }
    ]
    stored_agents = {
        "piper@codex": _stored_agent(total_earned=100, total_spent=0, balance=100),
    }

    computed_earned, computed_spent = compute_earned_spent(events)
    status, divergences, warnings, _ = check_consistency(
        stored_agents, computed_earned, computed_spent
    )

    assert computed_earned.get("piper@codex", 0) == 100
    assert computed_spent == {}
    assert status == "PASS"
    assert divergences == []
    assert warnings == []


def test_negative_escrow_create_amount_counts_as_negative_spent() -> None:
    events = [
        {"type": "escrow_create", "author": "quinn@codex", "issue": 3, "amount": -500},
    ]
    stored_agents = {
        "quinn@codex": _stored_agent(total_earned=0, total_spent=-500, balance=500),
    }

    computed_earned, computed_spent = compute_earned_spent(events)
    status, divergences, warnings, _ = check_consistency(
        stored_agents, computed_earned, computed_spent
    )

    assert computed_earned.get("quinn@codex", 0) == 0
    assert computed_spent.get("quinn@codex", 0) == -500
    assert status == "PASS"
    assert divergences == []
    assert warnings == []
