from __future__ import annotations

from datetime import timedelta

from .current_bdd_support import (
    activated_runtime,
    apply_event,
    assign_role,
    lifecycle_event,
    modules,
    stage,
)


def test_s_05h_role_deadline_starts_at_assignment_and_moves_once() -> None:
    ranked = stage(
        key="rank",
        depth="explore",
        mode="ranked",
        allocation_wea=5,
        payout_vector=[5],
    )
    state = activated_runtime(plan_stages=(ranked,), total_bank_wea=5)
    state = assign_role(state, duration_seconds=600, sequence=5)
    role = modules()["lifecycle"].project_runtime(state).roles[0]
    assert role.base_due_at == state.activation.plan.activated_at + timedelta(
        minutes=15
    )
    state = apply_event(
        state,
        lifecycle_event(
            state,
            "body_pause",
            {"cause_id": "changed-body"},
            sequence=6,
        ),
    )
    resume = lifecycle_event(state, "body_resume", {}, sequence=8)
    state = apply_event(state, resume)
    moved = modules()["lifecycle"].project_runtime(state).roles[0]
    assert moved.effective_due_at == role.base_due_at + timedelta(minutes=2)
    assert apply_event(state, resume) == state
    assert len(modules()["lifecycle"].project_runtime(state).stages) == 1
