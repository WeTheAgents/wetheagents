from __future__ import annotations

from datetime import timedelta

import pytest

from .current_bdd_support import (
    accept_work,
    activated_runtime,
    apply_event,
    digest,
    lifecycle_event,
    modules,
    stage,
    submit_work,
)


def test_s_06c_expiry_waits_until_after_the_inclusive_deadline() -> None:
    ranked = stage(
        key="rank",
        depth="explore",
        mode="ranked",
        allocation_wea=5,
        payout_vector=[5],
    )
    state = activated_runtime(plan_stages=(ranked,), total_bank_wea=5)
    lifecycle = modules()["lifecycle"]
    current = lifecycle.project_runtime(state).current_stage
    contract_id = current.contract.contract_id
    due = current.deadlines[0].effective_due_at
    at_deadline = lifecycle_event(
        state,
        "mode_expiry",
        {"contract_id": contract_id},
        sequence=1,
        effective_at=due,
    )

    with pytest.raises(modules()["intake"].PlanError, match="not expired"):
        apply_event(state, at_deadline)

    identifier = lifecycle.work_id(contract_id, "agent-alpha")
    revision_id = lifecycle.work_revision_id(identifier, 1)
    state = apply_event(
        state,
        lifecycle_event(
            state,
            "work_revision",
            {
                "content_hash": digest("deadline work"),
                "contract_id": contract_id,
                "eligible": True,
                "normalized_output": None,
                "revision_id": revision_id,
                "snapshot": None,
            },
            sequence=2,
            actor_kind="agent",
            actor_id="agent-alpha",
            actor_account_id="account-alpha",
            effective_at=due,
        ),
    )
    state = apply_event(
        state,
        lifecycle_event(
            state,
            "mode_expiry",
            {"contract_id": contract_id},
            sequence=3,
            effective_at=due + timedelta(microseconds=1),
        ),
    )

    projection = lifecycle.project_runtime(state)
    assert projection.current_stage.phase == "decision"
    assert projection.current_stage.works[0].revisions[0].revision_id == revision_id


def test_s_06c_ranked_silence_refunds_every_unallocated_rank() -> None:
    ranked = stage(
        key="rank",
        depth="explore",
        mode="ranked",
        allocation_wea=10,
        payout_vector=[6, 4],
    )
    state = activated_runtime(plan_stages=(ranked,), total_bank_wea=10)
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
            state, "mode_expiry", {"contract_id": contract_id}, sequence=17
        ),
    )
    projection = modules()["lifecycle"].project_runtime(state)
    assert projection.plan_status == "completed"
    assert projection.escrow.paid_wea == 0
    assert projection.escrow.refunded_wea == 10


def test_s_06c_frontier_expiry_preserves_paid_prefix_and_refunds_suffix() -> None:
    frontier = stage(
        key="frontier",
        depth="explore",
        mode="frontier",
        allocation_wea=6,
        payout_vector=[1, 2, 3],
    )
    state = activated_runtime(plan_stages=(frontier,), total_bank_wea=6)
    state, identifier, revision = submit_work(
        state,
        agent_id="agent-alpha",
        account_id="account-alpha",
        sequence=1,
        snapshot={"model": "m1", "genome": "g1", "runtime": "r1"},
    )
    state = accept_work(
        state,
        work_id=identifier,
        revision_id=revision,
        sequence=2,
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
    projection = modules()["lifecycle"].project_runtime(state)
    assert projection.escrow.paid_wea == 1
    assert projection.escrow.refunded_wea == 5
    assert projection.balance("agent-alpha") == 1
