from __future__ import annotations

from .current_bdd_support import (
    activated_runtime,
    assign_role,
    modules,
    stage,
)


def test_s_13_next_action_is_exact_and_read_only() -> None:
    ranked = stage(
        key="rank",
        depth="explore",
        mode="ranked",
        allocation_wea=5,
        payout_vector=[5],
    )
    state = activated_runtime(plan_stages=(ranked,), total_bank_wea=5)
    before = state.state_hash
    action = modules()["lifecycle"].next_action(state, "agent-alpha")
    assert action.plan_id == state.activation.plan.plan_id
    assert action.stage_key == "rank"
    assert action.depth == "explore"
    assert action.mode == "ranked"
    assert action.action == "submit eligible Work"
    assert action.boundary_at is not None
    assert action.role_id is None
    assert action.role_generation is None
    assert state.state_hash == before
    assert state.events == ()

    state = assign_role(
        state,
        role_id="later-role",
        duration_seconds=900,
        sequence=1,
    )
    state = assign_role(
        state,
        role_id="urgent-z-role",
        duration_seconds=300,
        sequence=2,
    )
    state = assign_role(
        state,
        role_id="urgent-a-role",
        duration_seconds=240,
        sequence=3,
    )
    state = assign_role(
        state,
        role_id="urgent-a-role",
        generation=2,
        duration_seconds=180,
        sequence=4,
    )
    before = state.state_hash
    role_action = modules()["lifecycle"].next_action(state, "agent-alpha")
    assert role_action.action == "submit the complete assigned-role target set"
    assert role_action.role_id == "urgent-a-role"
    assert role_action.role_generation == 1
    assert role_action.boundary_at < next(
        item.effective_due_at
        for item in modules()["lifecycle"].project_runtime(state).roles
        if item.role_id == "later-role"
    )
    assert state.state_hash == before
    assert len(state.events) == 4
