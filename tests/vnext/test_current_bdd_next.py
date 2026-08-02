from __future__ import annotations

from .current_bdd_support import (
    activated_runtime,
    apply_event,
    assign_role,
    lifecycle_event,
    modules,
    stage,
    submit_work,
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
    assert action.plan_revision_id == state.activation.plan.plan_revision_id
    assert action.stage_key == "rank"
    assert action.depth == "explore"
    assert action.mode == "ranked"
    assert action.action == "submit eligible Work"
    assert action.boundary_at is not None
    assert action.role_id is None
    assert action.role_generation is None
    assert action.work_id is None
    assert action.control_group_id is None
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


def test_s_13_next_action_waits_for_flat_pod_expiry_after_birdie() -> None:
    flat_pod = stage(
        key="answers",
        depth="explore",
        mode="flat_pod",
        allocation_wea=3,
        payout_vector=[1, 1, 1],
        slots=3,
    )
    state = activated_runtime(plan_stages=(flat_pod,), total_bank_wea=3)
    state, identifier, _ = submit_work(
        state,
        agent_id="agent-alpha",
        account_id="account-alpha",
        sequence=1,
    )
    contract_id = (
        modules()["lifecycle"].project_runtime(state).current_stage.contract.contract_id
    )
    state = apply_event(
        state,
        lifecycle_event(
            state,
            "birdie",
            {"contract_id": contract_id, "work_id": identifier},
            sequence=2,
            actor_kind="author",
            actor_id="agent-author",
            actor_account_id="account-author",
        ),
    )
    before = state.state_hash
    projection = modules()["lifecycle"].project_runtime(state)

    for actor_id in ("agent-author", "agent-alpha"):
        action = modules()["lifecycle"].next_action(state, actor_id)
        assert action.action == "wait for Tide to apply mode expiry"
        assert action.boundary_at == projection.current_stage.birdie_at

    assert state.state_hash == before
    assert len(state.events) == 2
