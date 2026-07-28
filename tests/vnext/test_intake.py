from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from wea_vnext.identity import (
    Binding,
    ControlGroupBinding,
    GitHubAccount,
    IdentityError,
    IdentityRegistry,
)
from wea_vnext.intake import (
    AccountBalance,
    DraftIssue,
    IntakeError,
    IntakeState,
    MechanicTerms,
    TriageAssignment,
    TriageCompletion,
    TriageRecord,
    TriageRole,
    assign_triage,
    complete_triage,
    record_triage,
    triage_escrow_id,
    triage_role_id,
    validate_draft,
)

NOW = datetime(2026, 7, 28, 10, tzinfo=timezone.utc)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _registry() -> IdentityRegistry:
    return IdentityRegistry(
        accounts=(
            GitHubAccount("account-agent0", "agent0", "agent0-base"),
            GitHubAccount("account-author", "author", "agent-author"),
            GitHubAccount("account-reviewer", "reviewer", "agent-reviewer"),
        ),
        bindings=(
            Binding(
                "binding-agent0-base",
                "agent",
                "account-agent0",
                "agent0-base",
                1,
                NOW - timedelta(days=1),
            ),
            Binding(
                "binding-agent0-role",
                "agent0",
                "account-agent0",
                "agent0@system",
                1,
                NOW - timedelta(days=1),
            ),
            Binding(
                "binding-author",
                "agent",
                "account-author",
                "agent-author",
                1,
                NOW - timedelta(days=1),
            ),
            Binding(
                "binding-reviewer",
                "agent",
                "account-reviewer",
                "agent-reviewer",
                1,
                NOW - timedelta(days=1),
            ),
        ),
        control_group_bindings=(
            ControlGroupBinding(
                "group-agent0",
                "agent0-base",
                "owner-agent0",
                1,
                NOW - timedelta(days=1),
            ),
            ControlGroupBinding(
                "group-author",
                "agent-author",
                "owner-author",
                1,
                NOW - timedelta(days=1),
            ),
            ControlGroupBinding(
                "group-reviewer",
                "agent-reviewer",
                "owner-reviewer",
                1,
                NOW - timedelta(days=1),
            ),
        ),
    )


def _draft() -> DraftIssue:
    return DraftIssue(
        issue_id="issue-42",
        issue_revision_id="issue-revision-1",
        creator_github_account_id="account-author",
        author_agent_id="agent-author",
        body="Exact Issue body",
        bank_wea=3,
        profile="direct-pr",
        terms=MechanicTerms(
            mechanic="pod",
            review_fee_wea=1,
            payout_vector=(2,),
            config={"mode": "finite", "payout_wea": 2, "slots": 1},
        ),
    )


@pytest.mark.parametrize("source", ["issue-form", "cli", "tide"])
def test_common_validator_keeps_a_valid_issue_as_a_read_only_draft(
    source: str,
) -> None:
    state = IntakeState(balances=(AccountBalance("agent-author", 10),))
    before = state.state_hash

    result = validate_draft(
        _draft(),
        effective_at=NOW,
        registry=_registry(),
        available_balance_wea=10,
    )

    assert source in {"issue-form", "cli", "tide"}
    assert result.status == "draft"
    assert result.balance_sufficient is True
    assert result.author.agent_id == "agent-author"
    assert state.state_hash == before
    assert state.contracts == state.tasks == state.escrows == state.ledger == ()


def test_draft_requires_author_agent_id_bound_to_issue_creator() -> None:
    with pytest.raises(IntakeError, match="author_agent_id"):
        validate_draft(
            replace(_draft(), author_agent_id="agent-other"),
            effective_at=NOW,
            registry=_registry(),
        )


