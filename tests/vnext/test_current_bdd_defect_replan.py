from __future__ import annotations

import pytest

from .current_bdd_support import (
    activated_runtime,
    apply_event,
    apply_suffix_replan,
    assign_role,
    author_event,
    lifecycle_event,
    modules,
    stage,
    submit_work,
)


def test_s_04d_and_s_66_replan_changes_only_unstarted_suffix() -> None:
    intake = modules()["intake"]
    first = stage(
        key="explore",
        depth="explore",
        mode="ranked",
        allocation_wea=5,
        payout_vector=[5],
    )
    second = stage(
        key="spec",
        depth="spec",
        mode="ranked",
        allocation_wea=5,
        payout_vector=[5],
        inputs=(intake.SelectedWorkInput("explore"),),
    )
    third = stage(
        key="implement",
        depth="implement",
        mode="ranked",
        allocation_wea=10,
        payout_vector=[10],
        inputs=(intake.SelectedWorkInput("spec"),),
    )
    state = activated_runtime(plan_stages=(first, second, third), total_bank_wea=20)
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
        author_event(
            state,
            "ranked_order",
            {
                "contract_id": contract_id,
                "ordered_work_ids": [identifier],
                "selected_revision_id": revision,
            },
            sequence=12,
        ),
    )
    before = modules()["lifecycle"].project_runtime(state)
    completed_bytes = before.stages[0].contract.to_data()
    active_bytes = before.stages[1].contract.to_data()

    state = assign_role(state, sequence=13)
    state = apply_event(
        state,
        lifecycle_event(
            state,
            "risk_warning",
            {"generation": 1, "role_id": "review-role", "warning_id": "defect-1"},
            sequence=14,
            actor_kind="role",
            actor_id="agent-alpha",
            actor_account_id="account-alpha",
        ),
    )
    state = apply_event(
        state,
        lifecycle_event(
            state,
            "risk_pause",
            {"warning_id": "defect-1"},
            sequence=15,
            actor_kind="agent0",
            actor_id="agent0@system",
            actor_account_id="account-agent0",
        ),
    )
    additive = stage(
        key="additive-research",
        depth="explore",
        mode="flat_pod",
        allocation_wea=4,
        payout_vector=[2, 2],
        slots=2,
    )
    impossible_successor = stage(
        key="impossible-implement",
        depth="implement",
        mode="ranked",
        allocation_wea=6,
        payout_vector=[6],
        inputs=(intake.SelectedWorkInput("additive-research"),),
    )
    with pytest.raises(intake.PlanError, match="Flat PoD"):
        apply_suffix_replan(
            state,
            (additive, impossible_successor),
            sequence=16,
        )
    with pytest.raises(intake.PlanError, match="exact Plan revision"):
        apply_event(
            state,
            author_event(
                state,
                "suffix_replan",
                {"replacement_suffix": [third.to_data()]},
                sequence=17,
            ),
        )
    corrected = stage(
        key="corrected-implement",
        depth="implement",
        mode="ranked",
        allocation_wea=10,
        payout_vector=[10],
        inputs=(intake.SelectedWorkInput("spec"),),
    )
    state = apply_suffix_replan(
        state,
        (corrected,),
        sequence=18,
    )
    projection = modules()["lifecycle"].project_runtime(state)
    assert projection.stages[0].contract.to_data() == completed_bytes
    assert projection.stages[1].contract.to_data() == active_bytes
    assert projection.future_stages[-1].key == "corrected-implement"
    assert projection.escrow.available_wea == 15
    assert len(projection.plan_revisions) == 2
    assert projection.current_plan_revision_id == (
        projection.plan_revisions[-1].revision_id
    )
    assert projection.plan_revision_approvals[0].plan_revision_id == (
        projection.current_plan_revision_id
    )
    assert projection.plan_revision_approvals[0].author_agent_id == "agent-author"

    state, spec_work, spec_revision = submit_work(
        state,
        agent_id="agent-beta",
        account_id="account-beta",
        sequence=19,
    )
    spec_contract_id = (
        modules()["lifecycle"].project_runtime(state).current_stage.contract.contract_id
    )
    state = apply_event(
        state,
        lifecycle_event(
                state, "mode_expiry", {"contract_id": spec_contract_id}, sequence=23
        ),
    )
    state = apply_event(
        state,
        author_event(
            state,
            "ranked_order",
            {
                "contract_id": spec_contract_id,
                "ordered_work_ids": [spec_work],
                "selected_revision_id": spec_revision,
            },
            sequence=24,
        ),
    )
    progressed = modules()["lifecycle"].project_runtime(state)
    assert progressed.current_stage.stage_key == "corrected-implement"
    assert progressed.current_stage.contract.plan_revision_id == (
        projection.current_plan_revision_id
    )
    assert progressed.current_stage.contract.plan_content_hash == (
        projection.current_plan_content_hash
    )
