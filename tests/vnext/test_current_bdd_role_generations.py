from __future__ import annotations

import pytest

from .current_bdd_support import (
    activated_runtime,
    apply_event,
    assign_role,
    modules,
    resolve_role,
    stage,
    submit_role_result,
)


def test_s_05a_role_result_authority_is_bound_to_the_exact_generation() -> None:
    ranked = stage(
        key="rank",
        depth="explore",
        mode="ranked",
        allocation_wea=5,
        payout_vector=[5],
    )
    state = activated_runtime(plan_stages=(ranked,), total_bank_wea=5)
    state = assign_role(state, generation=1, sequence=1)
    state = assign_role(
        state,
        generation=2,
        sequence=2,
        assigned_agent_id="agent-beta",
        assigned_account_id="account-beta",
    )

    with pytest.raises(modules()["intake"].PlanError, match="assigned actor"):
        submit_role_result(
            state,
            generation=1,
            sequence=3,
            assigned_agent_id="agent-beta",
            assigned_account_id="account-beta",
        )

    state = submit_role_result(state, generation=1, sequence=3)
    roles = modules()["lifecycle"].project_runtime(state).roles
    assert roles[0].timely_complete is True
    assert roles[1].results == ()


def test_s_05a_role_generations_settle_once_under_each_frozen_term() -> None:
    ranked = stage(
        key="rank",
        depth="explore",
        mode="ranked",
        allocation_wea=5,
        payout_vector=[5],
    )
    state = activated_runtime(plan_stages=(ranked,), total_bank_wea=5)
    state = assign_role(
        state, funding="treasury", amount_wea=3, generation=1, sequence=1
    )
    state = submit_role_result(state, generation=1, sequence=2)
    state = resolve_role(state, generation=1, sequence=3)
    state = assign_role(
        state, funding="treasury", amount_wea=3, generation=2, sequence=4
    )
    state = submit_role_result(state, generation=2, sequence=5)
    state = resolve_role(state, generation=2, sequence=6)
    replay = apply_event(state, state.events[-1])
    projection = modules()["lifecycle"].project_runtime(state)
    assert replay == state
    assert [item.status for item in projection.roles] == ["completed", "completed"]
    assert projection.balance("agent-alpha") == 6
    assert (
        len([item for item in projection.settlements if item.kind == "treasury"]) == 2
    )
