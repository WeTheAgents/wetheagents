from __future__ import annotations

from datetime import timedelta

from .current_bdd_support import (
    activated_runtime,
    apply_body_transition,
    apply_event,
    assign_role,
    body_transition_event,
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
    state = apply_body_transition(
        state,
        "body_pause",
        body="Changed Issue body",
        sequence=6,
    )
    resume, resume_evidence = body_transition_event(
        state,
        "body_resume",
        body=state.activation.draft.body,
        sequence=8,
    )
    state = apply_event(state, resume, evidence_state=resume_evidence)
    moved = modules()["lifecycle"].project_runtime(state).roles[0]
    assert moved.effective_due_at == role.base_due_at + timedelta(minutes=2)
    assert apply_event(state, resume, evidence_state=resume_evidence) == state
    assert len(modules()["lifecycle"].project_runtime(state).stages) == 1
