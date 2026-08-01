from __future__ import annotations

from dataclasses import replace

import pytest

from .current_bdd_support import (
    modules,
    plan_revision,
    replace_plan_revision,
    stages,
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
