from __future__ import annotations

from dataclasses import replace

import pytest

from .current_bdd_support import (
    assessment,
    decision,
    draft,
    github_state,
    modules,
    plan_revision,
    record_decision,
    record_plan,
    record_triage,
    replace_decision,
    replace_plan_revision,
    stages,
    state_with_plan,
)


@pytest.mark.parametrize(
    "schedule",
    (
        None,
        (0, None, (), None),
        (None, 10, (10,) * 5, 10),
        (10, None, (), None),
    ),
)
def test_s_02h_missing_non_positive_or_mode_wrong_schedule_is_rejected(
    schedule: tuple[int | None, int | None, tuple[int, ...], int | None] | None,
) -> None:
    intake = modules()["intake"]
    first = stages()[0]
    if schedule is None:
        raw = object.__new__(intake.StageSchedule)
        for name, value in {
            "intake_seconds": None,
            "join_seconds": None,
            "move_seconds": (),
            "author_decision_seconds": None,
        }.items():
            object.__setattr__(raw, name, value)
        candidate = raw
    else:
        intake_seconds, join_seconds, move_seconds, decision_seconds = schedule
        with pytest.raises(intake.PlanError):
            intake.StageSchedule(
                intake_seconds=intake_seconds,
                join_seconds=join_seconds,
                move_seconds=move_seconds,
                author_decision_seconds=decision_seconds,
            ).validate_mode("duel")
        return

    with pytest.raises(intake.PlanError, match="schedule"):
        replace(plan_revision(), stages=(replace(first, schedule=candidate),))


def test_s_02h_schedule_is_part_of_the_exact_plan_hash() -> None:
    first = plan_revision()
    changed_stage = replace(
        first.stages[0],
        schedule=replace(first.stages[0].schedule, join_seconds=601),
    )
    changed = replace_plan_revision(first, stages=(changed_stage, *first.stages[1:]))

    assert first.content_hash != changed.content_hash


def test_s_02h_author_decision_source_must_follow_the_plan_source() -> None:
    state, draft, _, plan = state_with_plan()
    approval = replace_decision(
        decision(plan),
        effective_at=plan.effective_at,
        source_comment_id="author-comment-before-plan",
        source_revision_id="author-source-before-plan",
    )

    with pytest.raises(modules()["intake"].PlanError, match="must follow"):
        record_decision(state, draft, approval)

    assert state.decisions == ()


def test_s_02h_initial_plan_must_follow_triage_completion_source_order() -> None:
    intake = modules()["intake"]
    draft_record = draft()
    assessment_record = assessment()
    state = intake.PlanIntakeState(
        balances=(intake.AccountBalance("agent-author", 150),)
    )
    state = record_triage(state, draft_record, assessment_record)
    inverted = replace_plan_revision(
        plan_revision(),
        effective_at=assessment_record.completion_effective_at,
        source_comment_id="a-plan",
    )

    with pytest.raises(intake.PlanError, match="Draft/Triage"):
        record_plan(
            state,
            draft_record,
            inverted,
            evidence_state=github_state(draft_record, assessment_record, inverted),
        )

    later = replace_plan_revision(
        inverted,
        source_comment_id="z-plan",
    )
    accepted = record_plan(
        state,
        draft_record,
        later,
        evidence_state=github_state(draft_record, assessment_record, later),
    )
    assert accepted.plan_revisions[-1] == later
