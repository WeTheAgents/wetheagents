from __future__ import annotations

from .current_bdd_support import (
    activated_runtime,
    apply_event,
    author_event,
    lifecycle_event,
    modules,
    stage,
    submit_work,
)


def test_s_04c_spec_author_has_no_exclusive_implement_right_or_duty() -> None:
    intake = modules()["intake"]
    spec = stage(
        key="spec",
        depth="spec",
        mode="ranked",
        allocation_wea=5,
        payout_vector=[5],
    )
    implement = stage(
        key="implement",
        depth="implement",
        mode="ranked",
        allocation_wea=10,
        payout_vector=[6, 4],
        inputs=(intake.SelectedWorkInput("spec"),),
    )
    state = activated_runtime(plan_stages=(spec, implement), total_bank_wea=15)
    state, spec_work, spec_revision = submit_work(
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
        author_event(
            state,
            "ranked_order",
            {
                "contract_id": contract_id,
                "ordered_work_ids": [spec_work],
                "selected_revision_id": spec_revision,
            },
            sequence=12,
        ),
    )
    state, alpha_work, _ = submit_work(
        state,
        agent_id="agent-alpha",
        account_id="account-alpha",
        sequence=13,
    )
    state, beta_work, _ = submit_work(
        state,
        agent_id="agent-beta",
        account_id="account-beta",
        sequence=14,
    )
    works = modules()["lifecycle"].project_runtime(state).current_stage.works
    assert {item.work_id for item in works} == {alpha_work, beta_work}
