from __future__ import annotations

import hashlib
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone

import pytest

from wea_vnext.engine import installed_executor
from wea_vnext.identity import (
    Binding,
    ControlGroupBinding,
    GitHubAccount,
    IdentityError,
    IdentityRegistry,
)
from wea_vnext.intake import (
    AccountBalance,
    AuthorConsent,
    ContractCandidate,
    ContractReadiness,
    DraftIssue,
    IntakeError,
    IntakeState,
    MechanicTerms,
    OrdinaryContract,
    RouteOverride,
    TriageAssignment,
    TriageCompletion,
    TriageRecord,
    TriageRole,
    activate_contract,
    assign_triage,
    complete_triage,
    ordinary_contract_id,
    record_author_consent,
    record_contract_readiness,
    record_route_override,
    record_triage,
    triage_role_id,
)

NOW = datetime(2026, 7, 28, 10, tzinfo=timezone.utc)
TRIAGE_AT = NOW - timedelta(minutes=20)
CONSENT_AT = NOW - timedelta(minutes=5)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _registry() -> IdentityRegistry:
    accounts = (
        GitHubAccount("account-agent0", "agent0", "agent0-base"),
        GitHubAccount("account-author", "author", "agent-author"),
        GitHubAccount("account-operator", "operator", "operator-base"),
        GitHubAccount("account-reviewer", "reviewer", "agent-reviewer"),
    )
    started = NOW - timedelta(days=1)
    return IdentityRegistry(
        accounts=accounts,
        bindings=(
            Binding(
                "agent0-base-binding",
                "agent",
                "account-agent0",
                "agent0-base",
                1,
                started,
            ),
            Binding(
                "agent0-role-binding",
                "agent0",
                "account-agent0",
                "agent0@system",
                1,
                started,
            ),
            Binding(
                "author-binding", "agent", "account-author", "agent-author", 1, started
            ),
            Binding(
                "operator-base-binding",
                "agent",
                "account-operator",
                "operator-base",
                1,
                started,
            ),
            Binding(
                "operator-role-binding",
                "operator",
                "account-operator",
                "operator",
                1,
                started,
            ),
            Binding(
                "reviewer-binding",
                "agent",
                "account-reviewer",
                "agent-reviewer",
                1,
                started,
            ),
        ),
        control_group_bindings=(
            ControlGroupBinding(
                "group-agent0", "agent0-base", "owner-agent0", 1, started
            ),
            ControlGroupBinding(
                "group-author", "agent-author", "owner-author", 1, started
            ),
            ControlGroupBinding(
                "group-operator", "operator-base", "owner-operator", 1, started
            ),
            ControlGroupBinding(
                "group-reviewer", "agent-reviewer", "owner-reviewer", 1, started
            ),
        ),
    )


def _terms() -> MechanicTerms:
    return MechanicTerms(
        mechanic="pod",
        review_fee_wea=1,
        payout_vector=(2,),
        config={"mode": "finite", "payout_wea": 2, "slots": 1},
    )


def _draft(*, profile: str = "direct-pr") -> DraftIssue:
    return DraftIssue(
        issue_id="issue-42",
        issue_revision_id="issue-revision-1",
        creator_github_account_id="account-author",
        author_agent_id="agent-author",
        body="Exact Issue body",
        bank_wea=3,
        profile=profile,
        terms=_terms(),
    )


def _triage(
    *,
    route: str = "direct-pr",
    issue_revision_id: str = "issue-revision-1",
    revision_id: str = "triage-revision-1",
) -> TriageRecord:
    snapshot = f"triage route={route}"
    return TriageRecord(
        role_id=triage_role_id("issue-42"),
        assignment_generation=1,
        reviewer_agent_id="agent-reviewer",
        reviewer_github_account_id="account-reviewer",
        reviewer_binding_id="reviewer-binding",
        reviewer_binding_version=1,
        issue_id="issue-42",
        issue_revision_id=issue_revision_id,
        body_hash=_hash("Exact Issue body"),
        route=route,
        risks=("none",),
        comment_id="triage-comment",
        revision_id=revision_id,
        snapshot=snapshot,
        snapshot_hash=_hash(snapshot),
        effective_at=TRIAGE_AT,
    )