def test_duel_draft_requires_exact_outcome_vectors_for_its_bank() -> None:
    terms = MechanicTerms(
        mechanic="duel",
        review_fee_wea=0,
        payout_vector=(),
        config={
            "outcome_vectors": {
                "inconclusive": {"payout_vector": [5, 5], "refund_wea": 0},
                "no-completers": {"payout_vector": [0, 0], "refund_wea": 10},
                "single-completer": {"payout_vector": [9, 0], "refund_wea": 1},
                "winner": {"payout_vector": [9, 1], "refund_wea": 0},
            }
        },
    )
    draft = replace(_draft(), bank_wea=10, profile="duel", terms=terms)

    assert (
        validate_draft(
            draft,
            effective_at=NOW,
            registry=_registry(),
        ).status
        == "draft"
    )

    with pytest.raises(IntakeError, match="bank_wea"):
        validate_draft(
            replace(draft, bank_wea=11),
            effective_at=NOW,
            registry=_registry(),
        )


@pytest.mark.parametrize(
    ("mechanic", "config", "payout_vector"),
    [
        ("pod", {"mode": "finite", "payout_wea": 2, "slots": 2}, (2, 2)),
        ("linear", {"mode": "infinite", "slots": 3}, (1, 2, 3)),
        ("progressive", {"mode": "infinite", "slots": 4}, (1, 1, 2, 3)),
        ("winner-take-all", {"mode": "finite", "prize_pool_wea": 7}, (7,)),
        (
            "best-x",
            {"mode": "finite", "prize_pool_wea": 10, "winners": 2},
            (7, 3),
        ),
    ],
)
def test_each_ordinary_mechanic_requires_its_ruleset_derived_payout_vector(
    mechanic: str,
    config: dict[str, object],
    payout_vector: tuple[int, ...],
) -> None:
    terms = MechanicTerms(
        mechanic=mechanic,
        review_fee_wea=1,
        payout_vector=payout_vector,
        config=config,
    )
    draft = replace(_draft(), bank_wea=1 + sum(payout_vector), terms=terms)

    assert (
        validate_draft(draft, effective_at=NOW, registry=_registry()).status == "draft"
    )

    altered_vector = (payout_vector[0] + 1, *payout_vector[1:])
    invalid_terms = replace(terms, payout_vector=altered_vector)
    invalid_draft = replace(
        draft,
        bank_wea=1 + sum(altered_vector),
        terms=invalid_terms,
    )
    with pytest.raises(IntakeError, match="payout_vector"):
        validate_draft(invalid_draft, effective_at=NOW, registry=_registry())


def test_additional_review_stage_must_use_an_allowed_profile_extension_point() -> None:
    terms = MechanicTerms(
        mechanic="pod",
        review_fee_wea=2,
        payout_vector=(2,),
        config={
            "mode": "finite",
            "payout_wea": 2,
            "slots": 1,
            "additional_review_stages": [
                {
                    "duration_seconds": 3600,
                    "extension_point": "after-made-up-stage",
                    "on_approved_stage": "author-decision",
                    "on_changes_stage": "implementation-review",
                    "stage_id": "security-review",
                    "targets": ["agent-security"],
                }
            ],
        },
    )
    with pytest.raises(IntakeError, match="extension_point"):
        validate_draft(
            replace(_draft(), bank_wea=4, terms=terms),
            effective_at=NOW,
            registry=_registry(),
        )


@pytest.mark.parametrize(
    ("field", "destination"),
    (
        ("on_approved_stage", "pr-intake"),
        ("on_changes_stage", "final"),
    ),
)
def test_additional_review_stage_uses_exact_versioned_successors(
    field: str, destination: str
) -> None:
    stage = {
        "duration_seconds": 3600,
        "extension_point": "after-implementation-review",
        "on_approved_stage": "author-decision",
        "on_changes_stage": "author-decision",
        "stage_id": "security-review",
        "targets": ["agent-security"],
    }
    stage[field] = destination
    terms = MechanicTerms(
        mechanic="pod",
        review_fee_wea=2,
        payout_vector=(2,),
        config={
            "mode": "finite",
            "payout_wea": 2,
            "slots": 1,
            "additional_review_stages": [stage],
        },
    )

    with pytest.raises(IntakeError, match=field):
        validate_draft(
            replace(_draft(), bank_wea=4, terms=terms),
            effective_at=NOW,
            registry=_registry(),
        )


