from __future__ import annotations

from .current_bdd_support import activated_runtime, assign_role, modules, stage


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
    assert state.state_hash == before
    assert state.events == ()

    state = assign_role(state, sequence=1)
    before = state.state_hash
    role_action = modules()["lifecycle"].next_action(state, "agent-alpha")
    assert role_action.action == "submit the complete assigned-role target set"
    assert state.state_hash == before
    assert len(state.events) == 1
