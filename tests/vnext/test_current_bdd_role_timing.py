from __future__ import annotations

import pytest

from .current_bdd_support import (
    activated_runtime,
    assign_role,
    modules,
    resolve_role,
    stage,
    submit_role_result,
)


def _state():
    ranked = stage(
        key="rank",
        depth="explore",
        mode="ranked",
        allocation_wea=5,
        payout_vector=[5],
    )
    return activated_runtime(plan_stages=(ranked,), total_bank_wea=5)


def test_s_05d_complete_timely_result_can_wait_for_late_agent0_resolution() -> None:
    state = assign_role(
        _state(), duration_seconds=120, funding="treasury", amount_wea=2, sequence=1
    )
    state = submit_role_result(state, sequence=2)
    state = resolve_role(state, sequence=10)
    projection = modules()["lifecycle"].project_runtime(state)
    assert projection.roles[0].status == "completed"
    assert projection.roles[0].escrow_available_wea == 0
    assert projection.balance("agent-alpha") == 2
    assert projection.balance("treasury") == 98
    assert [item.kind for item in projection.settlements] == [
        "treasury-reserve",
        "treasury",
    ]


def test_s_05d_late_final_result_cannot_complete_the_role() -> None:
    state = assign_role(_state(), duration_seconds=120, sequence=1)
    state = submit_role_result(state, sequence=4)
    with pytest.raises(modules()["intake"].PlanError, match="timely"):
        resolve_role(state, sequence=5)
    assert modules()["lifecycle"].project_runtime(state).roles[0].status == "active"


def test_s_05e_treasury_role_assignment_is_fully_funded_or_absent() -> None:
    ranked = stage(
        key="rank",
        depth="explore",
        mode="ranked",
        allocation_wea=5,
        payout_vector=[5],
    )
    state = activated_runtime(
        plan_stages=(ranked,), total_bank_wea=5, treasury_balance=1
    )
    before = state.state_hash
    with pytest.raises(modules()["intake"].PlanError, match="treasury"):
        assign_role(
            state,
            duration_seconds=120,
            funding="treasury",
            amount_wea=2,
            sequence=1,
        )
    assert state.state_hash == before
    projection = modules()["lifecycle"].project_runtime(state)
    assert projection.balance("treasury") == 1
    assert projection.roles == ()
