from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import timedelta

import pytest

from .resolution_plan_support import (
    activate_plan,
    assessment,
    decision,
    digest,
    draft,
    github_state,
    modules,
    plan_revision,
    record_decision,
    record_plan,
    record_triage,
    registry,
    replace_assessment,
    replace_decision,
    replace_plan_revision,
    state_with_plan,
)


def _approved_state(*, author_balance: int = 150):
    state, draft_record, _, plan = state_with_plan(author_balance=author_balance)
    author_decision = decision(plan)
    state = record_decision(state, draft_record, author_decision)
    return state, draft_record, plan, author_decision


def _activate(*, author_balance: int = 150):
    state, draft_record, plan, author_decision = _approved_state(
        author_balance=author_balance
    )
    return activate_plan(state, draft_record, plan, author_decision)


def test_s_58_approval_atomically_escrows_100_and_materializes_only_first_child() -> (
    None
):
    result = _activate()

    assert result.created is True
    assert result.state.balance("agent-author") == 50
    assert result.plan.total_bank_wea == 100
    assert result.plan.stage_allocations == (20, 40, 40)
    assert result.escrow.deposited_wea == 100
    assert result.escrow.available_wea == 100
    assert result.debit.amount_wea == 100
    assert result.contract.stage_key == "architecture"
    assert result.contract.allocation_wea == 20
    assert result.task.status == "active"
    assert result.task.stage_key == "architecture"
    assert len(result.state.contracts) == len(result.state.tasks) == 1
    assert not any(
        item.stage_key in {"specification", "implementation"}
        for item in result.state.contracts
    )
    assert result.plan.stages[1].inputs[0].source_stage_key == "architecture"


def test_s_58_exact_replay_is_idempotent_and_does_not_debit_twice() -> None:
    intake = modules()["intake"]
    first = _activate()
    again = intake.call_verified(
        "activate_resolution_plan",
        first.state,
        first.draft,
        plan_revision_id=first.plan.plan_revision_id,
        decision_id=first.plan.approval_decision_id,
        payer_agent_id="agent-author",
        payer_github_account_id="account-author",
        effective_at=first.plan.activated_at,
        registry=registry(),
        github_state=github_state(
            first.draft,
            *first.state.triage_assessments,
            *first.state.plan_revisions,
            *first.state.decisions,
        ),
    )

    assert again.created is False
    assert again.state == first.state
    assert again.state.balance("agent-author") == 50
    assert len(again.state.ledger) == 1


def test_two_distinct_plans_form_one_deterministic_financial_hash_chain() -> None:
    intake = modules()["intake"]
    state, first_draft, _, first_plan = state_with_plan(author_balance=300)
    first_decision = decision(first_plan)
    state = record_decision(state, first_draft, first_decision)
    first = activate_plan(state, first_draft, first_plan, first_decision)

    second_draft = replace(
        draft(),
        issue_id="issue-43",
        issue_number=43,
        issue_revision_id="issue-revision-43",
        body="Solve a second exact problem",
        effective_at=first.plan.activated_at + timedelta(minutes=1),
    )
    assessment_id = intake.triage_assessment_id(
        second_draft.repository_id,
        second_draft.issue_id,
        second_draft.issue_revision_id,
    )
    second_assessment = replace_assessment(
        assessment(),
        assessment_id=assessment_id,
        assignment_id=intake.triage_assignment_id(assessment_id),
        completion_id=intake.triage_completion_id(assessment_id),
        issue_id=second_draft.issue_id,
        issue_revision_id=second_draft.issue_revision_id,
        body_hash=digest(second_draft.body),
        assignment_source_comment_id="triage-assignment-comment-43",
        assignment_source_revision_id="triage-assignment-revision-43",
        assignment_effective_at=second_draft.effective_at + timedelta(minutes=1),
        source_comment_id="triage-comment-43",
        source_revision_id="triage-source-revision-43",
        effective_at=second_draft.effective_at + timedelta(minutes=2),
        completion_source_comment_id="triage-completion-comment-43",
        completion_source_revision_id="triage-completion-revision-43",
        completion_effective_at=second_draft.effective_at + timedelta(minutes=3),
    )
    second_plan_id = intake.resolution_plan_id(
        second_draft.repository_id, second_draft.issue_id
    )
    second_plan = replace_plan_revision(
        plan_revision(),
        plan_id=second_plan_id,
        revision_id=intake.resolution_plan_revision_id(second_plan_id, 1),
        issue_id=second_draft.issue_id,
        issue_revision_id=second_draft.issue_revision_id,
        body_hash=digest(second_draft.body),
        triage_assessment_id=assessment_id,
        source_comment_id="plan-comment-43",
        source_revision_id="plan-source-revision-43",
        effective_at=second_draft.effective_at + timedelta(minutes=4),
    )
    second_decision = replace_decision(
        decision(second_plan),
        source_comment_id="author-comment-43",
        source_revision_id="author-source-revision-43",
        effective_at=second_draft.effective_at + timedelta(minutes=5),
    )

    state = record_triage(first.state, second_draft, second_assessment)
    state = record_plan(state, second_draft, second_plan)
    state = record_decision(state, second_draft, second_decision)
    second = activate_plan(state, second_draft, second_plan, second_decision)

    assert second.state.balance("agent-author") == 100
    assert len(second.state.plans) == len(second.state.ledger) == 2
    assert len({item.prior_financial_hash for item in second.state.ledger}) == 2


