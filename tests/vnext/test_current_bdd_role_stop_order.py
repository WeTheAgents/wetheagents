from __future__ import annotations

import pytest

from .current_bdd_support import (
    activated_runtime,
    apply_event,
    assign_role,
    author_event,
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


def test_s_05e_stop_waits_for_complete_timely_role_resolution() -> None:
    state = assign_role(_state(), sequence=1)
    state = submit_role_result(state, sequence=2)
    with pytest.raises(modules()["intake"].PlanError, match="resolved first"):
        apply_event(state, author_event(state, "author_stop", {}, sequence=3))
    state = resolve_role(state, sequence=3)
    stopped = apply_event(state, author_event(state, "author_stop", {}, sequence=4))
    projection = modules()["lifecycle"].project_runtime(stopped)
    assert projection.roles[0].status == "completed"
    assert projection.escrow.refunded_wea == 5


def test_s_05f_incomplete_role_evidence_does_not_block_stop() -> None:
    state = assign_role(
        _state(),
        targets=("a", "b"),
        funding="treasury",
        amount_wea=3,
        sequence=1,
    )
    state = submit_role_result(state, target_id="a", sequence=2)
    stopped = apply_event(state, author_event(state, "author_stop", {}, sequence=3))
    projection = modules()["lifecycle"].project_runtime(stopped)
    assert projection.plan_status == "stopped"
    assert projection.roles[0].status == "stopped"
    assert projection.releases == ()
    assert projection.escrow.refunded_wea == 5
    assert projection.balance("treasury") == 100
    assert [item.kind for item in projection.settlements] == [
        "treasury-reserve",
        "treasury-refund",
        "refund",
    ]
