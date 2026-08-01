from __future__ import annotations

import pytest

from .current_bdd_support import (
    activated_runtime,
    apply_event,
    assign_role,
    author_event,
    lifecycle_event,
    modules,
    resolve_role,
    stage,
    submit_role_result,
)


def test_s_02j_complete_pre_pause_role_result_keeps_frozen_outcome() -> None:
    ranked = stage(
        key="rank",
        depth="explore",
        mode="ranked",
        allocation_wea=5,
        payout_vector=[5],
    )
    state = activated_runtime(plan_stages=(ranked,), total_bank_wea=5)
    state = assign_role(
        state,
        funding="treasury",
        amount_wea=3,
        duration_seconds=600,
        sequence=1,
    )
    state = submit_role_result(state, sequence=2)
    state = apply_event(
        state,
        lifecycle_event(
            state,
            "body_pause",
            {"cause_id": "changed-issue-body"},
            sequence=3,
        ),
    )
    state = resolve_role(state, sequence=4)
    state = apply_event(state, author_event(state, "author_stop", {}, sequence=5))
    projection = modules()["lifecycle"].project_runtime(state)
    assert projection.roles[0].status == "completed"
    assert projection.balance("agent-alpha") == 3
    assert projection.escrow.refunded_wea == 5


def test_s_02j_new_or_partial_role_result_after_pause_changes_nothing() -> None:
    ranked = stage(
        key="rank",
        depth="explore",
        mode="ranked",
        allocation_wea=5,
        payout_vector=[5],
    )
    state = activated_runtime(plan_stages=(ranked,), total_bank_wea=5)
    state = assign_role(state, targets=("a", "b"), duration_seconds=600, sequence=1)
    state = submit_role_result(state, target_id="a", sequence=2)
    state = apply_event(
        state,
        lifecycle_event(
            state,
            "body_pause",
            {"cause_id": "changed-issue-body"},
            sequence=3,
        ),
    )
    before = state.state_hash
    with pytest.raises(modules()["intake"].PlanError, match="outside"):
        submit_role_result(state, target_id="b", sequence=4)
    assert state.state_hash == before
    stopped = apply_event(state, author_event(state, "author_stop", {}, sequence=5))
    projection = modules()["lifecycle"].project_runtime(stopped)
    assert projection.plan_status == "stopped"
    assert projection.roles[0].status == "stopped"
