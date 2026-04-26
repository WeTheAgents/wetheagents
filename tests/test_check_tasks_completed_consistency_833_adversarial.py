"""Adversarial tests for scripts/check_tasks_completed_consistency.py — T2S38

Targets the T1S36 implementation (PR #831) which added:
  - ±5 tolerance: divergence only flagged when abs(stored - computed) > 5
  - tasks_created counter (via escrow_create author field)
  - compute_tasks_created() and check_consistency(... computed_created=...)

All tests are self-contained: in-memory event lists and stored-agent dicts
only.  No real ledger files are read.

Bypass vectors covered:
  1.  Tolerance boundary — exactly ±5 diff → PASS (boundary should pass)
  2.  Tolerance boundary — exactly ±6 diff → FAIL (just over boundary)
  3.  Rejection-heavy agent — reject events not counted, only payment/accept
  4.  Escrow-only agent — tasks_created from escrow_create; tasks_completed=0
  5.  History-only agent — warning not FAIL (confirmed with new API)
  6.  Negative divergence — stored > computed by >5 → FAIL
  7.  Zero-history agent — no events, stored=0 → PASS
  8.  Large ecosystem — 50 agents, only 1 with diff >5 → only that agent fails
  9.  tasks_created tolerance boundary — ±5 passes, ±6 fails
  10. escrow_create with missing author silently dropped → tasks_created undercount
  11. Tolerance boundary straddled: one field OK, other over threshold → FAIL
  12. Counter bypass — tasks_created = 0 but escrow_create events exist for author
"""

from __future__ import annotations

from scripts.check_tasks_completed_consistency import (
    check_consistency,
    compute_tasks_completed,
    compute_tasks_created,
)


# ---------------------------------------------------------------------------
# Test 1 — Tolerance boundary: exactly ±5 diff → PASS
# ---------------------------------------------------------------------------


def test_tolerance_boundary_exactly_five_passes() -> None:
    """Boundary: stored=10, computed=5 → diff=5, which is NOT > 5 → PASS.

    The tolerance guard uses strict inequality: abs(stored - computed) > _TOLERANCE.
    A diff of exactly 5 does NOT exceed the threshold, so no divergence is raised.
    This is an important boundary: an agent can drift by 5 completions without
    triggering any alarm.

    Attack scenario: an adversary manipulates exactly 5 task records,
    keeping the discrepancy at the tolerance boundary to stay invisible.
    """
    events = [
        {"type": "payment", "agent": "Alpha@claude", "amount": 10, "issue": i}
        for i in range(1, 6)  # 5 qualifying events → computed=5
    ]
    stored_agents = {
        "Alpha@claude": {"tasks_completed": 10, "tasks_created": 0},
    }

    computed_completed = compute_tasks_completed(events)
    computed_created = compute_tasks_created(events)

    assert computed_completed.get("Alpha@claude", 0) == 5

    status, divergences, _, _ = check_consistency(
        stored_agents, computed_completed, computed_created
    )

    assert status == "PASS", (
        "diff=5 is not > _TOLERANCE(5) — exactly at boundary, no divergence raised."
    )
    assert divergences == []


# ---------------------------------------------------------------------------
# Test 2 — Tolerance boundary: exactly ±6 diff → FAIL
# ---------------------------------------------------------------------------


def test_tolerance_boundary_six_over_fails() -> None:
    """Boundary: stored=10, computed=4 → diff=6 which IS > 5 → FAIL.

    One step past the tolerance threshold triggers a divergence.
    The diff=6 case must produce exactly one divergence for tasks_completed.
    """
    events = [
        {"type": "payment", "agent": "Beta@claude", "amount": 10, "issue": i}
        for i in range(1, 5)  # 4 qualifying events → computed=4
    ]
    stored_agents = {
        "Beta@claude": {"tasks_completed": 10, "tasks_created": 0},
    }

    computed_completed = compute_tasks_completed(events)
    computed_created = compute_tasks_created(events)

    assert computed_completed.get("Beta@claude", 0) == 4

    status, divergences, _, _ = check_consistency(
        stored_agents, computed_completed, computed_created
    )

    assert status == "FAIL", (
        "diff=6 exceeds _TOLERANCE(5) — must produce a divergence."
    )
    beta_divs = [d for d in divergences if d["agent"] == "Beta@claude"]
    assert len(beta_divs) == 1
    assert beta_divs[0]["field"] == "tasks_completed"
    assert beta_divs[0]["diff"] == 6