def test_additional_review_stage_accepts_the_exact_versioned_successors() -> None:
    terms = MechanicTerms(
        mechanic="pod",
        review_fee_wea=2,
        payout_vector=(2,),
        config={
            "mode": "finite",
            "payout_wea": 2,
            "slots": 1,
            "additional_review_stages": [
                {
                    "duration_seconds": 3600,
                    "extension_point": "after-implementation-review",
                    "on_approved_stage": "author-decision",
                    "on_changes_stage": "author-decision",
                    "stage_id": "security-review",
                    "targets": ["agent-security"],
                }
            ],
        },
    )

    assert (
        validate_draft(
            replace(_draft(), bank_wea=4, terms=terms),
            effective_at=NOW,
            registry=_registry(),
        ).status
        == "draft"
    )


def test_additional_review_stage_id_cannot_shadow_a_profile_stage() -> None:
    terms = MechanicTerms(
        mechanic="pod",
        review_fee_wea=2,
        payout_vector=(2,),
        config={
            "mode": "finite",
            "payout_wea": 2,
            "slots": 1,
            "additional_review_stages": [
                {
                    "duration_seconds": 3600,
                    "extension_point": "after-implementation-review",
                    "on_approved_stage": "author-decision",
                    "on_changes_stage": "author-decision",
                    "stage_id": "implementation-review",
                    "targets": ["agent-security"],
                }
            ],
        },
    )

    with pytest.raises(IntakeError, match="stage_id"):
        validate_draft(
            replace(_draft(), bank_wea=4, terms=terms),
            effective_at=NOW,
            registry=_registry(),
        )


@pytest.mark.parametrize(
    "reserved_agent_id",
    [
        "treasury",
        "task-escrow:existing-contract",
        "triage-escrow:existing-role",
    ],
)
def test_ledger_principal_namespaces_are_reserved_from_agent_identity(
    reserved_agent_id: str,
) -> None:
    registry = _registry()
    accounts = tuple(
        replace(item, base_agent_id=reserved_agent_id)
        if item.github_account_id == "account-author"
        else item
        for item in registry.accounts
    )
    bindings = tuple(
        replace(item, subject_id=reserved_agent_id)
        if item.binding_id == "author-binding"
        else item
        for item in registry.bindings
    )
    groups = tuple(
        replace(item, agent_id=reserved_agent_id)
        if item.binding_id == "group-author"
        else item
        for item in registry.control_group_bindings
    )

    with pytest.raises(IdentityError, match="reserved system account"):
        IdentityRegistry(
            accounts=accounts,
            bindings=bindings,
            control_group_bindings=groups,
        )


def test_assignment_mutated_after_validation_is_rejected() -> None:
    role = TriageRole(
        role_id=triage_role_id("issue-42"),
        issue_id="issue-42",
        funding_source="free",
    )
    assignment = _assignment()
    object.__setattr__(assignment, "snapshot", "forged assignment snapshot")

    with pytest.raises(IntakeError, match="snapshot_hash"):
        assign_triage(IntakeState(), role, assignment, registry=_registry())


def test_registry_rejects_a_caller_recomputed_integrity_marker() -> None:
    role = TriageRole(
        role_id=triage_role_id("issue-42"),
        issue_id="issue-42",
        funding_source="free",
    )
    registry = _registry()
    object.__setattr__(registry.accounts[0], "owner", "forged-owner")
    object.__setattr__(registry, "_integrity_hash", registry.state_hash)

    with pytest.raises(IntakeError, match="changed after validation"):
        assign_triage(IntakeState(), role, _assignment(), registry=registry)


def test_restored_triage_must_belong_to_its_roles_issue() -> None:
    role = TriageRole(
        role_id=triage_role_id("issue-42"),
        issue_id="issue-42",
        funding_source="free",
    )

    with pytest.raises(IntakeError, match="Triage"):
        IntakeState(
            triage_roles=(role,),
            triage_assignments=(_assignment(),),
            triages=(replace(_triage(), issue_id="issue-other"),),
        )