def _assignment() -> TriageAssignment:
    snapshot = "Agent0 assigns Triage"
    return TriageAssignment(
        assignment_id="assignment-1",
        role_id=triage_role_id("issue-42"),
        generation=1,
        reviewer_agent_id="agent-reviewer",
        reviewer_github_account_id="account-reviewer",
        reviewer_binding_id="reviewer-binding",
        reviewer_binding_version=1,
        agent0_github_account_id="account-agent0",
        agent0_binding_id="agent0-role-binding",
        agent0_binding_version=1,
        comment_id="assignment-comment",
        revision_id="assignment-revision",
        snapshot=snapshot,
        snapshot_hash=_hash(snapshot),
        effective_at=TRIAGE_AT - timedelta(minutes=1),
        idempotency_key="triage-assignment:issue-42:1",
    )


def _completion(
    triage: TriageRecord,
    *,
    suffix: str | None = None,
) -> TriageCompletion:
    suffix = suffix or triage.revision_id
    snapshot = f"Agent0 completes {triage.revision_id}"
    return TriageCompletion(
        completion_id=f"completion-{suffix}",
        role_id=triage.role_id,
        assignment_generation=triage.assignment_generation,
        triage_revision_id=triage.revision_id,
        reviewer_agent_id=triage.reviewer_agent_id,
        agent0_github_account_id="account-agent0",
        agent0_binding_id="agent0-role-binding",
        agent0_binding_version=1,
        comment_id=f"completion-comment-{suffix}",
        revision_id=f"completion-revision-{suffix}",
        snapshot=snapshot,
        snapshot_hash=_hash(snapshot),
        effective_at=TRIAGE_AT + timedelta(minutes=1),
        idempotency_key=f"triage-completion:issue-42:{suffix}",
    )


def _consent(
    draft: DraftIssue,
    triage: TriageRecord,
    *,
    consent_id: str = "consent-1",
    effective_at: datetime = CONSENT_AT,
    override_id: str | None = None,
) -> AuthorConsent:
    runtime = installed_executor("0.6.3").reference
    snapshot = f"consent {consent_id}"
    return AuthorConsent(
        consent_id=consent_id,
        author_agent_id="agent-author",
        github_account_id="account-author",
        account_binding_id="author-binding",
        account_binding_version=1,
        comment_id=f"comment-{consent_id}",
        revision_id=f"revision-{consent_id}",
        snapshot=snapshot,
        snapshot_hash=_hash(snapshot),
        effective_at=effective_at,
        issue_id=draft.issue_id,
        issue_revision_id=draft.issue_revision_id,
        body_hash=draft.body_hash,
        bank_wea=draft.bank_wea,
        profile=draft.profile,
        mechanic=draft.terms.mechanic,
        mechanic_config_hash=draft.terms.config_hash,
        ruleset_hash=runtime.ruleset_hash,
        tide_interface_version=runtime.tide_interface_version,
        executor_manifest_hash=runtime.executor_manifest_hash,
        triage_role_id=triage.role_id,
        triage_revision_id=triage.revision_id,
        triage_snapshot_hash=triage.snapshot_hash,
        route=draft.profile,
        override_id=override_id,
    )


def _readiness(
    consent: AuthorConsent,
    triage: TriageRecord,
    *,
    effective_at: datetime | None = None,
) -> ContractReadiness:
    readiness_id = f"ready-{consent.consent_id}"
    snapshot = f"readiness {readiness_id}"
    return ContractReadiness(
        readiness_id=readiness_id,
        issue_id=consent.issue_id,
        agent0_github_account_id="account-agent0",
        agent0_binding_id="agent0-role-binding",
        agent0_binding_version=1,
        comment_id=f"comment-{readiness_id}",
        revision_id=f"revision-{readiness_id}",
        snapshot=snapshot,
        snapshot_hash=_hash(snapshot),
        effective_at=effective_at or consent.effective_at + timedelta(minutes=1),
        consent_id=consent.consent_id,
        consent_revision_id=consent.revision_id,
        triage_role_id=triage.role_id,
        triage_revision_id=triage.revision_id,
        triage_snapshot_hash=triage.snapshot_hash,
        override_id=consent.override_id,
    )


