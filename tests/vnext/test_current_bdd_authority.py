from __future__ import annotations

import pytest

from .current_bdd_support import (
    decision,
    modules,
    record_decision,
    replace_decision,
    state_with_plan,
)


def test_s_01c_non_author_cannot_approve_a_plan() -> None:
    intake = modules()["intake"]
    state, draft, _, plan = state_with_plan()
    valid = decision(plan)
    invalid = replace_decision(
        valid,
        author_agent_id="agent-reviewer",
        author_github_account_id="account-reviewer",
        author_binding_id="reviewer-binding",
    )
    before = state.state_hash

    with pytest.raises(intake.PlanError, match="author"):
        record_decision(state, draft, invalid)

    assert state.state_hash == before
    assert state.plans == state.escrows == state.contracts == state.tasks == ()


def test_s_01c_operator_or_agent0_cannot_replace_author_approval() -> None:
    intake = modules()["intake"]
    state, draft, _, plan = state_with_plan()
    valid = decision(plan)
    for account_id, agent_id, binding_id in (
        ("account-agent0", "agent0@system", "agent0-role-binding"),
        ("unknown-account", "operator@system", "unknown-binding"),
    ):
        invalid = replace_decision(
            valid,
            author_agent_id=agent_id,
            author_github_account_id=account_id,
            author_binding_id=binding_id,
        )
        with pytest.raises(intake.PlanError):
            record_decision(state, draft, invalid)

    assert state.plans == state.escrows == state.ledger == ()