@pytest.mark.parametrize("principal_source", ["balance", "registry"])
def test_triage_role_id_cannot_collide_with_an_account_principal(
    principal_source: str,
) -> None:
    role = TriageRole(
        role_id=triage_role_id("issue-42"),
        issue_id="issue-42",
        funding_source="free",
    )
    state = IntakeState()
    registry = _registry()
    if principal_source == "balance":
        state = IntakeState(balances=(AccountBalance(role.role_id, 0),))
    else:
        registry = IdentityRegistry(
            accounts=(
                *registry.accounts,
                GitHubAccount("account-collision", "collision", role.role_id),
            ),
            bindings=(
                *registry.bindings,
                Binding(
                    "binding-collision",
                    "agent",
                    "account-collision",
                    role.role_id,
                    1,
                    NOW - timedelta(days=1),
                ),
            ),
            control_group_bindings=registry.control_group_bindings,
        )

    with pytest.raises(IntakeError, match="role_id"):
        assign_triage(state, role, _assignment(), registry=registry)


def _triage(
    *,
    body: str = "Exact Issue body",
    issue_revision_id: str = "issue-revision-1",
    revision_id: str = "triage-revision-1",
) -> TriageRecord:
    snapshot = f"triage for {issue_revision_id}"
    return TriageRecord(
        role_id=triage_role_id("issue-42"),
        assignment_generation=1,
        reviewer_agent_id="agent-reviewer",
        reviewer_github_account_id="account-reviewer",
        reviewer_binding_id="binding-reviewer",
        reviewer_binding_version=1,
        issue_id="issue-42",
        issue_revision_id=issue_revision_id,
        body_hash=_hash(body),
        route="direct-pr",
        risks=("no kill risk",),
        comment_id="comment-triage",
        revision_id=revision_id,
        snapshot=snapshot,
        snapshot_hash=_hash(snapshot),
        effective_at=NOW,
    )


def _assignment() -> TriageAssignment:
    snapshot = "Agent0 assigns Triage"
    return TriageAssignment(
        assignment_id="assignment-1",
        role_id=triage_role_id("issue-42"),
        generation=1,
        reviewer_agent_id="agent-reviewer",
        reviewer_github_account_id="account-reviewer",
        reviewer_binding_id="binding-reviewer",
        reviewer_binding_version=1,
        agent0_github_account_id="account-agent0",
        agent0_binding_id="binding-agent0-role",
        agent0_binding_version=1,
        comment_id="assignment-comment",
        revision_id="assignment-revision",
        snapshot=snapshot,
        snapshot_hash=_hash(snapshot),
        effective_at=NOW - timedelta(minutes=2),
        idempotency_key="triage-assignment:issue-42:1",
    )


def _completion(triage: TriageRecord, *, suffix: str) -> TriageCompletion:
    snapshot = f"Agent0 completes Triage {suffix}"
    return TriageCompletion(
        completion_id=f"completion-{suffix}",
        role_id=triage.role_id,
        assignment_generation=triage.assignment_generation,
        triage_revision_id=triage.revision_id,
        reviewer_agent_id=triage.reviewer_agent_id,
        agent0_github_account_id="account-agent0",
        agent0_binding_id="binding-agent0-role",
        agent0_binding_version=1,
        comment_id=f"completion-comment-{suffix}",
        revision_id=f"completion-revision-{suffix}",
        snapshot=snapshot,
        snapshot_hash=_hash(snapshot),
        effective_at=NOW + timedelta(minutes=1),
        idempotency_key=f"triage-completion:issue-42:{suffix}",
    )


def test_free_triage_and_body_revision_retry_never_create_a_payout() -> None:
    role = TriageRole(
        role_id=triage_role_id("issue-42"),
        issue_id="issue-42",
        funding_source="free",
    )
    assignment = _assignment()
    state = assign_triage(IntakeState(), role, assignment, registry=_registry())
    first = _triage()
    state = record_triage(state, first, registry=_registry())
    state = complete_triage(state, _completion(first, suffix="1"), registry=_registry())
    second = _triage(
        body="Edited Issue body",
        issue_revision_id="issue-revision-2",
        revision_id="triage-revision-2",
    )
    state = record_triage(
        state,
        second,
        registry=_registry(),
    )
    state = complete_triage(
        state, _completion(second, suffix="2"), registry=_registry()
    )

    assert len(state.triages) == 2
    assert len(state.triage_completions) == 2
    assert state.escrows == state.ledger == ()
    assert assign_triage(state, role, assignment, registry=_registry()) == state