def _state(
    draft: DraftIssue,
    triage: TriageRecord,
    consent: AuthorConsent,
    *,
    balance: int = 10,
) -> IntakeState:
    state = _triaged_state(draft, triage, balance=balance)
    state = record_author_consent(state, consent, registry=_registry())
    return record_contract_readiness(
        state,
        _readiness(consent, triage),
        registry=_registry(),
    )


def _triaged_state(
    draft: DraftIssue,
    triage: TriageRecord,
    *,
    balance: int = 10,
) -> IntakeState:
    state = IntakeState(balances=(AccountBalance("agent-author", balance),))
    state = assign_triage(
        state,
        TriageRole(
            role_id=triage.role_id,
            issue_id=draft.issue_id,
            funding_source="free",
        ),
        _assignment(),
        registry=_registry(),
    )
    state = record_triage(state, triage, registry=_registry())
    return complete_triage(state, _completion(triage), registry=_registry())


def _activate(state: IntakeState, draft: DraftIssue, consent_id: str = "consent-1"):
    return activate_contract(
        state,
        ContractCandidate(
            ordinary_contract_id(draft.issue_id),
            draft,
            draft.profile,
            "triage-revision-1",
        ),
        consent_id=consent_id,
        payer_agent_id="agent-author",
        payer_github_account_id="account-author",
        effective_at=NOW,
        readiness_id=f"ready-{consent_id}",
        registry=_registry(),
    )


def test_exact_activation_atomically_creates_one_debit_escrow_contract_and_task() -> (
    None
):
    draft = _draft()
    triage = _triage()
    consent = _consent(draft, triage)
    before = _state(draft, triage, consent)

    result = _activate(before, draft)

    assert result.created is True
    assert result.state.balance("agent-author") == 7
    assert len(result.state.contracts) == len(result.state.tasks) == 1
    assert len(result.state.escrows) == len(result.state.ledger) == 1
    assert result.escrow.refund_agent_id == "agent-author"
    assert result.task.stage == "pr-intake"
    again = _activate(result.state, draft)
    assert again.created is False
    assert again.state == result.state
    assert len(again.state.ledger) == 1

    with pytest.raises(FrozenInstanceError):
        result.contract.bank_wea = 4  # type: ignore[misc]
    with pytest.raises(IntakeError, match="atomic"):
        replace(result.state, tasks=())


def test_activation_runtime_is_owned_by_the_verified_facade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_runtime = (
        "1" * 64,
        "forged-interface",
        "2" * 64,
    )
    monkeypatch.setitem(
        OrdinaryContract.__post_init__.__globals__, "_VERIFIED_RUNTIME", fake_runtime
    )
    draft = _draft()
    triage = _triage()

    result = _activate(_state(draft, triage, _consent(draft, triage)), draft)

    assert result.contract.executor_manifest_hash == (
        installed_executor("0.6.3").reference.executor_manifest_hash
    )


@pytest.mark.parametrize(
    ("field", "forged_value"),
    (
        ("task_id", "task:forged"),
        ("transition_id", "contract-bank:forged"),
    ),
)
def test_restored_state_requires_deterministic_activation_record_ids(
    field: str,
    forged_value: str,
) -> None:
    draft = _draft()
    triage = _triage()
    result = _activate(_state(draft, triage, _consent(draft, triage)), draft)

    if field == "task_id":
        with pytest.raises(IntakeError, match="money does not match"):
            replace(result.state, tasks=(replace(result.task, task_id=forged_value),))
    else:
        with pytest.raises(IntakeError, match="money does not match"):
            replace(
                result.state,
                ledger=(replace(result.debit, transition_id=forged_value),),
            )


def test_state_construction_seal_is_not_exposed_through_module_globals() -> None:
    module_globals = IntakeState.__post_init__.__globals__

    assert "_STATE_SEALS" not in module_globals
    assert "_remember_state_seal" not in module_globals
    assert "_state_seal" not in module_globals


