from __future__ import annotations

import pytest

from .current_bdd_support import (
    activated_runtime,
    apply_event,
    assign_role,
    author_event,
    lifecycle_event,
    modules,
    stage,
    submit_work,
)


def test_s_04b_assigned_warning_needs_agent0_and_keeps_author_decision() -> None:
    ranked = stage(
        key="rank",
        depth="explore",
        mode="ranked",
        allocation_wea=5,
        payout_vector=[5],
    )
    state = activated_runtime(plan_stages=(ranked,), total_bank_wea=5)
    state = assign_role(state, sequence=1)
    warning = lifecycle_event(
        state,
        "risk_warning",
        {"role_id": "review-role", "warning_id": "warning-1"},
        sequence=2,
        actor_kind="role",
        actor_id="agent-alpha",
        actor_account_id="account-alpha",
    )
    state = apply_event(state, warning)
    before_pause = modules()["lifecycle"].project_runtime(state)
    assert before_pause.plan_status == "active"
    before_money = before_pause.escrow.to_data()

    pause = lifecycle_event(
        state,
        "risk_pause",
        {"warning_id": "warning-1"},
        sequence=3,
        actor_kind="agent0",
        actor_id="agent0@system",
        actor_account_id="account-agent0",
    )
    state = apply_event(state, pause)
    paused = modules()["lifecycle"].project_runtime(state)
    assert paused.plan_status == "paused"
    assert paused.escrow.to_data() == before_money
    contract_before = paused.current_stage.contract.to_data()

    state, _, _ = submit_work(
        state,
        agent_id="agent-beta",
        account_id="account-beta",
        sequence=4,
    )
    still_paused = modules()["lifecycle"].project_runtime(state)
    assert still_paused.plan_status == "paused"
    assert len(still_paused.current_stage.works) == 1
    assert still_paused.current_stage.contract.to_data() == contract_before

    continued = apply_event(
        state, author_event(state, "author_continue", {}, sequence=5)
    )
    assert modules()["lifecycle"].project_runtime(continued).plan_status == "active"


def test_s_04b_unassigned_warning_cannot_support_a_risk_pause() -> None:
    ranked = stage(
        key="rank",
        depth="explore",
        mode="ranked",
        allocation_wea=5,
        payout_vector=[5],
    )
    state = activated_runtime(plan_stages=(ranked,), total_bank_wea=5)
    warning = lifecycle_event(
        state,
        "risk_warning",
        {"role_id": "missing-role", "warning_id": "warning-x"},
        sequence=1,
        actor_kind="role",
        actor_id="agent-beta",
        actor_account_id="account-beta",
    )
    with pytest.raises(modules()["intake"].PlanError, match="assigned"):
        apply_event(state, warning)
    assert modules()["lifecycle"].project_runtime(state).plan_status == "active"
