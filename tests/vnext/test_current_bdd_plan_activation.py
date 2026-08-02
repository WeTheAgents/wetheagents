from __future__ import annotations

import pytest

from .current_bdd_support import (
    activate_plan,
    decision,
    modules,
    record_decision,
    state_with_plan,
)


def _approved(*, author_balance: int):
    state, draft, _, plan = state_with_plan(author_balance=author_balance)
    approval = decision(plan)
    state = record_decision(state, draft, approval)
    return state, draft, plan, approval


def test_s_02a_insufficient_funds_leave_all_activation_effects_absent() -> None:
    intake = modules()["intake"]
    state, draft, plan, approval = _approved(author_balance=99)
    before = state.state_hash

    with pytest.raises(intake.PlanError, match="balance"):
        activate_plan(state, draft, plan, approval)

    assert state.state_hash == before
    assert state.plans == state.escrows == state.contracts == state.tasks == ()
    assert state.ledger == ()
    assert state.balance("agent-author") == 99


def test_s_02c_author_funds_complete_plan_and_first_deadline_only() -> None:
    state, draft, plan, approval = _approved(author_balance=150)
    result = activate_plan(state, draft, plan, approval)

    assert result.state.balance("agent-author") == 50
    assert result.debit.amount_wea == result.plan.total_bank_wea == 100
    assert result.escrow.available_wea == 100
    assert len(result.state.contracts) == len(result.state.tasks) == 1
    assert [item.kind for item in result.contract.deadlines] == ["join"]
    assert result.contract.deadlines[0].duration_seconds == 600


def test_s_02c_third_party_payer_cannot_activate_any_effect() -> None:
    intake = modules()["intake"]
    state, draft, plan, approval = _approved(author_balance=150)
    before = state.state_hash

    with pytest.raises(intake.PlanError, match="payer"):
        activate_plan(
            state,
            draft,
            plan,
            approval,
            payer_agent_id="agent-reviewer",
            payer_github_account_id="account-reviewer",
        )

    assert state.state_hash == before
    assert state.plans == state.escrows == state.contracts == state.ledger == ()


def test_s_02c_created_activation_must_match_its_sealed_state_group() -> None:
    intake = modules()["intake"]
    lifecycle = modules()["lifecycle"]
    state, draft, plan, approval = _approved(author_balance=150)
    valid = activate_plan(state, draft, plan, approval)
    forged = intake.PlanActivation(
        intake.PlanIntakeState(),
        True,
        valid.draft,
        valid.plan,
        valid.escrow,
        valid.contract,
        valid.task,
        valid.debit,
    )

    with pytest.raises(intake.PlanError, match="activation group"):
        lifecycle.start_runtime(forged)
