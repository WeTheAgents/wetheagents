from __future__ import annotations

from .current_bdd_support import (
    activated_runtime,
    apply_event,
    lifecycle_event,
    modules,
    stage,
    submit_work,
)


def test_s_03b_work_revisions_stay_inside_one_child_contract() -> None:
    intake = modules()["intake"]
    first = stage(
        key="spec",
        depth="spec",
        mode="ranked",
        allocation_wea=5,
        payout_vector=[5],
    )
    second = stage(
        key="implement",
        depth="implement",
        mode="ranked",
        allocation_wea=5,
        payout_vector=[5],
        inputs=(intake.SelectedWorkInput("spec"),),
    )
    state = activated_runtime(plan_stages=(first, second), total_bank_wea=10)
    state, first_work, first_revision = submit_work(
        state,
        agent_id="agent-alpha",
        account_id="account-alpha",
        sequence=1,
    )
    state, same_work, second_revision = submit_work(
        state,
        agent_id="agent-alpha",
        account_id="account-alpha",
        sequence=2,
    )
    assert same_work == first_work
    state = apply_event(
        state,
        lifecycle_event(
            state,
            "mode_expiry",
            {
                "contract_id": modules()["lifecycle"]
                .project_runtime(state)
                .current_stage.contract.contract_id
            },
            sequence=11,
        ),
    )
    state = apply_event(
        state,
        lifecycle_event(
            state,
            "ranked_order",
            {
                "contract_id": modules()["lifecycle"]
                .project_runtime(state)
                .current_stage.contract.contract_id,
                "ordered_work_ids": [first_work],
                "selected_revision_id": second_revision,
            },
            sequence=12,
            actor_kind="author",
            actor_id="agent-author",
            actor_account_id="account-author",
        ),
    )
    projection = modules()["lifecycle"].project_runtime(state)
    assert projection.current_stage.stage_key == "implement"
    selected = projection.current_stage.contract.resolved_inputs[0]
    assert selected.revision_id == second_revision
    assert selected.work_id == first_work
    state, next_work, _ = submit_work(
        state,
        agent_id="agent-alpha",
        account_id="account-alpha",
        sequence=13,
    )
    assert next_work != first_work
    assert first_revision != second_revision