def test_assignment_replay_rejects_changed_role_funding() -> None:
    free_role = TriageRole(
        role_id=triage_role_id("issue-42"),
        issue_id="issue-42",
        funding_source="free",
    )
    assignment = _assignment()
    state = assign_triage(
        IntakeState(balances=(AccountBalance("treasury", 2),)),
        free_role,
        assignment,
        registry=_registry(),
    )
    paid_role = TriageRole(
        role_id=free_role.role_id,
        issue_id=free_role.issue_id,
        funding_source="treasury",
        amount_wea=1,
        escrow_id=triage_escrow_id(free_role.issue_id),
    )

    with pytest.raises(IntakeError, match="role_id"):
        assign_triage(state, paid_role, assignment, registry=_registry())

    assert state.balance("treasury") == 2
    assert state.escrows == state.ledger == ()


def test_one_assignment_source_revision_cannot_fund_two_roles() -> None:
    first_role = TriageRole(
        role_id=triage_role_id("issue-42"),
        issue_id="issue-42",
        funding_source="treasury",
        amount_wea=1,
        escrow_id=triage_escrow_id("issue-42"),
    )
    state = assign_triage(
        IntakeState(balances=(AccountBalance("treasury", 3),)),
        first_role,
        _assignment(),
        registry=_registry(),
    )
    second_role = TriageRole(
        role_id=triage_role_id("issue-43"),
        issue_id="issue-43",
        funding_source="treasury",
        amount_wea=1,
        escrow_id=triage_escrow_id("issue-43"),
    )
    reused_source = replace(
        _assignment(),
        assignment_id="assignment-other-role",
        role_id=second_role.role_id,
        idempotency_key="triage-assignment:issue-43:1",
    )

    with pytest.raises(IntakeError, match="source revision"):
        assign_triage(state, second_role, reused_source, registry=_registry())

    assert state.balance("treasury") == 2
    assert len(state.escrows) == len(state.ledger) == 1


def test_reassignment_must_follow_prior_triage_and_completion_evidence() -> None:
    role = TriageRole(
        role_id=triage_role_id("issue-42"),
        issue_id="issue-42",
        funding_source="treasury",
        amount_wea=1,
        escrow_id=triage_escrow_id("issue-42"),
    )
    state = assign_triage(
        IntakeState(balances=(AccountBalance("treasury", 2),)),
        role,
        _assignment(),
        registry=_registry(),
    )
    triage = _triage()
    state = record_triage(state, triage, registry=_registry())
    state = complete_triage(
        state, _completion(triage, suffix="first"), registry=_registry()
    )
    snapshot = "Backdated reassignment"
    backdated = replace(
        _assignment(),
        assignment_id="assignment-backdated",
        generation=2,
        comment_id="assignment-comment-backdated",
        revision_id="assignment-revision-backdated",
        snapshot=snapshot,
        snapshot_hash=_hash(snapshot),
        effective_at=NOW - timedelta(minutes=1),
        idempotency_key="triage-assignment:issue-42:2",
    )

    with pytest.raises(IntakeError, match="prior role evidence"):
        assign_triage(state, role, backdated, registry=_registry())

    assert len(state.triage_assignments) == 1
    assert len(state.triage_completions) == 1
    assert len([item for item in state.ledger if item.kind == "triage-payout"]) == 1


def test_reassignment_requires_the_prior_generation_to_be_terminal() -> None:
    role = TriageRole(
        role_id=triage_role_id("issue-42"),
        issue_id="issue-42",
        funding_source="free",
    )
    state = assign_triage(IntakeState(), role, _assignment(), registry=_registry())
    state = record_triage(state, _triage(), registry=_registry())
    snapshot = "Agent0 reassigns before completing prior work"
    premature = replace(
        _assignment(),
        assignment_id="assignment-2",
        generation=2,
        comment_id="assignment-comment-2",
        revision_id="assignment-revision-2",
        snapshot=snapshot,
        snapshot_hash=_hash(snapshot),
        effective_at=NOW + timedelta(minutes=2),
        idempotency_key="triage-assignment:issue-42:2",
    )

    with pytest.raises(IntakeError, match="prior generation must be terminal"):
        assign_triage(state, role, premature, registry=_registry())

    with pytest.raises(IntakeError, match="prior generation must be terminal"):
        IntakeState(
            triage_roles=state.triage_roles,
            triage_assignments=tuple(
                sorted(
                    (*state.triage_assignments, premature),
                    key=lambda item: item.assignment_id,
                )
            ),
            triages=state.triages,
        )


