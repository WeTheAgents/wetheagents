from __future__ import annotations

from dataclasses import replace

import pytest

from .current_bdd_support import (
    activate_plan,
    decision,
    modules,
    plan_revision,
    record_decision,
    record_plan,
    replace_plan_revision,
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


def test_s_02i_triage_revision_must_follow_request_in_canonical_order() -> None:
    intake = modules()["intake"]
    state, draft, _, first = state_with_plan()
    request = decision(first, outcome="request_revision")
    state = record_decision(state, draft, request)
    earlier_equal_time = replace_plan_revision(
        plan_revision(
            revision_number=2,
            proposer_kind="triage",
            parent_revision_id=first.revision_id,
        ),
        effective_at=request.effective_at,
        source_comment_id="aaa-triage-proposal",
    )

    with pytest.raises(intake.PlanError, match="author request"):
        record_plan(state, draft, earlier_equal_time)
    with pytest.raises(intake.PlanError, match="author request"):
        replace(
            state,
            plan_revisions=(*state.plan_revisions, earlier_equal_time),
        )
