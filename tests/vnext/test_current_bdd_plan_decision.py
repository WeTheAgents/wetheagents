from __future__ import annotations

import pytest

from .current_bdd_support import (
    activate_plan,
    decision,
    modules,
    record_decision,
    state_with_plan,
)


@pytest.mark.parametrize("outcome", ("request_revision", "decline"))
def test_s_02i_request_or_decline_keeps_draft_without_money(outcome: str) -> None:
    intake = modules()["intake"]
    state, draft, _, plan = state_with_plan()
    author_decision = decision(plan, outcome=outcome)
    state = record_decision(state, draft, author_decision)

    with pytest.raises(intake.PlanError, match="approval"):
        activate_plan(state, draft, plan, author_decision)

    assert state.plans == state.escrows == state.ledger == ()


def test_s_02i_exact_author_approval_activates_once() -> None:
    state, draft, _, plan = state_with_plan()
    approval = decision(plan)
    state = record_decision(state, draft, approval)
    result = activate_plan(state, draft, plan, approval)
    replay = activate_plan(result.state, draft, plan, approval)

    assert result.created is True
    assert replay.created is False
    assert replay.state == result.state
