from __future__ import annotations

from .current_bdd_support import (
    accept_work,
    activated_runtime,
    modules,
    stage,
    submit_work,
)


def test_s_65_missing_selector_pauses_without_creating_future_child() -> None:
    intake = modules()["intake"]
    first = stage(
        key="ideas",
        depth="explore",
        mode="flat_pod",
        allocation_wea=1,
        payout_vector=[1],
        slots=1,
    )
    second = stage(
        key="spec",
        depth="spec",
        mode="ranked",
        allocation_wea=5,
        payout_vector=[5],
        inputs=(intake.SelectedWorkInput("ideas"),),
    )
    state = activated_runtime(plan_stages=(first, second), total_bank_wea=6)
    state, identifier, revision = submit_work(
        state,
        agent_id="agent-alpha",
        account_id="account-alpha",
        sequence=1,
    )
    state = accept_work(state, work_id=identifier, revision_id=revision, sequence=2)
    projection = modules()["lifecycle"].project_runtime(state)
    assert projection.plan_status == "paused"
    assert len(projection.stages) == 1
    assert len(projection.tasks) == 1
    assert projection.current_task.status == "closed"
    assert projection.current_task.close_result == "completed"
    assert projection.escrow.paid_wea == 1
    assert projection.escrow.available_wea == 5
    assert projection.pauses[-1].kind == "progression_pause"
