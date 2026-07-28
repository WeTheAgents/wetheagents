from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from wea_vnext.identity import (
    Binding,
    ControlGroupBinding,
    GitHubAccount,
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
    assert assign_triage(state, role, assignment, registry=_registry()) is state


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

    assert complete_triage(state, completion, registry=_registry()) is state


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
    collision_registry = IdentityRegistry(
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
    with pytest.raises(IntakeError, match="escrow_id"):
        assign_triage(
            initial,
            role,
            _assignment(),
            registry=collision_registry,
        )

    with pytest.raises(IntakeError, match="treasury_balance"):
        assign_triage(
            IntakeState(balances=(AccountBalance("treasury", 0),)),
            role,
            _assignment(),
            registry=_registry(),
        )