def test_paid_completion_reauthorizes_restored_assignment_and_triage() -> None:
    role = TriageRole(
        role_id=triage_role_id("issue-42"),
        issue_id="issue-42",
        funding_source="treasury",
        amount_wea=1,
        escrow_id=triage_escrow_id("issue-42"),
    )
    state = assign_triage(
        IntakeState(balances=(AccountBalance("treasury", 2),)),
        role,
        _assignment(),
        registry=_registry(),
    )
    triage = _triage()
    state = record_triage(state, triage, registry=_registry())
    forged_assignment = replace(
        state.triage_assignments[0],
        reviewer_agent_id="ghost",
        reviewer_github_account_id="ghost-account",
        reviewer_binding_id="ghost-binding",
    )
    forged_triage = replace(
        triage,
        reviewer_agent_id="ghost",
        reviewer_github_account_id="ghost-account",
        reviewer_binding_id="ghost-binding",
    )
    restored = replace(
        state,
        triage_assignments=(forged_assignment,),
        triages=(forged_triage,),
    )
    completion = replace(
        _completion(forged_triage, suffix="ghost"),
        reviewer_agent_id="ghost",
    )

    with pytest.raises(IntakeError, match="reviewer"):
        complete_triage(restored, completion, registry=_registry())

    assert not any(item.account_id == "ghost" for item in restored.balances)
    assert not any(item.kind == "triage-payout" for item in restored.ledger)


def test_triage_role_is_the_single_deterministic_payment_slot_for_an_issue() -> None:
    with pytest.raises(IntakeError, match="role_id"):
        TriageRole(
            role_id="triage-role-second",
            issue_id="issue-42",
            funding_source="treasury",
            amount_wea=1,
            escrow_id=triage_escrow_id("issue-other"),
        )


def test_triage_assignment_and_completion_require_exact_agent0_binding_version() -> (
    None
):
    role = TriageRole(
        role_id=triage_role_id("issue-42"),
        issue_id="issue-42",
        funding_source="free",
    )
    with pytest.raises(IntakeError, match="agent0_binding_version"):
        assign_triage(
            IntakeState(),
            role,
            replace(_assignment(), agent0_binding_version=2),
            registry=_registry(),
        )

    state = assign_triage(IntakeState(), role, _assignment(), registry=_registry())
    triage = _triage()
    state = record_triage(state, triage, registry=_registry())
    with pytest.raises(IntakeError, match="agent0_binding_version"):
        complete_triage(
            state,
            replace(_completion(triage, suffix="wrong"), agent0_binding_version=2),
            registry=_registry(),
        )


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("reviewer_github_account_id", "account-unknown", "reviewer_agent_id"),
        ("reviewer_github_account_id", "account-author", "reviewer_agent_id"),
        ("reviewer_binding_version", 2, "reviewer_binding_version"),
    ],
)
def test_triage_assignment_requires_exact_reviewer_identity(
    field: str,
    value: object,
    error: str,
) -> None:
    role = TriageRole(
        role_id=triage_role_id("issue-42"),
        issue_id="issue-42",
        funding_source="free",
    )
    with pytest.raises(IntakeError, match=error):
        assign_triage(
            IntakeState(),
            role,
            replace(_assignment(), **{field: value}),
            registry=_registry(),
        )


def test_triage_output_requires_the_assigned_reviewer_identity_and_order() -> None:
    role = TriageRole(
        role_id=triage_role_id("issue-42"),
        issue_id="issue-42",
        funding_source="free",
    )
    late_assignment = replace(
        _assignment(),
        effective_at=NOW + timedelta(seconds=30),
    )
    state = assign_triage(IntakeState(), role, late_assignment, registry=_registry())
    with pytest.raises(IntakeError, match="must not precede"):
        record_triage(state, _triage(), registry=_registry())

    ordered = assign_triage(IntakeState(), role, _assignment(), registry=_registry())
    with pytest.raises(IntakeError, match="role_id"):
        record_triage(
            ordered,
            replace(_triage(), reviewer_github_account_id="account-author"),
            registry=_registry(),
        )
    with pytest.raises(IntakeError, match="role_id"):
        record_triage(
            ordered,
            replace(_triage(), reviewer_binding_version=2),
            registry=_registry(),
        )