# ---------------------------------------------------------------------------
# Test 3 — Rejection-heavy agent: reject events not counted
# ---------------------------------------------------------------------------


def test_rejection_heavy_agent_only_accepted_payments_count() -> None:
    """Bypass vector: events with type 'reject' or 'rejection' carry no weight.

    compute_tasks_completed() filters on type in ('payment', 'accept') only.
    An agent with many rejection events and only a few actual payments should
    show a low tasks_completed count.

    Real scenario: an agent submits work repeatedly, gets rejected 9 times,
    and finally receives one payment.  If stored=10 (including rejections),
    the actual computed=1.  diff=9 > 5 → FAIL.

    This confirms the checker catches inflation caused by counting rejections
    as completions.
    """
    events = [
        # 9 reject events — must NOT contribute to tasks_completed
        {"type": "reject", "agent": "Gamma@claude", "amount": 0, "issue": i}
        for i in range(1, 10)
    ] + [
        # 1 real payment
        {"type": "payment", "agent": "Gamma@claude", "amount": 30, "issue": 10},
    ]
    stored_agents = {
        # stored=10 (operator incorrectly counted rejections)
        "Gamma@claude": {"tasks_completed": 10, "tasks_created": 0},
    }

    computed_completed = compute_tasks_completed(events)
    computed_created = compute_tasks_created(events)

    assert computed_completed.get("Gamma@claude", 0) == 1, (
        "Only the single payment event counts; 9 reject events are ignored."
    )

    status, divergences, _, _ = check_consistency(
        stored_agents, computed_completed, computed_created
    )

    assert status == "FAIL", (
        "stored=10 vs computed=1 → diff=9 > 5 → should FAIL."
    )
    gamma_divs = [d for d in divergences if d["agent"] == "Gamma@claude"]
    assert len(gamma_divs) == 1
    assert gamma_divs[0]["field"] == "tasks_completed"
    assert gamma_divs[0]["diff"] == 9


# ---------------------------------------------------------------------------
# Test 4 — Escrow-only agent: tasks_created from escrow_create, tasks_completed=0
# ---------------------------------------------------------------------------


def test_escrow_only_agent_tasks_created_match_tasks_completed_zero() -> None:
    """Design verification: an agent who authored many escrows but received no
    payments should show tasks_created matching their escrow_create count, and
    tasks_completed = 0.

    compute_tasks_created() counts escrow_create events where 'author' == agent_id.
    compute_tasks_completed() is unaffected by escrow events.

    If stored tasks_created=3 and 3 escrow_create events exist for that agent,
    diff=0 → PASS.  tasks_completed stored=0, computed=0 → diff=0 → PASS.
    """
    events = [
        {"type": "escrow_create", "author": "Delta@claude", "amount": 20, "issue": i}
        for i in range(1, 4)  # 3 escrow creates
    ]
    stored_agents = {
        "Delta@claude": {"tasks_completed": 0, "tasks_created": 3},
    }

    computed_completed = compute_tasks_completed(events)
    computed_created = compute_tasks_created(events)

    assert computed_completed.get("Delta@claude", 0) == 0, (
        "escrow_create events don't count toward tasks_completed."
    )
    assert computed_created.get("Delta@claude", 0) == 3

    status, divergences, _, _ = check_consistency(
        stored_agents, computed_completed, computed_created
    )

    assert status == "PASS"
    assert divergences == []


# ---------------------------------------------------------------------------
# Test 5 — History-only agent: warning not FAIL (new API)
# ---------------------------------------------------------------------------


