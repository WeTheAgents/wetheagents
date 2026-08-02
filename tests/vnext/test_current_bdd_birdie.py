from __future__ import annotations

import pytest

from .current_bdd_support import (
    activated_runtime,
    apply_event,
    lifecycle_event,
    modules,
    stage,
    submit_work,
)


def test_s_07a_birdie_closes_ranked_intake_early_for_exact_work() -> None:
    ranked = stage(
        key="rank",
        depth="explore",
        mode="ranked",
        allocation_wea=5,
        payout_vector=[5],
    )
    state = activated_runtime(plan_stages=(ranked,), total_bank_wea=5)
    state, identifier, _ = submit_work(
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
            state,
            "birdie",
            {"contract_id": contract_id, "work_id": identifier},
            sequence=2,
            actor_kind="author",
            actor_id="agent-author",
            actor_account_id="account-author",
        ),
    )
    projection = modules()["lifecycle"].project_runtime(state)
    assert projection.current_stage.phase == "decision"
    assert projection.current_stage.birdie_at is not None


def test_s_07b_birdie_rejects_frontier_and_missing_work_without_change() -> None:
    frontier = stage(
        key="frontier",
        depth="explore",
        mode="frontier",
        allocation_wea=1,
        payout_vector=[1],
    )
    state = activated_runtime(plan_stages=(frontier,), total_bank_wea=1)
    contract_id = (
        modules()["lifecycle"].project_runtime(state).current_stage.contract.contract_id
    )
    before = state.state_hash
    event = lifecycle_event(
        state,
        "birdie",
        {"contract_id": contract_id, "work_id": "missing"},
        sequence=1,
        actor_kind="author",
        actor_id="agent-author",
        actor_account_id="account-author",
    )
    with pytest.raises(modules()["intake"].PlanError, match="birdie"):
        apply_event(state, event)
    assert state.state_hash == before