def test_activation_rejects_a_balance_mutated_after_state_validation() -> None:
    draft = _draft()
    triage = _triage()
    consent = _consent(draft, triage)
    state = _state(draft, triage, consent, balance=1)
    object.__setattr__(state.balances[0], "amount_wea", 10)
    object.__setattr__(state, "_integrity_hash", state.state_hash)

    with pytest.raises(IntakeError, match="changed after validation"):
        _activate(state, draft)


def test_restored_state_rejects_contract_terms_not_bound_to_consent() -> None:
    draft = _draft()
    triage = _triage()
    result = _activate(_state(draft, triage, _consent(draft, triage)), draft)
    forged_body = "Different unconsented body"
    forged_contract = replace(
        result.contract,
        issue_revision_id="issue-revision-forged",
        body=forged_body,
        body_hash=_hash(forged_body),
    )

    with pytest.raises(IntakeError, match="evidence does not match"):
        replace(result.state, contracts=(forged_contract,))


def test_restored_state_rejects_completion_that_precedes_triage() -> None:
    draft = _draft()
    triage = _triage()
    state = _triaged_state(draft, triage)
    early_completion = replace(
        state.triage_completions[0],
        effective_at=triage.effective_at - timedelta(seconds=1),
    )

    with pytest.raises(IntakeError, match="triage completion"):
        replace(state, triage_completions=(early_completion,))


def test_restored_state_rejects_task_escrow_with_foreign_funding_source() -> None:
    draft = _draft()
    triage = _triage()
    result = _activate(_state(draft, triage, _consent(draft, triage)), draft)
    forged_escrow = replace(result.escrow, source_account_id="agent-attacker")

    with pytest.raises(IntakeError, match="money does not match"):
        replace(result.state, escrows=(forged_escrow,))


def test_restored_state_requires_the_deterministic_task_escrow_id() -> None:
    draft = _draft()
    triage = _triage()
    result = _activate(_state(draft, triage, _consent(draft, triage)), draft)
    forged_escrow = replace(result.escrow, escrow_id="agent-reviewer")
    forged_debit = replace(result.debit, credit_account_id="agent-reviewer")

    with pytest.raises(IntakeError, match="money does not match"):
        replace(
            result.state,
            escrows=(forged_escrow,),
            ledger=(forged_debit,),
        )


@pytest.mark.parametrize("record_kind", ("assignment", "completion"))
def test_activation_reauthorizes_restored_triage_agent0_evidence(
    record_kind: str,
) -> None:
    draft = _draft()
    triage = _triage()
    state = _state(draft, triage, _consent(draft, triage))
    if record_kind == "assignment":
        state = replace(
            state,
            triage_assignments=(
                replace(
                    state.triage_assignments[0],
                    agent0_github_account_id="account-author",
                    agent0_binding_id="author-binding",
                ),
            ),
        )
    else:
        state = replace(
            state,
            triage_completions=(
                replace(
                    state.triage_completions[0],
                    agent0_github_account_id="account-author",
                    agent0_binding_id="author-binding",
                ),
            ),
        )

    with pytest.raises(IntakeError, match="agent0"):
        _activate(state, draft)


def test_same_issue_cannot_be_reactivated_under_a_caller_chosen_contract_id() -> None:
    draft = _draft()
    triage = _triage()
    activated = _activate(_state(draft, triage, _consent(draft, triage)), draft)

    with pytest.raises(IntakeError, match="contract_id"):
        ContractCandidate(
            "caller-selected-second-contract",
            draft,
            draft.profile,
            triage.revision_id,
        )

    assert len(activated.state.contracts) == 1
    assert len(activated.state.ledger) == 1
    assert activated.state.balance("agent-author") == 7


def test_s_02a_insufficient_author_balance_leaves_every_activation_object_absent() -> (
    None
):
    draft = _draft()
    triage = _triage()
    state = _state(draft, triage, _consent(draft, triage), balance=2)
    before = state.state_hash

    with pytest.raises(IntakeError, match="author_balance"):
        _activate(state, draft)

    assert state.state_hash == before
    assert state.contracts == state.tasks == state.escrows == state.ledger == ()