def test_history_only_agent_is_warning_not_fail_new_api() -> None:
    """[CONFIRMED GAP] Agent in payment history but absent from balances.json
    produces a warning, not a divergence — confirmed with the new 3-arg API.

    This test exercises check_consistency() with all three arguments
    (computed_created is now explicit).  The gap behavior is unchanged in the
    T1S36 implementation: missing agents still go to warnings, not divergences.

    Attack scenario: deleting an agent from balances.json hides their task
    count behind a warning that can go unnoticed in PASS output.
    """
    events = [
        {"type": "payment", "agent": "Epsilon@claude", "amount": 30, "issue": 5},
        {"type": "payment", "agent": "Epsilon@claude", "amount": 20, "issue": 6},
    ]
    stored_agents: dict = {}  # Epsilon absent from balances.json

    computed_completed = compute_tasks_completed(events)
    computed_created = compute_tasks_created(events)

    assert computed_completed.get("Epsilon@claude", 0) == 2

    status, divergences, warnings, _ = check_consistency(
        stored_agents, computed_completed, computed_created
    )

    assert status == "PASS", (
        "History-only agents produce warnings only, not divergences → PASS."
    )
    assert divergences == []
    assert len(warnings) == 1
    assert warnings[0]["agent"] == "Epsilon@claude"


# ---------------------------------------------------------------------------
# Test 6 — Negative divergence: stored > computed by >5 → FAIL
# ---------------------------------------------------------------------------


def test_negative_divergence_stored_greater_than_computed_fails() -> None:
    """Boundary: stored=10, computed=3 → diff=7 > 5 → FAIL.

    The tolerance uses abs(), so both over-counting (stored > computed) and
    under-counting (computed > stored) are flagged at the same threshold.

    This test confirms the negative direction: when stored tasks_completed
    exceeds the computed value by more than 5, a divergence is raised.

    Real scenario: an operator manually inflated tasks_completed without
    corresponding payment events in history.
    """
    events = [
        {"type": "payment", "agent": "Zeta@claude", "amount": 10, "issue": i}
        for i in range(1, 4)  # 3 qualifying events → computed=3
    ]
    stored_agents = {
        "Zeta@claude": {"tasks_completed": 10, "tasks_created": 0},
    }

    computed_completed = compute_tasks_completed(events)
    computed_created = compute_tasks_created(events)

    assert computed_completed.get("Zeta@claude", 0) == 3

    status, divergences, _, _ = check_consistency(
        stored_agents, computed_completed, computed_created
    )

    assert status == "FAIL", (
        "stored=10, computed=3 → diff=7 > 5 → must FAIL."
    )
    zeta_divs = [d for d in divergences if d["agent"] == "Zeta@claude"]
    assert len(zeta_divs) == 1
    assert zeta_divs[0]["field"] == "tasks_completed"
    assert zeta_divs[0]["stored"] == 10
    assert zeta_divs[0]["computed"] == 3
    assert zeta_divs[0]["diff"] == 7


# ---------------------------------------------------------------------------
# Test 7 — Zero-history agent: no events → computed=0, stored=0 → PASS
# ---------------------------------------------------------------------------


def test_zero_history_agent_no_events_passes() -> None:
    """Zero-history boundary: agent registered in balances.json but no events
    in history.  Computed is 0 for both counters; stored is also 0 → PASS.

    This is the baseline for a newly registered agent who has not yet
    completed or created any tasks.  The checker must not falsely flag them.
    """
    events: list = []  # no history at all
    stored_agents = {
        "Eta@claude": {"tasks_completed": 0, "tasks_created": 0},
    }

    computed_completed = compute_tasks_completed(events)
    computed_created = compute_tasks_created(events)

    assert computed_completed.get("Eta@claude", 0) == 0
    assert computed_created.get("Eta@claude", 0) == 0

    status, divergences, _, _ = check_consistency(
        stored_agents, computed_completed, computed_created
    )

    assert status == "PASS"
    assert divergences == []


# ---------------------------------------------------------------------------
# Test 8 — Large ecosystem: 50 agents, only 1 with diff >5 → only that fails
# ---------------------------------------------------------------------------


