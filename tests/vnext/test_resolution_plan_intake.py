from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from .resolution_plan_support import (
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


def test_s_56_author_can_approve_triage_plan_or_an_append_only_amendment() -> None:
    state, draft_record, _, first = state_with_plan()
    amended = plan_revision(
        revision_number=2,
        proposer_kind="author",
        parent_revision_id=first.revision_id,
    )
    state = record_plan(state, draft_record, amended)
    state = record_decision(state, draft_record, decision(amended))

    assert [item.proposer_kind for item in state.plan_revisions] == [
        "triage",
        "author",
    ]
    assert state.plan_revisions[1].parent_revision_id == first.revision_id
    assert state.decisions[0].plan_revision_id == amended.revision_id
    assert state.feedback_chain("issue-42") == (
        assessment().assessment_id,
        first.revision_id,
        amended.revision_id,
        state.decisions[0].decision_id,
    )


def test_exact_plan_revision_replay_is_idempotent() -> None:
    state, draft_record, _, first = state_with_plan()

    assert record_plan(state, draft_record, first) is state


def test_second_triage_proposal_requires_author_request() -> None:
    intake = modules()["intake"]
    state, draft_record, _, first = state_with_plan()
    premature_second = plan_revision(
        revision_number=2,
        proposer_kind="triage",
        parent_revision_id=first.revision_id,
    )

    with pytest.raises(intake.PlanError, match="author request"):
        record_plan(state, draft_record, premature_second)

    request = decision(first, outcome="request_revision")
    state = record_decision(state, draft_record, request)
    second = replace(
        premature_second, effective_at=request.effective_at + timedelta(minutes=1)
    )
    state = record_plan(state, draft_record, second)
    assert state.plan_revisions[-1] == second
    assert state.feedback_chain("issue-42") == (
        assessment().assessment_id,
        first.revision_id,
        request.decision_id,
        second.revision_id,
    )


def test_plan_revision_evidence_strictly_follows_parent_in_canonical_order() -> None:
    intake = modules()["intake"]
    state, draft_record, _, first = state_with_plan()
    amendment = plan_revision(
        revision_number=2,
        proposer_kind="author",
        parent_revision_id=first.revision_id,
    )

    backdated = replace_plan_revision(
        amendment,
        effective_at=first.effective_at - timedelta(seconds=1),
    )
    with pytest.raises(intake.PlanError, match="must follow parent"):
        record_plan(state, draft_record, backdated)

    earlier_equal_time = replace_plan_revision(
        amendment,
        effective_at=first.effective_at,
        source_comment_id="plan-comment-0",
    )
    with pytest.raises(intake.PlanError, match="must follow parent"):
        record_plan(state, draft_record, earlier_equal_time)

    later_equal_time = replace_plan_revision(
        amendment,
        effective_at=first.effective_at,
    )
    accepted = record_plan(state, draft_record, later_equal_time)
    assert accepted.plan_revisions[-1] == later_equal_time


@pytest.mark.parametrize("outcome", ("request_revision", "decline"))
def test_s_56_non_approval_preserves_feedback_without_task_money(outcome: str) -> None:
    state, draft_record, _, plan = state_with_plan()
    state = record_decision(state, draft_record, decision(plan, outcome=outcome))

    assert state.decisions[0].outcome == outcome
    assert state.escrows == state.contracts == state.tasks == state.ledger == ()


def test_s_57_semantic_negativa_warning_is_advice_not_veto() -> None:
    intake = modules()["intake"]
    state, draft_record, _, plan = state_with_plan(
        advice="Recommend decline: likely not worth the budget"
    )
    state = record_decision(state, draft_record, decision(plan))

    result = intake.call_verified(
        "activate_resolution_plan",
        state,
        draft_record,
        plan_revision_id=plan.revision_id,
        decision_id=state.decisions[0].decision_id,
        payer_agent_id="agent-author",
        payer_github_account_id="account-author",
        effective_at=decision(plan).effective_at,
        registry=registry(),
        github_state=github_state(
            draft_record,
            *state.triage_assessments,
            *state.plan_revisions,
            *state.decisions,
        ),
    )

    assert result.created is True
    assert result.plan.status == "active"


def test_author_decision_outcome_must_match_normalized_source_snapshot() -> None:
    intake = modules()["intake"]
    _, _, _, plan = state_with_plan()
    base = decision(plan)
    contradictory = "I decline this Plan and authorize no debit"

    with pytest.raises(intake.PlanError, match="normalized evidence"):
        replace(
            base,
            snapshot=contradictory,
            snapshot_hash=digest(contradictory),
        )

    with pytest.raises(intake.PlanError, match="decision ID is not deterministic"):
        replace(base, decision_id="caller-selected-decision")
    with pytest.raises(intake.PlanError, match="idempotency key is not deterministic"):
        replace(base, idempotency_key="caller-selected-key")


def test_issue_author_cannot_self_attest_triage() -> None:
    intake = modules()["intake"]
    base_draft = draft()
    self_review = replace_assessment(
        assessment(),
        reviewer_agent_id="agent-author",
        reviewer_github_account_id="account-author",
        reviewer_binding_id="author-binding",
    )
    state = intake.PlanIntakeState(
        balances=(intake.AccountBalance("agent-author", 150),)
    )

    with pytest.raises(intake.PlanError, match="exact Draft"):
        record_triage(state, base_draft, self_review)


def test_triage_requires_exact_agent0_assignment_and_completion_evidence() -> None:
    intake = modules()["intake"]
    identity = modules()["identity"]
    base_assessment = assessment()

    with pytest.raises(intake.PlanError, match="assignment_snapshot"):
        replace(
            base_assessment,
            assignment_snapshot="{}",
            assignment_snapshot_hash=digest("{}"),
        )

    with pytest.raises(intake.PlanError, match="assessment ID is not deterministic"):
        replace(base_assessment, assessment_id="caller-selected-assessment")

    state = intake.PlanIntakeState(
        balances=(intake.AccountBalance("agent-author", 150),)
    )
    with pytest.raises(intake.PlanError, match="accepted GitHub revision is missing"):
        record_triage(
            state,
            draft(),
            base_assessment,
            evidence_state=github_state(draft()),
        )

    original_draft = draft()
    with pytest.raises(
        intake.PlanError, match="accepted GitHub revision content does not match"
    ):
        record_triage(
            state,
            replace(original_draft, max_bank_wea=200),
            base_assessment,
            evidence_state=github_state(original_draft, base_assessment),
        )

    base_registry = registry()
    expired_bindings = tuple(
        replace(
            item,
            effective_until=base_assessment.completion_effective_at,
        )
        if item.binding_id == "agent0-role-binding"
        else item
        for item in base_registry.bindings
    )
    expired_agent0 = identity.IdentityRegistry(
        accounts=base_registry.accounts,
        bindings=expired_bindings,
        control_group_bindings=base_registry.control_group_bindings,
    )
    state = intake.PlanIntakeState(
        balances=(intake.AccountBalance("agent-author", 150),)
    )

    with pytest.raises(intake.PlanError, match="Triage evidence is not authorized"):
        record_triage(
            state,
            draft(),
            base_assessment,
            identity_registry=expired_agent0,
        )


def test_triage_reviewer_must_be_authorized_when_agent0_assigns_the_role() -> None:
    intake = modules()["intake"]
    identity = modules()["identity"]
    base_assessment = assessment()
    base_registry = registry()
    late_reviewer = identity.IdentityRegistry(
        accounts=base_registry.accounts,
        bindings=tuple(
            replace(
                item,
                effective_from=base_assessment.assignment_effective_at
                + timedelta(minutes=1),
            )
            if item.binding_id == "reviewer-binding"
            else item
            for item in base_registry.bindings
        ),
        control_group_bindings=base_registry.control_group_bindings,
    )
    state = intake.PlanIntakeState(
        balances=(intake.AccountBalance("agent-author", 150),)
    )

    with pytest.raises(intake.PlanError, match="Triage evidence is not authorized"):
        record_triage(
            state,
            draft(),
            base_assessment,
            identity_registry=late_reviewer,
        )


def test_triage_evidence_must_follow_draft_and_finish_before_plan() -> None:
    intake = modules()["intake"]
    base_assessment = assessment()
    state = intake.PlanIntakeState(
        balances=(intake.AccountBalance("agent-author", 150),)
    )

    with pytest.raises(intake.PlanError, match="exact Draft"):
        altered_draft = replace(
            draft(), effective_at=base_assessment.assignment_effective_at
        )
        altered_assessment = replace(
            base_assessment,
            assignment_effective_at=base_assessment.assignment_effective_at
            - timedelta(seconds=1),
        )
        record_triage(
            state,
            altered_draft,
            altered_assessment,
            evidence_state=github_state(altered_draft, altered_assessment),
        )

    state = record_triage(state, draft(), base_assessment)
    with pytest.raises(intake.PlanError, match="Draft/Triage"):
        early_plan = replace(
            plan_revision(),
            effective_at=base_assessment.completion_effective_at - timedelta(seconds=1),
        )
        record_plan(
            state,
            draft(),
            early_plan,
            evidence_state=github_state(draft(), base_assessment, early_plan),
        )


def test_triage_rejects_blocked_or_stale_issue_evidence() -> None:
    intake = modules()["intake"]
    draft_record = draft()
    assessment_record = assessment()
    state = intake.PlanIntakeState(
        balances=(intake.AccountBalance("agent-author", 150),)
    )
    accepted = github_state(draft_record, assessment_record)
    blocked = replace(
        accepted,
        read_blockers=(intake.ReadBlocker("repository-1", 2, "read-incomplete"),),
    )

    with pytest.raises(intake.PlanError, match="unresolved read blocker"):
        record_triage(
            state,
            draft_record,
            assessment_record,
            evidence_state=blocked,
        )

    newer_draft = replace(
        draft_record,
        issue_revision_id="issue-revision-2",
        body="Solve the exact problem with a changed constraint",
        effective_at=draft_record.effective_at + timedelta(minutes=1),
    )
    with pytest.raises(intake.PlanError, match="latest accepted revision"):
        record_triage(
            state,
            draft_record,
            assessment_record,
            evidence_state=github_state(
                draft_record,
                newer_draft,
                assessment_record,
            ),
        )


def test_triage_proposer_binding_must_still_be_active_at_plan_revision() -> None:
    intake = modules()["intake"]
    identity = modules()["identity"]
    draft_record = draft()
    assessment_record = assessment()
    plan_record = plan_revision()
    base_registry = registry()
    expiring_registry = identity.IdentityRegistry(
        accounts=base_registry.accounts,
        bindings=tuple(
            replace(item, effective_until=plan_record.effective_at)
            if item.binding_id == "reviewer-binding"
            else item
            for item in base_registry.bindings
        ),
        control_group_bindings=base_registry.control_group_bindings,
    )
    state = intake.PlanIntakeState(
        balances=(intake.AccountBalance("agent-author", 150),)
    )
    state = record_triage(
        state,
        draft_record,
        assessment_record,
        identity_registry=expiring_registry,
    )

    with pytest.raises(intake.PlanError, match="Triage proposer is not authorized"):
        record_plan(
            state,
            draft_record,
            plan_record,
            identity_registry=expiring_registry,
        )


def test_s_57_formal_failures_are_closed() -> None:
    intake = modules()["intake"]
    base_draft = draft()
    base_assessment = assessment()
    empty = intake.PlanIntakeState(
        balances=(intake.AccountBalance("agent-author", 150),)
    )

    with pytest.raises(intake.PlanError, match="identity"):
        altered_draft = replace(
            base_draft, creator_github_account_id="account-reviewer"
        )
        record_triage(
            empty,
            altered_draft,
            base_assessment,
            evidence_state=github_state(altered_draft, base_assessment),
        )

    state, _, _, plan = state_with_plan()
    wrong_author = replace_decision(
        decision(plan),
        author_github_account_id="account-reviewer",
        author_binding_id="reviewer-binding",
    )
    with pytest.raises(intake.PlanError, match="authority"):
        record_decision(state, draft(), wrong_author)

    with pytest.raises(intake.PlanError, match="snapshot_hash"):
        replace(base_assessment, snapshot_hash=digest("forged"))

    with pytest.raises(intake.PlanError, match="money"):
        replace(plan, total_bank_wea=99)

    missing_evidence = intake.PlanIntakeState(
        balances=(intake.AccountBalance("agent-author", 150),)
    )
    with pytest.raises(intake.PlanError, match="evidence"):
        record_plan(missing_evidence, base_draft, plan)


def test_plan_approval_must_target_the_latest_exact_revision() -> None:
    intake = modules()["intake"]
    state, draft_record, _, first = state_with_plan()
    amended = plan_revision(
        revision_number=2,
        proposer_kind="author",
        parent_revision_id=first.revision_id,
    )
    state = record_plan(state, draft_record, amended)

    with pytest.raises(intake.PlanError, match="latest"):
        record_decision(state, draft_record, decision(first))

    forged = replace_decision(decision(amended), plan_content_hash="0" * 64)
    with pytest.raises(intake.PlanError, match="content_hash"):
        record_decision(state, draft_record, forged)
