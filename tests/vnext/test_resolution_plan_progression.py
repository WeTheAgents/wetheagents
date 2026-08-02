from __future__ import annotations

from .current_bdd_support import (
    accept_work,
    activated_runtime,
    apply_event,
    lifecycle_event,
    modules,
    stage,
    submit_work,
)


def test_s_64_full_frontier_waits_for_exact_selector_before_progression() -> None:
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
    state, work_id, revision_id = submit_work(
        state,
        agent_id="agent-alpha",
        account_id="account-alpha",
        sequence=1,
        snapshot={"model": "m1", "genome": "g1", "runtime": "r1"},
    )
    state = accept_work(
        state,
        work_id=work_id,
        revision_id=revision_id,
        sequence=2,
    )
    projection = modules()["lifecycle"].project_runtime(state)
    assert projection.plan_status == "active"
    assert projection.current_stage.stage_key == "research"
    assert projection.current_stage.status == "active"
    assert projection.current_stage.selected_revision_id is None
    assert projection.escrow.paid_wea == 1

    state = apply_event(
        state,
        lifecycle_event(
            state,
            "frontier_close",
            {
                "contract_id": projection.current_stage.contract.contract_id,
                "selected_revision_id": revision_id,
            },
            sequence=3,
            actor_kind="author",
            actor_id="agent-author",
            actor_account_id="account-author",
        ),
    )
    projection = modules()["lifecycle"].project_runtime(state)
    assert projection.plan_status == "active"
    assert projection.current_stage.stage_key == "spec"
    assert (
        projection.current_stage.contract.resolved_inputs[0].revision_id
        == revision_id
    )
    assert [item.status for item in projection.tasks] == ["closed", "active"]


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
