from __future__ import annotations

import pytest

from .current_bdd_support import (
    accept_work,
    activated_runtime,
    apply_event,
    common_control_registry,
    confirm_control_disclosure,
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


def test_s_03f_common_control_blocks_ranked_selection_until_public_evidence() -> None:
    ranked = stage(
        key="rank",
        depth="explore",
        mode="ranked",
        allocation_wea=5,
        payout_vector=[5],
    )
    state = activated_runtime(plan_stages=(ranked,), total_bank_wea=5)
    identity_registry = common_control_registry("agent-alpha")
    state, work_id, revision_id = submit_work(
        state,
        agent_id="agent-alpha",
        account_id="account-alpha",
        sequence=1,
        identity_registry=identity_registry,
    )
    work = modules()["lifecycle"].project_runtime(state).current_stage.works[0]
    disclosure = work.authority.disclosure
    assert disclosure is not None and not disclosure.confirmed
    assert work.authority.author.control_group_binding_version == 1
    assert work.authority.participant.control_group_binding_version == 1
    action = modules()["lifecycle"].next_action(state, "agent-author")
    assert action.plan_revision_id == state.activation.plan.plan_revision_id
    assert action.work_id == work_id
    assert action.control_group_id == "owner-author"
    assert action.action == "wait for the public common-control disclosure"
    participant_action = modules()["lifecycle"].next_action(state, "agent-alpha")
    assert participant_action.action == "submit eligible Work"
    assert participant_action.work_id == work_id
    assert participant_action.control_group_id == "owner-author"

    contract_id = work.contract_id
    state = apply_event(
        state,
        lifecycle_event(
            state, "mode_expiry", {"contract_id": contract_id}, sequence=11
        ),
        identity_registry=identity_registry,
    )
    order = lifecycle_event(
        state,
        "ranked_order",
        {
            "contract_id": contract_id,
            "ordered_work_ids": [work_id],
            "selected_revision_id": revision_id,
        },
        sequence=12,
        actor_kind="author",
        actor_id="agent-author",
        actor_account_id="account-author",
    )
    before = state.state_hash
    with pytest.raises(modules()["intake"].PlanError, match="common-control"):
        apply_event(state, order, identity_registry=identity_registry)
    assert state.state_hash == before

    disclosure_event = lifecycle_event(
        state,
        "control_disclosure",
        {
            "contract_id": contract_id,
            "disclosure_revision_id": "disclosure-revision-0012",
            "disclosure_source_id": "disclosure-source-0012",
            "work_id": work_id,
        },
        sequence=12,
    )
    with pytest.raises(modules()["intake"].PlanError, match="revision is missing"):
        apply_event(
            state,
            disclosure_event,
            identity_registry=identity_registry,
        )
    state = confirm_control_disclosure(
        state,
        work_id=work_id,
        sequence=12,
        identity_registry=identity_registry,
    )
    confirmed = modules()["lifecycle"].project_runtime(state).current_stage.works[0]
    assert confirmed.authority.disclosure is not None
    assert confirmed.authority.disclosure.confirmed
    settled = apply_event(
        state,
        lifecycle_event(
            state,
            "ranked_order",
            {
                "contract_id": contract_id,
                "ordered_work_ids": [work_id],
                "selected_revision_id": revision_id,
            },
            sequence=13,
            actor_kind="author",
            actor_id="agent-author",
            actor_account_id="account-author",
        ),
        identity_registry=identity_registry,
    )
    projection = modules()["lifecycle"].project_runtime(settled)
    assert projection.plan_status == "completed"
    assert projection.balance("agent-alpha") == 5


@pytest.mark.parametrize("mode", ("flat_pod", "frontier"))
def test_s_03f_common_control_blocks_additive_payment(mode: str) -> None:
    candidate = stage(
        key="flat-pod" if mode == "flat_pod" else "frontier",
        depth="explore",
        mode=mode,
        allocation_wea=5,
        payout_vector=[5],
        slots=1 if mode == "flat_pod" else None,
    )
    state = activated_runtime(plan_stages=(candidate,), total_bank_wea=5)
    identity_registry = common_control_registry("agent-alpha")
    state, work_id, revision_id = submit_work(
        state,
        agent_id="agent-alpha",
        account_id="account-alpha",
        sequence=1,
        snapshot={"model": "m", "genome": "g", "runtime": "r"}
        if mode == "frontier"
        else None,
        identity_registry=identity_registry,
    )
    before = state.state_hash
    with pytest.raises(modules()["intake"].PlanError, match="common-control"):
        accept_work(
            state,
            work_id=work_id,
            revision_id=revision_id,
            sequence=2,
        )
    assert state.state_hash == before
    state = confirm_control_disclosure(
        state,
        work_id=work_id,
        sequence=2,
        identity_registry=identity_registry,
    )
    state = accept_work(
        state,
        work_id=work_id,
        revision_id=revision_id,
        sequence=3,
    )
    projection = modules()["lifecycle"].project_runtime(state)
    assert projection.plan_status == "completed"
    assert projection.balance("agent-alpha") == 5
