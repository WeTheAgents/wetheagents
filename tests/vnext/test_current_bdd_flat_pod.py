from __future__ import annotations

import pytest

from .current_bdd_support import (
    accept_work,
    activated_runtime,
    apply_event,
    lifecycle_event,
    modules,
    stage,
    submit_work,
)


def test_s_69_flat_pod_pays_one_equal_atomic_slot_per_work() -> None:
    flat = stage(
        key="answers",
        depth="explore",
        mode="flat_pod",
        allocation_wea=6,
        payout_vector=[2, 2, 2],
        slots=3,
    )
    state = activated_runtime(plan_stages=(flat,), total_bank_wea=6)
    state, identifier, revision = submit_work(
        state,
        agent_id="agent-alpha",
        account_id="account-alpha",
        sequence=1,
    )
    accepted = accept_work(
        state,
        work_id=identifier,
        revision_id=revision,
        sequence=2,
    )
    projection = modules()["lifecycle"].project_runtime(accepted)
    assert projection.balance("agent-alpha") == 2
    assert projection.escrow.paid_wea == 2

    replay_event = accepted.events[-1]
    assert apply_event(accepted, replay_event) == accepted
    revised, _, later_revision = submit_work(
        accepted,
        agent_id="agent-alpha",
        account_id="account-alpha",
        sequence=3,
    )
    before = revised.state_hash
    with pytest.raises(modules()["intake"].PlanError, match="one Work"):
        accept_work(
            revised,
            work_id=identifier,
            revision_id=later_revision,
            sequence=4,
        )
    assert revised.state_hash == before

    contract_id = projection.current_stage.contract.contract_id
    closed = apply_event(
        accepted,
        lifecycle_event(
            accepted,
            "mode_expiry",
            {"contract_id": contract_id},
            sequence=11,
        ),
    )
    final = modules()["lifecycle"].project_runtime(closed)
    assert final.plan_status == "completed"
    assert final.escrow.paid_wea == 2
    assert final.escrow.refunded_wea == 4
    assert final.balance("agent-author") == 198


def test_s_69_invalid_or_failed_acceptance_changes_no_state_or_money() -> None:
    flat = stage(
        key="answers",
        depth="explore",
        mode="flat_pod",
        allocation_wea=2,
        payout_vector=[2],
        slots=1,
    )
    state = activated_runtime(plan_stages=(flat,), total_bank_wea=2)
    state, identifier, revision = submit_work(
        state,
        agent_id="agent-alpha",
        account_id="account-alpha",
        sequence=1,
        eligible=False,
    )
    before = state.state_hash
    with pytest.raises(modules()["intake"].PlanError, match="eligible"):
        accept_work(
            state,
            work_id=identifier,
            revision_id=revision,
            sequence=2,
        )
    assert state.state_hash == before
    projection = modules()["lifecycle"].project_runtime(state)
    assert projection.escrow.paid_wea == 0
    assert projection.balance("agent-alpha") == 0