def test_same_triage_revision_cannot_receive_two_completion_declarations() -> None:
    role = TriageRole(
        role_id=triage_role_id("issue-42"),
        issue_id="issue-42",
        funding_source="free",
    )
    state = assign_triage(IntakeState(), role, _assignment(), registry=_registry())
    triage = _triage()
    state = record_triage(state, triage, registry=_registry())
    state = complete_triage(
        state, _completion(triage, suffix="first"), registry=_registry()
    )

    with pytest.raises(IntakeError, match="triage_revision_id"):
        complete_triage(
            state,
            _completion(triage, suffix="second"),
            registry=_registry(),
        )


def test_exact_completion_replay_remains_idempotent_after_reassignment() -> None:
    role = TriageRole(
        role_id=triage_role_id("issue-42"),
        issue_id="issue-42",
        funding_source="free",
    )
    state = assign_triage(IntakeState(), role, _assignment(), registry=_registry())
    triage = _triage()
    state = record_triage(state, triage, registry=_registry())
    completion = _completion(triage, suffix="first")
    state = complete_triage(state, completion, registry=_registry())
    second_assignment = replace(
        _assignment(),
        assignment_id="assignment-2",
        generation=2,
        comment_id="assignment-comment-2",
        revision_id="assignment-revision-2",
        snapshot="Agent0 reassigns Triage",
        snapshot_hash=_hash("Agent0 reassigns Triage"),
        effective_at=NOW + timedelta(minutes=2),
        idempotency_key="triage-assignment:issue-42:2",
    )
    state = assign_triage(state, role, second_assignment, registry=_registry())

    assert complete_triage(state, completion, registry=_registry()) == state


def test_same_timestamp_completions_use_canonical_source_order_for_paid_role() -> None:
    role = TriageRole(
        role_id=triage_role_id("issue-42"),
        issue_id="issue-42",
        funding_source="treasury",
        amount_wea=1,
        escrow_id=triage_escrow_id("issue-42"),
    )
    state = assign_triage(
        IntakeState(balances=(AccountBalance("treasury", 2),)),
        role,
        _assignment(),
        registry=_registry(),
    )
    first_triage = _triage()
    state = record_triage(state, first_triage, registry=_registry())
    first_completion = replace(
        _completion(first_triage, suffix="z"),
        comment_id="comment-a-completion",
        revision_id="revision-a-completion",
    )
    state = complete_triage(state, first_completion, registry=_registry())

    second_assignment = replace(
        _assignment(),
        assignment_id="assignment-2",
        generation=2,
        reviewer_agent_id="agent-author",
        reviewer_github_account_id="account-author",
        reviewer_binding_id="binding-author",
        comment_id="comment-b-assignment",
        revision_id="revision-b-assignment",
        snapshot="Agent0 reassigns Triage",
        snapshot_hash=_hash("Agent0 reassigns Triage"),
        effective_at=first_completion.effective_at,
        idempotency_key="triage-assignment:issue-42:2",
    )
    state = assign_triage(state, role, second_assignment, registry=_registry())
    second_triage = replace(
        _triage(revision_id="triage-revision-2"),
        assignment_generation=2,
        reviewer_agent_id="agent-author",
        reviewer_github_account_id="account-author",
        reviewer_binding_id="binding-author",
        comment_id="comment-c-triage",
        snapshot="second Triage",
        snapshot_hash=_hash("second Triage"),
        effective_at=first_completion.effective_at,
    )
    state = record_triage(state, second_triage, registry=_registry())
    second_completion = replace(
        _completion(second_triage, suffix="a"),
        comment_id="comment-d-completion",
        revision_id="revision-d-completion",
        effective_at=first_completion.effective_at,
    )

    state = complete_triage(state, second_completion, registry=_registry())

    assert len(state.triage_completions) == 2
    assert state.balance("agent-reviewer") == 1
    assert not any(item.account_id == "agent-author" for item in state.balances)