def test_large_ecosystem_only_one_failing_agent_flagged() -> None:
    """Scale test: 50 agents with clean counts, 1 agent with diff=8 > 5.

    Only the single offending agent should appear in divergences.  All 49
    clean agents must remain at PASS level.  The status must be FAIL because
    one divergence exists.

    This confirms the checker scales linearly and does not contaminate clean
    agents when one fails.
    """
    events: list = []
    stored_agents: dict = {}

    # 49 clean agents: computed=5, stored=5 → diff=0
    for i in range(1, 50):
        agent_id = f"Clean-{i:02d}@claude"
        for issue in range(i * 100, i * 100 + 5):
            events.append(
                {"type": "payment", "agent": agent_id, "amount": 10, "issue": issue}
            )
        stored_agents[agent_id] = {"tasks_completed": 5, "tasks_created": 0}

    # 1 failing agent: computed=2, stored=10 → diff=8 > 5
    events.extend([
        {"type": "payment", "agent": "Rogue@claude", "amount": 10, "issue": 9901},
        {"type": "payment", "agent": "Rogue@claude", "amount": 10, "issue": 9902},
    ])
    stored_agents["Rogue@claude"] = {"tasks_completed": 10, "tasks_created": 0}

    computed_completed = compute_tasks_completed(events)
    computed_created = compute_tasks_created(events)

    assert computed_completed.get("Rogue@claude", 0) == 2
    assert len(computed_completed) == 50  # all 50 agents present

    status, divergences, _, _ = check_consistency(
        stored_agents, computed_completed, computed_created
    )

    assert status == "FAIL"
    assert len(divergences) == 1, (
        "Exactly 1 divergence — only the rogue agent, not the 49 clean ones."
    )
    assert divergences[0]["agent"] == "Rogue@claude"
    assert divergences[0]["diff"] == 8


# ---------------------------------------------------------------------------
# Test 9 — tasks_created tolerance: ±5 passes, ±6 fails
# ---------------------------------------------------------------------------


def test_tasks_created_tolerance_boundary() -> None:
    """Tolerance applies equally to tasks_created: diff=5 passes, diff=6 fails.

    compute_tasks_created() counts escrow_create events by author.
    check_consistency() applies the same _TOLERANCE=5 guard to tasks_created.

    Two sub-scenarios:
      A) stored_created=10, computed_created=5 → diff=5 → PASS
      B) stored_created=10, computed_created=4 → diff=6 → FAIL
    """
    # Scenario A — diff=5 → PASS
    events_a = [
        {"type": "escrow_create", "author": "Iota@claude", "amount": 20, "issue": i}
        for i in range(1, 6)
    ]
    stored_a = {"Iota@claude": {"tasks_completed": 0, "tasks_created": 10}}

    completed_a = compute_tasks_completed(events_a)
    created_a = compute_tasks_created(events_a)

    assert created_a.get("Iota@claude", 0) == 5

    status_a, divs_a, _, _ = check_consistency(stored_a, completed_a, created_a)

    assert status_a == "PASS", "tasks_created diff=5 should not exceed tolerance."
    assert divs_a == []

    # Scenario B — diff=6 → FAIL
    events_b = [
        {"type": "escrow_create", "author": "Kappa@claude", "amount": 20, "issue": i}
        for i in range(1, 5)  # 4 escrows
    ]
    stored_b = {"Kappa@claude": {"tasks_completed": 0, "tasks_created": 10}}

    completed_b = compute_tasks_completed(events_b)
    created_b = compute_tasks_created(events_b)

    assert created_b.get("Kappa@claude", 0) == 4

    status_b, divs_b, _, _ = check_consistency(stored_b, completed_b, created_b)

    assert status_b == "FAIL", "tasks_created diff=6 exceeds tolerance → FAIL."
    kappa_divs = [d for d in divs_b if d["agent"] == "Kappa@claude"]
    assert len(kappa_divs) == 1
    assert kappa_divs[0]["field"] == "tasks_created"
    assert kappa_divs[0]["diff"] == 6


# ---------------------------------------------------------------------------
# Test 10 — escrow_create with missing author silently dropped
# ---------------------------------------------------------------------------


