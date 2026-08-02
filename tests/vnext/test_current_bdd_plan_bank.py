from __future__ import annotations

from dataclasses import replace

import pytest

from .current_bdd_support import modules, plan_revision


def test_s_05c_plan_bank_is_exact_stage_sum_without_hidden_fee() -> None:
    plan = plan_revision()

    assert plan.total_bank_wea == sum(stage.allocation_wea for stage in plan.stages)
    assert all("review_fee" not in stage.to_data() for stage in plan.stages)


def test_s_05c_unlisted_fee_cannot_be_added_to_plan_bank() -> None:
    intake = modules()["intake"]
    plan = plan_revision()

    with pytest.raises(intake.PlanError, match="allocations"):
        replace(plan, total_bank_wea=plan.total_bank_wea + 1)