def test_active_plan_cannot_receive_another_revision() -> None:
    intake = modules()["intake"]
    result = _activate()
    amended = plan_revision(
        revision_number=2,
        proposer_kind="author",
        parent_revision_id=result.plan.plan_revision_id,
    )

    with pytest.raises(intake.PlanError, match="active Plan revisions are immutable"):
        record_plan(result.state, result.draft, amended)


def test_s_58_insufficient_balance_leaves_every_activation_effect_absent() -> None:
    intake = modules()["intake"]
    state, draft_record, plan, author_decision = _approved_state(author_balance=99)
    before = state.state_hash

    with pytest.raises(intake.PlanError, match="balance"):
        intake.call_verified(
            "activate_resolution_plan",
            state,
            draft_record,
            plan_revision_id=plan.revision_id,
            decision_id=author_decision.decision_id,
            payer_agent_id="agent-author",
            payer_github_account_id="account-author",
            effective_at=author_decision.effective_at,
            registry=registry(),
            github_state=github_state(
                draft_record,
                *state.triage_assessments,
                *state.plan_revisions,
                *state.decisions,
            ),
        )

    assert state.state_hash == before
    assert (
        state.escrows
        == state.plans
        == state.contracts
        == state.tasks
        == state.ledger
        == ()
    )


def test_activation_rejects_a_different_authorized_draft() -> None:
    intake = modules()["intake"]
    state, _, plan, author_decision = _approved_state()
    other_draft = replace(
        draft(),
        issue_id="issue-other",
        issue_number=43,
        issue_revision_id="issue-revision-other",
        body="Different problem",
        max_bank_wea=1,
    )

    with pytest.raises(intake.PlanError, match="activation Draft"):
        intake.call_verified(
            "activate_resolution_plan",
            state,
            other_draft,
            plan_revision_id=plan.revision_id,
            decision_id=author_decision.decision_id,
            payer_agent_id="agent-author",
            payer_github_account_id="account-author",
            effective_at=author_decision.effective_at,
            registry=registry(),
            github_state=github_state(
                other_draft,
                *state.triage_assessments,
                *state.plan_revisions,
                *state.decisions,
            ),
        )


def test_activation_rejects_an_edited_author_decision_source() -> None:
    intake = modules()["intake"]
    state, draft_record, plan, approval = _approved_state()
    edited = replace_decision(
        approval,
        outcome="decline",
        source_revision_id="author-source-edited",
        effective_at=approval.effective_at + timedelta(seconds=1),
    )

    with pytest.raises(intake.PlanError, match="latest accepted revision"):
        activate_plan(
            state,
            draft_record,
            plan,
            approval,
            evidence_state=github_state(
                draft_record,
                *state.triage_assessments,
                *state.plan_revisions,
                *state.decisions,
                edited,
            ),
        )


