"""Adversarial tests for scripts/check_history_balance_flow.py (T2S25).

Each test constructs a synthetic history containing a subtle integrity violation
and asserts that the checker returns FAIL — not a silent PASS.

Coverage:
  (a) Negative mid-history balance — agent earns 100, spends 150, earns 50:
      terminal balance is 0 (matches balances.json) but the checker must still
      FAIL because the balance was negative at the mid-point escrow event.

  (b) trajectory_mint amount drift — history records a different per-agent
      amount than what balances.json (authoritative) says; the checker detects
      the discrepancy as a final-balance mismatch.

  (c) economy_reset baseline handling — reset clears pre-reset state and sets
      the correct baseline; post-reset events are tracked from zero, not from
      the pre-reset balance.

  (d) escrow_return_bulk multi-agent — multiple separate bulk-return events
      each crediting a different agent; the checker correctly accumulates all
      credits and detects if any are missing or over-stated.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.check_history_balance_flow import replay, run


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_ledger(root: Path, balances: dict, events: list[dict]) -> None:
    """Write balances.json and a single history file to a tmp root."""
    ledger = root / "ledger"
    ledger.mkdir(parents=True, exist_ok=True)
    (ledger / "balances.json").write_text(
        json.dumps({"version": 1, "agents": balances}), encoding="utf-8"
    )
    history = ledger / "history"
    history.mkdir(parents=True, exist_ok=True)
    (history / "2026-01-01.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events), encoding="utf-8"
    )


# ===========================================================================
# (a) Negative mid-history balance — terminal balance OK but violation exists
# ===========================================================================


def test_earn_100_spend_150_earn_50_fails(tmp_path: Path) -> None:
    """Exact pattern from spec: earn 100, spend 150, earn 50.

    Terminal balance = 0, matching balances.json.  A naive checker that only
    inspects final balances would silently PASS.  The correct checker must
    detect the negative balance after the escrow_create and FAIL.
    """
    _write_ledger(
        tmp_path,
        balances={"alice@claude": {"balance": 0}},
        events=[
            {"type": "payment", "agent": "alice@claude", "amount": 100, "timestamp": "2026-01-01T01:00:00Z"},
            # alice escrows 150 but only has 100 → goes negative mid-history
            {"type": "escrow_create", "agent": "alice@claude", "amount": 150, "issue": 10, "timestamp": "2026-01-01T02:00:00Z"},
            # later earns 50 — terminal balance is 100 - 150 + 50 = 0
            {"type": "payment", "agent": "alice@claude", "amount": 50, "timestamp": "2026-01-01T03:00:00Z"},
        ],
    )

    result, passed = run(tmp_path)

    assert passed is False, "checker must FAIL even when terminal balance is 0"
    assert result["status"] == "FAIL"
    violations = result["negative_violations"]
    assert len(violations) >= 1
    assert any(v["agent"] == "alice@claude" for v in violations)
    # The violation must record the balance at the escrow_create event: 100-150 = -50
    alice_violation = next(v for v in violations if v["agent"] == "alice@claude")
    assert alice_violation["balance"] == -50


def test_gradual_overdraft_then_recovery_fails(tmp_path: Path) -> None:
    """Multiple escrow debits that gradually push balance negative.

    Agent earns 200, then makes two escrows of 120 and 100 — the second one
    crosses into negative territory.  A subsequent payment restores balance to
    80, which matches balances.json.  The mid-history negative must be caught.
    """
    _write_ledger(
        tmp_path,
        balances={"bob@codex": {"balance": 80}},
        events=[
            {"type": "payment", "agent": "bob@codex", "amount": 200, "timestamp": "2026-01-01T01:00:00Z"},
            {"type": "escrow_create", "agent": "bob@codex", "amount": 120, "issue": 20, "timestamp": "2026-01-01T02:00:00Z"},
            # balance is 80 here — still fine
            {"type": "escrow_create", "agent": "bob@codex", "amount": 100, "issue": 21, "timestamp": "2026-01-01T03:00:00Z"},
            # balance is -20 here — VIOLATION
            {"type": "payment", "agent": "bob@codex", "amount": 100, "timestamp": "2026-01-01T04:00:00Z"},
            # balance is 80 — back to positive, matching balances.json
        ],
    )

    result, passed = run(tmp_path)

    assert passed is False
    assert result["status"] == "FAIL"
    assert any(v["agent"] == "bob@codex" for v in result["negative_violations"])
    bob_min = min(v["balance"] for v in result["negative_violations"] if v["agent"] == "bob@codex")
    assert bob_min == -20


def test_escrow_alone_creates_negative_and_is_recovered_fails(tmp_path: Path) -> None:
    """Escrow event (not escrow_create) also creates a negative mid-balance.

    The checker debits 'escrow' events identically to 'escrow_create'.
    Confirm both event types trigger negative violation detection.
    """
    _write_ledger(
        tmp_path,
        balances={"carol@gemini": {"balance": 0}},
        events=[
            {"type": "payment", "agent": "carol@gemini", "amount": 50, "timestamp": "2026-01-01T01:00:00Z"},
            # escrow (not escrow_create) of 80 — crosses into -30
            {"type": "escrow", "agent": "carol@gemini", "amount": 80, "issue": 30, "timestamp": "2026-01-01T02:00:00Z"},
            # earns 30 back — terminal balance 0, matches balances.json
            {"type": "payment", "agent": "carol@gemini", "amount": 30, "timestamp": "2026-01-01T03:00:00Z"},
        ],
    )

    result, passed = run(tmp_path)

    assert passed is False
    assert result["status"] == "FAIL"
    assert any(v["agent"] == "carol@gemini" for v in result["negative_violations"])


def test_multiple_agents_one_negative_fails(tmp_path: Path) -> None:
    """Only one agent goes negative; the other is clean.

    The checker must report the single violating agent and still FAIL overall,
    not silently average or mask the violation across agents.
    """
    _write_ledger(
        tmp_path,
        balances={
            "clean@claude": {"balance": 100},
            "dirty@codex": {"balance": 0},
        },
        events=[
            {"type": "payment", "agent": "clean@claude", "amount": 100, "timestamp": "2026-01-01T01:00:00Z"},
            {"type": "payment", "agent": "dirty@codex", "amount": 40, "timestamp": "2026-01-01T02:00:00Z"},
            # dirty goes negative here
            {"type": "escrow_create", "agent": "dirty@codex", "amount": 80, "issue": 5, "timestamp": "2026-01-01T03:00:00Z"},
            # recovered
            {"type": "payment", "agent": "dirty@codex", "amount": 40, "timestamp": "2026-01-01T04:00:00Z"},
        ],
    )

    result, passed = run(tmp_path)

    assert passed is False
    assert result["status"] == "FAIL"
    agents_violated = {v["agent"] for v in result["negative_violations"]}
    assert "dirty@codex" in agents_violated
    assert "clean@claude" not in agents_violated
    assert result["final_mismatches"] == []


# ===========================================================================
# (b) trajectory_mint amount drift
# ===========================================================================


def test_trajectory_mint_inflated_in_history_fails(tmp_path: Path) -> None:
    """History records 30 WEA for a trajectory_mint but balances.json says 25.

    This simulates a scenario where someone edits a history JSONL to claim a
    larger mint than was actually authorised by trajectory_mints.json.
    The final-balance mismatch must be detected.
    """
    _write_ledger(
        tmp_path,
        # balances.json reflects the authoritative 25 WEA from trajectory_mints.json
        balances={"alice@claude": {"balance": 25}},
        events=[
            # History records 30 — inflated vs the authorised 25
            {"type": "trajectory_mint", "agent": "alice@claude", "amount": 30,
             "trajectory": "T2", "slot": 5, "timestamp": "2026-01-01T01:00:00Z"},
        ],
    )

    result, passed = run(tmp_path)

    assert passed is False, "inflated trajectory_mint in history must trigger FAIL"
    assert result["status"] == "FAIL"
    assert result["negative_violations"] == []  # no negative balance
    mismatches = {m["agent"]: m for m in result["final_mismatches"]}
    assert "alice@claude" in mismatches
    m = mismatches["alice@claude"]
    # computed = 30 (from history), stored = 25 (from balances.json)
    assert m["computed"] == 30
    assert m["stored"] == 25
    assert m["delta"] == 5  # computed - stored


def test_trajectory_mint_deflated_in_history_fails(tmp_path: Path) -> None:
    """History records less than balances.json — under-stated trajectory_mint.

    If history was edited to reduce the recorded mint amount, the replay will
    compute a lower final balance than what balances.json holds.
    """
    _write_ledger(
        tmp_path,
        balances={"alice@claude": {"balance": 40}},
        events=[
            # History only records 20 — balances.json holds 40
            {"type": "trajectory_mint", "agent": "alice@claude", "amount": 20,
             "trajectory": "T1", "slot": 3, "timestamp": "2026-01-01T01:00:00Z"},
        ],
    )

    result, passed = run(tmp_path)

    assert passed is False
    assert result["status"] == "FAIL"
    mismatches = {m["agent"]: m for m in result["final_mismatches"]}
    assert "alice@claude" in mismatches
    assert mismatches["alice@claude"]["delta"] == -20  # computed 20 - stored 40


def test_trajectory_mint_list_format_per_agent_drift_fails(tmp_path: Path) -> None:
    """List-format trajectory_mint per_agent amounts drift from balances.json.

    The per_agent list credits [alice: 30, bob: 20] but authoritative ledger
    says [alice: 25, bob: 15].  Replay inflates both agents → FAIL.
    """
    _write_ledger(
        tmp_path,
        balances={
            "alice@claude": {"balance": 25},
            "bob@codex": {"balance": 15},
        },
        events=[
            {
                "type": "trajectory_mint",
                "agents": ["alice@claude", "bob@codex"],
                "per_agent": [30, 20],  # inflated vs authorised [25, 15]
                "amount": 50,
                "trajectory": "T3",
                "slot": 7,
                "timestamp": "2026-01-01T01:00:00Z",
            }
        ],
    )

    result, passed = run(tmp_path)

    assert passed is False
    assert result["status"] == "FAIL"
    mismatches = {m["agent"]: m for m in result["final_mismatches"]}
    assert "alice@claude" in mismatches
    assert "bob@codex" in mismatches
    assert mismatches["alice@claude"]["delta"] == 5   # 30 - 25
    assert mismatches["bob@codex"]["delta"] == 5     # 20 - 15


def test_trajectory_mint_credits_wrong_agent_fails(tmp_path: Path) -> None:
    """History records trajectory_mint crediting alice but balances.json shows bob.

    Simulates a history tampering scenario where an agent substitutes its ID.
    alice ends up over-counted; bob has zero computed balance vs non-zero stored.
    """
    _write_ledger(
        tmp_path,
        balances={
            "alice@claude": {"balance": 0},   # alice should have 0
            "bob@codex": {"balance": 25},      # bob should have 25
        },
        events=[
            # History mislabels bob's trajectory_mint as alice's
            {"type": "trajectory_mint", "agent": "alice@claude", "amount": 25,
             "trajectory": "T4", "slot": 2, "timestamp": "2026-01-01T01:00:00Z"},
        ],
    )

    result, passed = run(tmp_path)

    assert passed is False
    assert result["status"] == "FAIL"
    mismatches = {m["agent"]: m for m in result["final_mismatches"]}
    # alice: computed=25, stored=0 → delta=+25
    assert "alice@claude" in mismatches
    assert mismatches["alice@claude"]["computed"] == 25
    assert mismatches["alice@claude"]["stored"] == 0
    # bob: computed=0, stored=25 → delta=-25
    assert "bob@codex" in mismatches
    assert mismatches["bob@codex"]["computed"] == 0
    assert mismatches["bob@codex"]["stored"] == 25


# ===========================================================================
# (c) economy_reset baseline handling
# ===========================================================================


def test_economy_reset_post_reset_events_tracked_from_zero(tmp_path: Path) -> None:
    """Post-reset events are tracked from the zero baseline, not pre-reset.

    Pre-reset: alice earns 500.
    economy_reset: zeros alice.
    Post-reset: alice earns 100, escrows 30 → terminal = 70.
    balances.json says 70.  Must PASS.
    """
    _write_ledger(
        tmp_path,
        balances={"alice@claude": {"balance": 70}},
        events=[
            # pre-reset accumulation
            {"type": "payment", "agent": "alice@claude", "amount": 500, "timestamp": "2026-01-01T01:00:00Z"},
            # economy_reset zeros alice
            {
                "type": "economy_reset",
                "agents_zeroed": ["alice@claude"],
                "wea_returned_to_agent0": 500,
                "new_supply": 10000,
                "timestamp": "2026-01-01T02:00:00Z",
            },
            # post-reset: earn 100, escrow 30
            {"type": "payment", "agent": "alice@claude", "amount": 100, "timestamp": "2026-01-01T03:00:00Z"},
            {"type": "escrow_create", "agent": "alice@claude", "amount": 30, "issue": 50, "timestamp": "2026-01-01T04:00:00Z"},
        ],
    )

    result, passed = run(tmp_path)

    assert passed is True, "post-reset accounting must match balances.json: 70"
    assert result["status"] == "PASS"
    assert result["negative_violations"] == []
    assert result["final_mismatches"] == []


def test_economy_reset_post_reset_overspend_fails(tmp_path: Path) -> None:
    """Negative balance AFTER economy_reset must still be detected.

    Pre-reset violations are forgiven.  But a new negative created after the
    reset is a genuine violation and must cause FAIL.
    """
    _write_ledger(
        tmp_path,
        balances={"alice@claude": {"balance": 0}},
        events=[
            # pre-reset activity (goes negative — will be forgiven by reset)
            {"type": "payment", "agent": "alice@claude", "amount": 30, "timestamp": "2026-01-01T01:00:00Z"},
            {"type": "escrow_create", "agent": "alice@claude", "amount": 60, "issue": 5, "timestamp": "2026-01-01T02:00:00Z"},
            # economy_reset clears all — pre-reset negative forgiven
            {
                "type": "economy_reset",
                "agents_zeroed": ["alice@claude"],
                "wea_returned_to_agent0": 0,
                "new_supply": 10000,
                "timestamp": "2026-01-01T03:00:00Z",
            },
            # post-reset: earns 50, then escrows 80 → goes negative again (NOT forgiven)
            {"type": "payment", "agent": "alice@claude", "amount": 50, "timestamp": "2026-01-01T04:00:00Z"},
            {"type": "escrow_create", "agent": "alice@claude", "amount": 80, "issue": 6, "timestamp": "2026-01-01T05:00:00Z"},
            # earns back 30 — terminal = 0, matches balances.json
            {"type": "payment", "agent": "alice@claude", "amount": 30, "timestamp": "2026-01-01T06:00:00Z"},
        ],
    )

    result, passed = run(tmp_path)

    assert passed is False, "post-reset negative balance must not be silently passed"
    assert result["status"] == "FAIL"
    violations = result["negative_violations"]
    assert len(violations) >= 1, "post-reset violation must be reported"
    assert any(v["agent"] == "alice@claude" for v in violations)


def test_economy_reset_resets_events_counter(tmp_path: Path) -> None:
    """events_replayed counter is reset to 0 by economy_reset.

    Only events AFTER the reset are counted in events_replayed.
    """
    _write_ledger(
        tmp_path,
        balances={"alice@claude": {"balance": 50}},
        events=[
            # 2 events before reset
            {"type": "payment", "agent": "alice@claude", "amount": 100},
            {"type": "escrow_create", "agent": "alice@claude", "amount": 50, "issue": 1},
            # reset
            {
                "type": "economy_reset",
                "agents_zeroed": ["alice@claude"],
                "wea_returned_to_agent0": 50,
                "new_supply": 10000,
                "timestamp": "2026-01-01T02:00:00Z",
            },
            # 1 event after reset
            {"type": "payment", "agent": "alice@claude", "amount": 50},
        ],
    )

    result, passed = run(tmp_path)

    assert passed is True
    # Only post-reset events are counted (1 payment after reset)
    assert result["events_replayed"] == 1


def test_economy_reset_agent0_credit_tracked(tmp_path: Path) -> None:
    """wea_returned_to_agent0 from economy_reset credits agent0's balance.

    This confirms the reset's agent0 credit is accumulated and does not
    interfere with the per-agent final-balance checks (agent0 is always skipped).
    """
    _write_ledger(
        tmp_path,
        balances={"alice@claude": {"balance": 0}},
        events=[
            # alice had 300 WEA; reset returns them to agent0
            {"type": "payment", "agent": "alice@claude", "amount": 300},
            {
                "type": "economy_reset",
                "agents_zeroed": ["alice@claude"],
                "wea_returned_to_agent0": 300,
                "new_supply": 10000,
                "timestamp": "2026-01-01T01:00:00Z",
            },
        ],
    )

    result, passed = run(tmp_path)

    assert passed is True
    assert result["status"] == "PASS"
    assert result["final_mismatches"] == []


# ===========================================================================
# (d) escrow_return_bulk multi-agent crediting
# ===========================================================================


def test_escrow_return_bulk_two_agents_both_credited(tmp_path: Path) -> None:
    """Two separate escrow_return_bulk events, one per agent — both credited.

    The checker must accumulate each bulk-return event independently.
    """
    _write_ledger(
        tmp_path,
        balances={
            "alice@claude": {"balance": 80},   # 50 from payment + 30 from bulk return
            "bob@codex":   {"balance": 60},   # 40 from payment + 20 from bulk return
        },
        events=[
            {"type": "payment", "agent": "alice@claude", "amount": 50},
            {"type": "payment", "agent": "bob@codex", "amount": 40},
            # Separate bulk-return events for each agent (normal pattern)
            {"type": "escrow_return_bulk", "agent": "alice@claude", "amount": 30,
             "issues": [1, 2], "timestamp": "2026-01-01T03:00:00Z"},
            {"type": "escrow_return_bulk", "agent": "bob@codex", "amount": 20,
             "issues": [3], "timestamp": "2026-01-01T04:00:00Z"},
        ],
    )

    result, passed = run(tmp_path)

    assert passed is True
    assert result["status"] == "PASS"
    assert result["negative_violations"] == []
    assert result["final_mismatches"] == []


def test_escrow_return_bulk_missing_second_agent_fails(tmp_path: Path) -> None:
    """History only records bulk return for one agent; the second is omitted.

    This simulates a batch-return that was only partially written to history.
    The checker must detect the mismatch for the un-credited agent.
    """
    _write_ledger(
        tmp_path,
        balances={
            "alice@claude": {"balance": 80},
            "bob@codex":   {"balance": 60},  # bob should have gotten 20 from a bulk return
        },
        events=[
            {"type": "payment", "agent": "alice@claude", "amount": 50},
            {"type": "payment", "agent": "bob@codex", "amount": 40},
            # alice's bulk return is present
            {"type": "escrow_return_bulk", "agent": "alice@claude", "amount": 30,
             "issues": [1, 2], "timestamp": "2026-01-01T03:00:00Z"},
            # bob's bulk return is MISSING — history is incomplete
        ],
    )

    result, passed = run(tmp_path)

    assert passed is False, "missing bulk return for bob must trigger FAIL"
    assert result["status"] == "FAIL"
    mismatches = {m["agent"]: m for m in result["final_mismatches"]}
    assert "bob@codex" in mismatches
    # bob computed=40 (no bulk return), stored=60 (includes the 20 that was omitted)
    assert mismatches["bob@codex"]["computed"] == 40
    assert mismatches["bob@codex"]["stored"] == 60
    assert mismatches["bob@codex"]["delta"] == -20


def test_escrow_return_bulk_inflated_amount_fails(tmp_path: Path) -> None:
    """History records a larger bulk-return than what balances.json authorises.

    Adversarial: agent inflates the 'amount' field in a bulk-return event to
    claim more WEA.  The replay credits the inflated amount; balances.json
    reflects the authorised amount → FAIL.
    """
    _write_ledger(
        tmp_path,
        balances={"alice@claude": {"balance": 130}},  # 100 earned + 30 authorised return
        events=[
            {"type": "payment", "agent": "alice@claude", "amount": 100},
            # Inflated: claims 50 WEA returned but only 30 was authorised
            {"type": "escrow_return_bulk", "agent": "alice@claude", "amount": 50,
             "issues": [7, 8], "timestamp": "2026-01-01T02:00:00Z"},
        ],
    )

    result, passed = run(tmp_path)

    assert passed is False
    assert result["status"] == "FAIL"
    mismatches = {m["agent"]: m for m in result["final_mismatches"]}
    assert "alice@claude" in mismatches
    # computed=150, stored=130 → delta=+20
    assert mismatches["alice@claude"]["computed"] == 150
    assert mismatches["alice@claude"]["stored"] == 130
    assert mismatches["alice@claude"]["delta"] == 20


def test_escrow_return_bulk_recipient_field_takes_precedence(tmp_path: Path) -> None:
    """'recipient' field overrides 'agent' field in escrow_return_bulk.

    When both are present, 'recipient' must win.  If this is silently ignored
    and 'agent' wins, the wrong agent gets credited → final mismatch.
    """
    _write_ledger(
        tmp_path,
        balances={
            "recipient@claude": {"balance": 50},  # correct: recipient should get credited
            "agent@codex": {"balance": 0},          # agent field should NOT be used
        },
        events=[
            {
                "type": "escrow_return_bulk",
                "recipient": "recipient@claude",  # the authorised recipient
                "agent": "agent@codex",           # legacy field — must be overridden
                "amount": 50,
                "issues": [9],
                "timestamp": "2026-01-01T01:00:00Z",
            }
        ],
    )

    result, passed = run(tmp_path)

    assert passed is True, "recipient field must override agent field → correct credit"
    assert result["status"] == "PASS"
    assert result["final_mismatches"] == []


def test_escrow_return_bulk_three_agents_accumulates(tmp_path: Path) -> None:
    """Three separate escrow_return_bulk events for three agents all accumulate.

    Ensures the checker handles any number of bulk-return events in one
    history file without conflating or dropping credits.
    """
    _write_ledger(
        tmp_path,
        balances={
            "alpha@claude": {"balance": 110},  # 100 + 10
            "beta@codex":  {"balance": 225},  # 200 + 25
            "gamma@gemini": {"balance": 315},  # 300 + 15
        },
        events=[
            {"type": "payment", "agent": "alpha@claude", "amount": 100},
            {"type": "payment", "agent": "beta@codex", "amount": 200},
            {"type": "payment", "agent": "gamma@gemini", "amount": 300},
            {"type": "escrow_return_bulk", "agent": "alpha@claude", "amount": 10,
             "issues": [11], "timestamp": "2026-01-01T04:00:00Z"},
            {"type": "escrow_return_bulk", "agent": "beta@codex", "amount": 25,
             "issues": [12], "timestamp": "2026-01-01T05:00:00Z"},
            {"type": "escrow_return_bulk", "agent": "gamma@gemini", "amount": 15,
             "issues": [13], "timestamp": "2026-01-01T06:00:00Z"},
        ],
    )

    result, passed = run(tmp_path)

    assert passed is True
    assert result["status"] == "PASS"
    assert result["negative_violations"] == []
    assert result["final_mismatches"] == []
