from __future__ import annotations

import pytest

from .current_bdd_support import (
    activated_runtime,
    apply_event,
    assign_role,
    author_event,
    modules,
    stage,
    submit_role_result,
)


def test_s_05g_role_evidence_after_stop_changes_nothing() -> None:
    ranked = stage(
        key="rank",
        depth="explore",
        mode="ranked",
        allocation_wea=5,
        payout_vector=[5],
    )
    state = activated_runtime(plan_stages=(ranked,), total_bank_wea=5)
    state = assign_role(state, targets=("a", "b"), sequence=1)
    state = apply_event(state, author_event(state, "author_stop", {}, sequence=2))
    before = state.state_hash
    with pytest.raises(modules()["intake"].PlanError, match="terminal"):
        submit_role_result(state, target_id="a", sequence=3)
    assert state.state_hash == before
    projection = modules()["lifecycle"].project_runtime(state)
    assert projection.escrow.refunded_wea == 5
    assert projection.releases == ()
