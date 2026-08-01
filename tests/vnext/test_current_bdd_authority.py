from __future__ import annotations

from datetime import timedelta

import pytest

from .current_bdd_support import (
    activated_runtime,
    apply_event,
    decision,
    lifecycle_event,
    modules,
    record_decision,
    replace_decision,
    stage,
    state_with_plan,
)


def test_s_01c_lifecycle_event_cannot_predate_plan_activation() -> None:
    ranked = stage(
        key="rank",
        depth="explore",
        mode="ranked",
        allocation_wea=5,
        payout_vector=[5],
    )
    state = activated_runtime(plan_stages=(ranked,), total_bank_wea=5)
    before = state.state_hash
    event = lifecycle_event(
        state,
        "author_stop",
        {},
        sequence=1,
        actor_kind="author",
        actor_id="agent-author",
        actor_account_id="account-author",
        effective_at=state.activation.plan.activated_at - timedelta(microseconds=1),
    )

    with pytest.raises(modules()["intake"].PlanError, match="predates"):
        apply_event(state, event)

    assert state.state_hash == before
    assert modules()["lifecycle"].project_runtime(state).plan_status == "active"


def test_s_01c_non_author_cannot_approve_a_plan() -> None:
    intake = modules()["intake"]
    state, draft, _, plan = state_with_plan()
    valid = decision(plan)
    invalid = replace_decision(
        valid,
        author_agent_id="agent-reviewer",
        author_github_account_id="account-reviewer",
        author_binding_id="reviewer-binding",
    )
    before = state.state_hash

    with pytest.raises(intake.PlanError, match="author"):
        record_decision(state, draft, invalid)

    assert state.state_hash == before
    assert state.plans == state.escrows == state.contracts == state.tasks == ()


def test_s_01c_operator_or_agent0_cannot_replace_author_approval() -> None:
    intake = modules()["intake"]
    state, draft, _, plan = state_with_plan()
    valid = decision(plan)
    for account_id, agent_id, binding_id in (
        ("account-agent0", "agent0@system", "agent0-role-binding"),
        ("unknown-account", "operator@system", "unknown-binding"),
    ):
        invalid = replace_decision(
            valid,
            author_agent_id=agent_id,
            author_github_account_id=account_id,
            author_binding_id=binding_id,
        )
        with pytest.raises(intake.PlanError):
            record_decision(state, draft, invalid)

    assert state.plans == state.escrows == state.ledger == ()