def test_task_escrow_cannot_collide_with_registered_identity_without_balance() -> None:
    draft = _draft()
    triage = _triage()
    state = _state(draft, triage, _consent(draft, triage))
    collision_id = f"task-escrow:{ordinary_contract_id(draft.issue_id)}"
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

    assert state.balance("agent-author") == 10
    assert state.contracts == state.tasks == state.escrows == state.ledger == ()


def test_s_02c_third_party_payer_is_rejected_without_escrow() -> None:
    draft = _draft()
    triage = _triage()
    state = _state(draft, triage, _consent(draft, triage))

    with pytest.raises(IntakeError, match="payer_agent_id"):
        activate_contract(
            state,
            ContractCandidate(
                ordinary_contract_id(draft.issue_id),
                draft,
                draft.profile,
                "triage-revision-1",
            ),
            consent_id="consent-1",
            payer_agent_id="agent-third-party",
            payer_github_account_id="account-author",
            effective_at=NOW,
            readiness_id="ready-consent-1",
            registry=_registry(),
        )

    assert state.contracts == state.tasks == state.escrows == state.ledger == ()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("issue_id", "issue-other"),
        ("issue_revision_id", "issue-revision-other"),
        ("body_hash", "0" * 64),
        ("bank_wea", 4),
        ("profile", "spec-only"),
        ("mechanic", "linear"),
        ("mechanic_config_hash", "1" * 64),
        ("ruleset_hash", "2" * 64),
        ("tide_interface_version", "9.9"),
        ("executor_manifest_hash", "3" * 64),
        ("triage_snapshot_hash", "4" * 64),
    ],
)
def test_s_02h_each_mismatched_consent_field_fails_closed(
    field: str, value: object
) -> None:
    draft = _draft()
    triage = _triage()
    consent = replace(_consent(draft, triage), **{field: value})
    state = _triaged_state(draft, triage)

    with pytest.raises(IntakeError, match=field):
        candidate_state = record_author_consent(
            state,
            consent,
            registry=_registry(),
        )
        candidate_state = record_contract_readiness(
            candidate_state,
            _readiness(consent, triage),
            registry=_registry(),
        )
        _activate(candidate_state, draft)

    assert state.contracts == state.tasks == state.escrows == state.ledger == ()


def test_s_02h_consent_must_name_the_candidates_exact_triage_revision() -> None:
    draft = _draft()
    candidate_triage = _triage()
    other_triage = _triage(
        revision_id="triage-revision-2",
    )
    consent = _consent(draft, other_triage)
    state = IntakeState(balances=(AccountBalance("agent-author", 10),))
    state = assign_triage(
        state,
        TriageRole(
            role_id=candidate_triage.role_id,
            issue_id=draft.issue_id,
            funding_source="free",
        ),
        _assignment(),
        registry=_registry(),
    )
    state = record_triage(state, candidate_triage, registry=_registry())
    state = record_triage(state, other_triage, registry=_registry())
    state = complete_triage(
        state,
        _completion(candidate_triage, suffix="candidate"),
        registry=_registry(),
    )
    state = complete_triage(
        state,
        _completion(other_triage, suffix="other"),
        registry=_registry(),
    )
    state = record_author_consent(state, consent, registry=_registry())
    state = record_contract_readiness(
        state,
        _readiness(consent, other_triage),
        registry=_registry(),
    )

    with pytest.raises(IntakeError, match="triage_revision_id"):
        _activate(state, draft)

    assert state.contracts == state.tasks == state.escrows == state.ledger == ()


def test_activation_requires_recorded_exact_agent0_readiness() -> None:
    draft = _draft()
    triage = _triage()
    state = _state(draft, triage, _consent(draft, triage))
    state = replace(state, readiness=())

    with pytest.raises(IntakeError, match="readiness_id"):
        _activate(state, draft)

    assert state.contracts == state.tasks == state.escrows == state.ledger == ()


def test_readiness_requires_exact_agent0_binding_version() -> None:
    draft = _draft()
    triage = _triage()
    consent = _consent(draft, triage)
    state = _triaged_state(draft, triage)
    state = record_author_consent(state, consent, registry=_registry())

    with pytest.raises(IntakeError, match="agent0_binding_version"):
        record_contract_readiness(
            state,
            replace(_readiness(consent, triage), agent0_binding_version=2),
            registry=_registry(),
        )


