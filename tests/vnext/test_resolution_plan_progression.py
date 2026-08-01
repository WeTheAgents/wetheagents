from __future__ import annotations

from .current_bdd_support import (
    activated_runtime,
    apply_event,
    lifecycle_event,
    modules,
    stage,
)


def test_s_65_missing_selector_pauses_without_creating_future_child() -> None:
    intake = modules()["intake"]
    first = stage(
        key="research",
        depth="explore",
        mode="frontier",
        allocation_wea=1,
        payout_vector=[1],
    )
    second = stage(
        key="spec",
        depth="spec",
        mode="ranked",
        allocation_wea=5,
        payout_vector=[5],
        inputs=(intake.SelectedWorkInput("research"),),
    )
    state = activated_runtime(plan_stages=(first, second), total_bank_wea=6)
    contract_id = (
        modules()["lifecycle"].project_runtime(state).current_stage.contract.contract_id
    )
    state = apply_event(
        state,
        lifecycle_event(
            state,
            "frontier_close",
            {"contract_id": contract_id, "selected_revision_id": None},
            sequence=1,
            actor_kind="author",
            actor_id="agent-author",
            actor_account_id="account-author",
        ),
    )
    projection = modules()["lifecycle"].project_runtime(state)
    assert projection.plan_status == "paused"
    assert len(projection.stages) == 1
    assert len(projection.tasks) == 1
    assert projection.current_task.status == "closed"
    assert projection.current_task.close_result == "completed"
    assert projection.escrow.paid_wea == 0
    assert projection.escrow.refunded_wea == 1
    assert projection.escrow.available_wea == 5
    assert projection.pauses[-1].kind == "progression_pause"