def test_activation_records_are_frozen_and_restored_partial_group_is_rejected() -> None:
    intake = modules()["intake"]
    result = _activate()

    with pytest.raises(FrozenInstanceError):
        result.contract.allocation_wea = 99  # type: ignore[misc]
    with pytest.raises(intake.PlanError, match="verified transition"):
        replace(result.state, tasks=())


def test_restored_activation_cannot_restore_the_spent_author_balance() -> None:
    intake = modules()["intake"]
    result = _activate()

    with pytest.raises(intake.PlanError, match="verified transition"):
        replace(
            result.state,
            balances=(intake.AccountBalance("agent-author", 150),),
        )

    raw_module = object.__getattribute__(intake, "_ReadOnlyModule__module")
    assert "_ACTIVATION_CAPABILITY" not in vars(raw_module)
    assert "_verified_activation_replace" not in vars(raw_module)
    with pytest.raises(intake.PlanError, match="verified transition"):
        replace(
            result.state,
            balances=(intake.AccountBalance("agent-author", 150),),
            ledger=(
                replace(
                    result.debit,
                    prior_financial_hash="0" * 64,
                ),
            ),
        )


def test_restored_activation_rejects_runtime_outside_verified_closure() -> None:
    intake = modules()["intake"]
    result = _activate()
    forged_plan = replace(result.plan, ruleset_hash="0" * 64)
    forged_contract = replace(result.contract, ruleset_hash="0" * 64)

    with pytest.raises(intake.PlanError, match="verified transition"):
        replace(
            result.state,
            plans=(forged_plan,),
            contracts=(forged_contract,),
        )


def test_restored_activation_rejects_spent_or_non_atomic_group() -> None:
    intake = modules()["intake"]
    result = _activate()

    with pytest.raises(intake.PlanError, match="verified transition"):
        replace(
            result.state,
            escrows=(replace(result.escrow, paid_wea=1),),
        )
    with pytest.raises(intake.PlanError, match="verified transition"):
        replace(
            result.state,
            contracts=(
                replace(
                    result.contract,
                    activated_at=result.contract.activated_at + timedelta(seconds=1),
                ),
            ),
        )


def test_activation_rejects_state_or_registry_mutated_after_validation() -> None:
    intake = modules()["intake"]
    state, draft_record, plan, author_decision = _approved_state()
    object.__setattr__(state.balances[0], "amount_wea", 1000)

    with pytest.raises(intake.PlanError, match="changed after validation"):
        intake.call_verified(
            "activate_resolution_plan",
            state,
            draft_record,
            plan_revision_id=plan.revision_id,
            decision_id=author_decision.decision_id,
            payer_agent_id="agent-author",
            payer_github_account_id="account-author",
            effective_at=author_decision.effective_at,
            registry=registry(),
            github_state=github_state(
                draft_record,
                *state.triage_assessments,
                *state.plan_revisions,
                *state.decisions,
            ),
        )


def test_plan_escrow_namespace_cannot_be_registered_as_an_agent() -> None:
    identity = modules()["identity"]
    base = registry()
    collision = "plan-escrow:resolution-plan:repository-1:issue-42"

    with pytest.raises(identity.IdentityError, match="reserved system account"):
        identity.IdentityRegistry(
            accounts=(
                *base.accounts,
                identity.GitHubAccount("collision-account", "collision", collision),
            ),
            bindings=(
                *base.bindings,
                identity.Binding(
                    "collision-binding",
                    "agent",
                    "collision-account",
                    collision,
                    1,
                    author_decision_time(),
                ),
            ),
            control_group_bindings=(
                *base.control_group_bindings,
                identity.ControlGroupBinding(
                    "collision-group",
                    collision,
                    "collision-owner",
                    1,
                    author_decision_time(),
                ),
            ),
        )


def test_future_stage_selector_cannot_point_forward_or_materialize_early() -> None:
    intake = modules()["intake"]
    valid = plan_revision()
    invalid_first = replace(
        valid.stages[0],
        inputs=(intake.SelectedWorkInput("implementation"),),
    )

    with pytest.raises(intake.PlanError, match="earlier"):
        replace(valid, stages=(invalid_first, *valid.stages[1:]))


def author_decision_time():
    return decision(plan_revision()).effective_at
