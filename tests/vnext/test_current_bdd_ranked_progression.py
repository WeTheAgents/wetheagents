from __future__ import annotations

from .current_bdd_support import (
    activated_runtime,
    apply_event,
    lifecycle_event,
    modules,
    stage,
    submit_work,
)


def test_s_04a_ranked_underfill_pays_one_rank_and_materializes_next_child() -> None:
    intake = modules()["intake"]
    first = stage(
        key="options",
        depth="explore",
        mode="ranked",
        allocation_wea=100,
        payout_vector=[50, 30, 20],
    )
    second = stage(
        key="spec",
        depth="spec",
        mode="ranked",
        allocation_wea=10,
        payout_vector=[10],
        inputs=(intake.SelectedWorkInput("options"),),
    )
    state = activated_runtime(plan_stages=(first, second), total_bank_wea=110)
    state, identifier, revision = submit_work(
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
            state, "mode_expiry", {"contract_id": contract_id}, sequence=11
        ),
    )
    state = apply_event(
        state,
        lifecycle_event(
            state,
            "ranked_order",
            {
                "contract_id": contract_id,
                "ordered_work_ids": [identifier],
                "selected_revision_id": revision,
            },
            sequence=12,
            actor_kind="author",
            actor_id="agent-author",
            actor_account_id="account-author",
        ),
    )
    projection = modules()["lifecycle"].project_runtime(state)
    assert projection.balance("agent-alpha") == 50
    assert projection.balance("agent-author") == 140
    assert projection.escrow.paid_wea == 50
    assert projection.escrow.refunded_wea == 50
    assert projection.escrow.available_wea == 10
    assert projection.current_stage.stage_key == "spec"
    assert projection.current_stage.contract.resolved_inputs[0].revision_id == revision


def test_s_04a_ranked_progression_preserves_the_selected_eligible_revision() -> None:
    intake = modules()["intake"]
    first = stage(
        key="options",
        depth="explore",
        mode="ranked",
        allocation_wea=10,
        payout_vector=[10],
    )
    second = stage(
        key="spec",
        depth="spec",
        mode="ranked",
        allocation_wea=5,
        payout_vector=[5],
        inputs=(intake.SelectedWorkInput("options"),),
    )
    state = activated_runtime(plan_stages=(first, second), total_bank_wea=15)
    state, identifier, selected = submit_work(
        state,
        agent_id="agent-alpha",
        account_id="account-alpha",
        sequence=1,
        content="first eligible revision",
    )
    state, _, latest = submit_work(
        state,
        agent_id="agent-alpha",
        account_id="account-alpha",
        sequence=2,
        content="second eligible revision",
    )
    assert latest != selected
    contract_id = (
        modules()["lifecycle"].project_runtime(state).current_stage.contract.contract_id
    )
    state = apply_event(
        state,
        lifecycle_event(
            state, "mode_expiry", {"contract_id": contract_id}, sequence=11
        ),
    )
    state = apply_event(
        state,
        lifecycle_event(
            state,
            "ranked_order",
            {
                "contract_id": contract_id,
                "ordered_work_ids": [identifier],
                "selected_revision_id": selected,
            },
            sequence=12,
            actor_kind="author",
            actor_id="agent-author",
            actor_account_id="account-author",
        ),
    )

    projection = modules()["lifecycle"].project_runtime(state)
    assert projection.current_stage.stage_key == "spec"
    assert projection.current_stage.contract.resolved_inputs[0].revision_id == selected