def test_treasury_triage_has_its_own_atomic_escrow_and_no_task_bank() -> None:
    role = TriageRole(
        role_id=triage_role_id("issue-42"),
        issue_id="issue-42",
        funding_source="treasury",
        amount_wea=1,
        escrow_id=triage_escrow_id("issue-42"),
    )
    initial = IntakeState(balances=(AccountBalance("treasury", 2),))
    state = assign_triage(initial, role, _assignment(), registry=_registry())
    first = _triage()
    state = record_triage(state, first, registry=_registry())
    state = complete_triage(state, _completion(first, suffix="1"), registry=_registry())
    second = _triage(
        body="Edited Issue body",
        issue_revision_id="issue-revision-2",
        revision_id="triage-revision-2",
    )
    state = record_triage(
        state,
        second,
        registry=_registry(),
    )
    state = complete_triage(
        state, _completion(second, suffix="2"), registry=_registry()
    )

    assert state.balance("treasury") == 1
    assert state.balance("agent-reviewer") == 1
    assert [(item.kind, item.amount_wea) for item in state.escrows] == [
        ("triage-role", 1)
    ]
    assert [item.kind for item in state.ledger] == [
        "triage-treasury",
        "triage-payout",
    ]
    assert state.escrows[0].settlement_transition_id == (
        f"triage-payout:{triage_role_id('issue-42')}"
    )
    assert len(state.triages) == 2
    assert len(state.triage_completions) == 2
    assert state.contracts == state.tasks == ()

    with pytest.raises(TypeError, match="treasury_account_id"):
        assign_triage(
            initial,
            role,
            _assignment(),
            registry=_registry(),
            treasury_account_id="agent-author",  # type: ignore[call-arg]
        )

    with pytest.raises(IntakeError, match="escrow_id"):
        TriageRole(
            role_id=triage_role_id("issue-42"),
            issue_id="issue-42",
            funding_source="treasury",
            amount_wea=1,
            escrow_id="agent-reviewer",
        )

    collision_id = triage_escrow_id("issue-42")
    with pytest.raises(IntakeError, match="escrow_id"):
        assign_triage(
            IntakeState(
                balances=(
                    AccountBalance("treasury", 2),
                    AccountBalance(collision_id, 0),
                )
            ),
            role,
            _assignment(),
            registry=_registry(),
        )

    registry = _registry()
    with pytest.raises(IdentityError, match="reserved system account"):
        IdentityRegistry(
            accounts=(
                *registry.accounts,
                GitHubAccount("account-collision", "collision", collision_id),
            ),
            bindings=(
                *registry.bindings,
                Binding(
                    "binding-collision",
                    "agent",
                    "account-collision",
                    collision_id,
                    1,
                    NOW - timedelta(days=1),
                ),
            ),
            control_group_bindings=(
                *registry.control_group_bindings,
                ControlGroupBinding(
                    "group-collision",
                    collision_id,
                    "owner-collision",
                    1,
                    NOW - timedelta(days=1),
                ),
            ),
        )

    with pytest.raises(IntakeError, match="treasury_balance"):
        assign_triage(
            IntakeState(balances=(AccountBalance("treasury", 0),)),
            role,
            _assignment(),
            registry=_registry(),
        )


def test_treasury_principal_is_not_redirected_by_module_globals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        TriageRole.__post_init__.__globals__,
        "_TRIAGE_TREASURY_ACCOUNT_ID",
        "agent-author",
    )
    role = TriageRole(
        role_id=triage_role_id("issue-42"),
        issue_id="issue-42",
        funding_source="treasury",
        amount_wea=1,
        escrow_id=triage_escrow_id("issue-42"),
    )

    with pytest.raises(IntakeError, match="treasury_balance"):
        assign_triage(
            IntakeState(
                balances=(
                    AccountBalance("agent-author", 10),
                    AccountBalance("treasury", 0),
                )
            ),
            role,
            _assignment(),
            registry=_registry(),
        )