def _override(triage: TriageRecord, *, effective_at: datetime) -> RouteOverride:
    snapshot = "operator override spec-only -> direct-pr"
    return RouteOverride(
        override_id="override-1",
        issue_id="issue-42",
        triage_role_id=triage.role_id,
        triage_revision_id=triage.revision_id,
        triage_snapshot_hash=triage.snapshot_hash,
        original_route="spec-only",
        new_route="direct-pr",
        reason="bounded implementation is sufficient",
        operator_github_account_id="account-operator",
        operator_binding_id="operator-role-binding",
        operator_binding_version=1,
        comment_id="override-comment",
        revision_id="override-revision",
        snapshot=snapshot,
        snapshot_hash=_hash(snapshot),
        effective_at=effective_at,
    )


def test_s_02i_route_change_requires_earlier_operator_override_and_fresh_consent() -> (
    None
):
    draft = _draft(profile="direct-pr")
    triage = _triage(route="spec-only")
    old_consent = _consent(draft, triage)
    state = _state(draft, triage, old_consent)

    with pytest.raises(IntakeError, match="route"):
        _activate(state, draft)

    late_override = _override(triage, effective_at=CONSENT_AT + timedelta(minutes=1))
    state = record_route_override(state, late_override, registry=_registry())
    with pytest.raises(IntakeError, match="route"):
        _activate(state, draft)

    fresh_consent = _consent(
        draft,
        triage,
        consent_id="consent-fresh",
        effective_at=CONSENT_AT + timedelta(minutes=2),
        override_id=late_override.override_id,
    )
    state = record_author_consent(state, fresh_consent, registry=_registry())
    state = record_contract_readiness(
        state,
        _readiness(fresh_consent, triage),
        registry=_registry(),
    )

    result = _activate(state, draft, fresh_consent.consent_id)

    assert result.contract.override_id == late_override.override_id
    assert result.task.profile == "direct-pr"
    assert result.state.balance("agent-author") == 7


def test_route_override_requires_exact_operator_binding_version() -> None:
    draft = _draft(profile="direct-pr")
    triage = _triage(route="spec-only")
    state = _triaged_state(draft, triage)

    with pytest.raises(IntakeError, match="operator_binding_version"):
        record_route_override(
            state,
            replace(
                _override(triage, effective_at=CONSENT_AT - timedelta(minutes=1)),
                operator_binding_version=2,
            ),
            registry=_registry(),
        )


def test_same_timestamp_override_and_consent_use_canonical_event_order() -> None:
    draft = _draft(profile="direct-pr")
    triage = _triage(route="spec-only")
    state = _triaged_state(draft, triage)
    same_time = CONSENT_AT
    override = replace(
        _override(triage, effective_at=same_time),
        comment_id="comment-a-override",
        revision_id="revision-a-override",
    )
    state = record_route_override(state, override, registry=_registry())
    consent = replace(
        _consent(
            draft,
            triage,
            consent_id="consent-same-time",
            effective_at=same_time,
            override_id=override.override_id,
        ),
        comment_id="comment-z-consent",
        revision_id="revision-z-consent",
    )
    state = record_author_consent(state, consent, registry=_registry())
    state = record_contract_readiness(
        state, _readiness(consent, triage), registry=_registry()
    )

    assert _activate(state, draft, consent.consent_id).contract.override_id == (
        override.override_id
    )

    reversed_override = replace(
        override,
        override_id="override-reversed",
        comment_id="comment-z-override",
        revision_id="revision-z-override",
    )
    reversed_state = record_route_override(
        _triaged_state(draft, triage), reversed_override, registry=_registry()
    )
    reversed_consent = replace(
        consent,
        consent_id="consent-reversed",
        comment_id="comment-a-consent",
        revision_id="revision-a-consent",
        override_id=reversed_override.override_id,
    )
    with pytest.raises(IntakeError, match="override must precede consent"):
        record_author_consent(reversed_state, reversed_consent, registry=_registry())
