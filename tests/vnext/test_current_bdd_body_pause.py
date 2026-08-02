from __future__ import annotations

import pytest

from .current_bdd_support import (
    activated_runtime,
    apply_body_transition,
    apply_event,
    assign_role,
    author_event,
    body_transition_event,
    modules,
    resolve_role,
    stage,
    submit_role_result,
)


def test_s_02j_complete_pre_pause_role_result_keeps_frozen_outcome() -> None:
    ranked = stage(
        key="rank",
        depth="explore",
        mode="ranked",
        allocation_wea=5,
        payout_vector=[5],
    )
    state = activated_runtime(plan_stages=(ranked,), total_bank_wea=5)
    state = assign_role(
        state,
        funding="treasury",
        amount_wea=3,
        duration_seconds=600,
        sequence=1,
    )
    state = submit_role_result(state, sequence=2)
    state = apply_body_transition(
        state,
        "body_pause",
        body="Changed Issue body",
        sequence=3,
    )
    state = resolve_role(state, sequence=4)
    state = apply_event(state, author_event(state, "author_stop", {}, sequence=5))
    projection = modules()["lifecycle"].project_runtime(state)
    assert projection.roles[0].status == "completed"
    assert projection.balance("agent-alpha") == 3
    assert projection.escrow.refunded_wea == 5


def test_s_02j_next_action_surfaces_pre_pause_role_resolution() -> None:
    ranked = stage(
        key="rank",
        depth="explore",
        mode="ranked",
        allocation_wea=5,
        payout_vector=[5],
    )
    state = activated_runtime(plan_stages=(ranked,), total_bank_wea=5)
    state = assign_role(state, sequence=1)
    state = submit_role_result(state, sequence=2)
    state = apply_body_transition(
        state,
        "body_pause",
        body="Changed Issue body",
        sequence=3,
    )

    before = state.state_hash
    action = modules()["lifecycle"].next_action(state, "agent0@system")
    assert action.action == "resolve the complete timely assigned-role result"
    assert action.role_id == "review-role"
    assert action.role_generation == 1
    assert action.boundary_at is None
    author_action = modules()["lifecycle"].next_action(state, "agent-author")
    assert (
        author_action.action
        == "restore the exact Issue body or wait for Agent0 role resolution"
    )
    assert state.state_hash == before


def test_s_02j_new_or_partial_role_result_after_pause_changes_nothing() -> None:
    ranked = stage(
        key="rank",
        depth="explore",
        mode="ranked",
        allocation_wea=5,
        payout_vector=[5],
    )
    state = activated_runtime(plan_stages=(ranked,), total_bank_wea=5)
    state = assign_role(state, targets=("a", "b"), duration_seconds=600, sequence=1)
    state = submit_role_result(state, target_id="a", sequence=2)
    state = apply_body_transition(
        state,
        "body_pause",
        body="Changed Issue body",
        sequence=3,
    )
    before = state.state_hash
    with pytest.raises(modules()["intake"].PlanError, match="outside"):
        submit_role_result(state, target_id="b", sequence=4)
    assert state.state_hash == before
    stopped = apply_event(state, author_event(state, "author_stop", {}, sequence=5))
    projection = modules()["lifecycle"].project_runtime(stopped)
    assert projection.plan_status == "stopped"
    assert projection.roles[0].status == "stopped"


def test_s_02j_body_resume_requires_the_current_exact_contract_body() -> None:
    ranked = stage(
        key="rank",
        depth="explore",
        mode="ranked",
        allocation_wea=5,
        payout_vector=[5],
    )
    state = activated_runtime(plan_stages=(ranked,), total_bank_wea=5)
    invalid_pause, invalid_pause_evidence = body_transition_event(
        state,
        "body_pause",
        body=state.activation.draft.body,
        sequence=1,
    )
    before = state.state_hash
    with pytest.raises(modules()["intake"].PlanError, match="current changed"):
        apply_event(state, invalid_pause, evidence_state=invalid_pause_evidence)
    assert state.state_hash == before

    state = apply_body_transition(
        state,
        "body_pause",
        body="Changed Issue body",
        sequence=2,
    )
    invalid, invalid_evidence = body_transition_event(
        state,
        "body_resume",
        body="Still changed",
        sequence=3,
    )
    before = state.state_hash
    with pytest.raises(modules()["intake"].PlanError, match="current restored"):
        apply_event(state, invalid, evidence_state=invalid_evidence)
    assert state.state_hash == before

    resumed = apply_body_transition(
        state,
        "body_resume",
        body=state.activation.draft.body,
        sequence=4,
    )
    projection = modules()["lifecycle"].project_runtime(resumed)
    assert projection.plan_status == "active"
    assert projection.pauses[-1].ended_at is not None