def test_escrow_create_missing_author_not_counted() -> None:
    """Bypass vector: escrow_create events without a usable author field are
    silently dropped, causing tasks_created to be under-counted.

    compute_tasks_created() checks `if author:` (falsy guard).  Missing,
    empty, and null author values are all falsy — those escrow events vanish.

    If stored tasks_created=1 (only the well-formed escrow) and the history
    has 3 escrow_create events (1 good + 2 bad), computed=1 → diff=0 → PASS.
    The 2 author-less escrows are undetectable.

    Real violation: a bug in the escrow-creation path omits the author field.
    Tasks were created but are invisible to the tasks_created counter.
    """
    events = [
        # Well-formed
        {"type": "escrow_create", "author": "Lambda@claude", "amount": 20, "issue": 1},
        # Missing author key
        {"type": "escrow_create", "amount": 20, "issue": 2},
        # Empty string author
        {"type": "escrow_create", "author": "", "amount": 20, "issue": 3},
    ]
    stored_agents = {
        "Lambda@claude": {"tasks_completed": 0, "tasks_created": 1},
    }

    computed_completed = compute_tasks_completed(events)
    computed_created = compute_tasks_created(events)

    assert computed_created.get("Lambda@claude", 0) == 1, (
        "Only the well-formed escrow_create is counted — missing/empty author dropped."
    )

    status, divergences, _, _ = check_consistency(
        stored_agents, computed_completed, computed_created
    )

    assert status == "PASS", (
        "stored=1, computed=1 → diff=0 → PASS.  Author-less escrows invisible."
    )
    assert divergences == []


# ---------------------------------------------------------------------------
# Test 11 — One field OK, other over threshold → FAIL
# ---------------------------------------------------------------------------


def test_one_field_ok_other_over_threshold_fails() -> None:
    """Straddled divergence: tasks_completed within tolerance, tasks_created over.

    An agent can have tasks_completed perfectly matching history while their
    tasks_created is wildly off — the checker must catch the diverging field
    even when the other field is clean.

    stored_completed=5, computed_completed=3 → diff=2 ≤ 5 → no completed divergence
    stored_created=15,  computed_created=5  → diff=10 > 5 → created divergence → FAIL
    """
    events = [
        {"type": "payment", "agent": "Mu@claude", "amount": 10, "issue": i}
        for i in range(1, 4)  # 3 payments
    ] + [
        {"type": "escrow_create", "author": "Mu@claude", "amount": 20, "issue": j}
        for j in range(101, 106)  # 5 escrow creates
    ]
    stored_agents = {
        "Mu@claude": {"tasks_completed": 5, "tasks_created": 15},
    }

    computed_completed = compute_tasks_completed(events)
    computed_created = compute_tasks_created(events)

    assert computed_completed.get("Mu@claude", 0) == 3
    assert computed_created.get("Mu@claude", 0) == 5

    status, divergences, _, _ = check_consistency(
        stored_agents, computed_completed, computed_created
    )

    assert status == "FAIL"
    field_names = [d["field"] for d in divergences if d["agent"] == "Mu@claude"]
    assert "tasks_created" in field_names, (
        "tasks_created divergence (diff=10) must be flagged."
    )
    assert "tasks_completed" not in field_names, (
        "tasks_completed diff=2 is within tolerance — must not be flagged."
    )


# ---------------------------------------------------------------------------
# Test 12 — Counter bypass: tasks_created=0 stored but escrow_creates exist
# ---------------------------------------------------------------------------


def test_tasks_created_stored_zero_but_escrow_creates_exist_fails() -> None:
    """Bypass vector: stored tasks_created=0 while history has 8 escrow_creates.

    diff = abs(0 - 8) = 8 > 5 → should fail.

    An operator who omits tasks_created initialization allows an agent to
    create many tasks without the counter ever being checked correctly.
    Default stored=0 while the ledger shows real activity.
    """
    events = [
        {"type": "escrow_create", "author": "Nu@claude", "amount": 20, "issue": i}
        for i in range(201, 209)  # 8 escrow creates
    ]
    stored_agents = {
        "Nu@claude": {"tasks_completed": 0, "tasks_created": 0},
    }

    computed_completed = compute_tasks_completed(events)
    computed_created = compute_tasks_created(events)

    assert computed_created.get("Nu@claude", 0) == 8

    status, divergences, _, _ = check_consistency(
        stored_agents, computed_completed, computed_created
    )

    assert status == "FAIL", (
        "stored_created=0 vs computed_created=8 → diff=8 > 5 → FAIL."
    )
    nu_divs = [d for d in divergences if d["agent"] == "Nu@claude"]
    assert len(nu_divs) == 1
    assert nu_divs[0]["field"] == "tasks_created"
    assert nu_divs[0]["diff"] == 8
